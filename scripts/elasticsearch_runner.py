#!/usr/bin/env python3
# /// script
# dependencies = ["docker", "httpx", "click", "python-dotenv", "jinja2", "psutil"]
# ///
"""
Modern Python replacement for elasticsearch_runner.sh
Provides unified container orchestration with async operations and better performance.
"""

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import tempfile
import signal

import click
import docker
import httpx
import psutil
from dotenv import load_dotenv
from jinja2 import Template

# Load environment
load_dotenv()

# --- Configuration ---
NETWORK_NAME = os.getenv("NETWORK_NAME", "es-run-net")
LOGSTASH_CONTAINER_NAME = os.getenv("LOGSTASH_CONTAINER_NAME", "es-run-logstash") 
LISTENER_CONTAINER_NAME = os.getenv("LISTENER_CONTAINER_NAME", "es-run-listener")
LISTENER_IMAGE_NAME = os.getenv("LISTENER_IMAGE_NAME", "es-run-listener-img")
LOGSTASH_PORT = int(os.getenv("LOGSTASH_PORT", "8080"))
LISTENER_PORT = int(os.getenv("LISTENER_PORT", "8081"))
ELASTICSEARCH_PORT = 9200
LOGSTASH_HEAP_SIZE = os.getenv("LOGSTASH_HEAP_SIZE", "4g")
LOGSTASH_PIPELINE_WORKERS = os.getenv("LOGSTASH_PIPELINE_WORKERS") or str(psutil.cpu_count() or 1)

# Container names
ES_CONTAINER_NAME = "es-run-elasticsearch"
DEFAULT_ES_IMAGE = "docker.elastic.co/elasticsearch/elasticsearch:8.15.1"
DEFAULT_LOGSTASH_IMAGE = "docker.elastic.co/logstash/logstash:8.15.1"

# --- Logging Setup ---
class ColoredFormatter(logging.Formatter):
    """Colored logging formatter matching bash script style"""
    
    COLORS = {
        'DEBUG': '\033[0;36m',    # Cyan
        'INFO': '\033[0;32m',     # Green  
        'WARNING': '\033[1;33m',  # Yellow
        'ERROR': '\033[0;31m',    # Red
        'CRITICAL': '\033[1;31m', # Bold Red
    }
    RESET = '\033[0m'
    
    def format(self, record):
        color = self.COLORS.get(record.levelname, '')
        record.levelname = f"{color}{record.levelname}{self.RESET}"
        return super().format(record)

def setup_logging(verbose: bool = False, debug: bool = False):
    level = logging.DEBUG if debug else logging.INFO if verbose else logging.WARNING
    
    formatter = ColoredFormatter(
        fmt="[%(asctime)s] - PYTHON - %(levelname)s - %(message)s",
        datefmt="%H:%M:%S.%f"
    )
    
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)
    
    logger = logging.getLogger()
    logger.setLevel(level)
    logger.addHandler(handler)
    
    return logger

# --- Container Management ---
class ContainerOrchestrator:
    """Unified container orchestration with shared Docker client"""
    
    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.docker_client = docker.from_env()
        self.http_client = httpx.AsyncClient(timeout=30.0)
        self.containers_to_cleanup = []
        self._keep_alive = False
        
    async def __aenter__(self):
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.cleanup(self._keep_alive)
        
    def ensure_network(self):
        """Ensure Docker network exists"""
        try:
            self.docker_client.networks.get(NETWORK_NAME)
            self.logger.debug(f"Network '{NETWORK_NAME}' already exists")
        except docker.errors.NotFound:
            self.logger.info(f"Creating network '{NETWORK_NAME}'...")
            self.docker_client.networks.create(NETWORK_NAME, driver="bridge")
            
    def build_listener_image_if_needed(self):
        """Build listener image if it doesn't exist"""
        try:
            self.docker_client.images.get(LISTENER_IMAGE_NAME)
            self.logger.debug(f"Image '{LISTENER_IMAGE_NAME}' already exists")
        except docker.errors.ImageNotFound:
            self.logger.info(f"Building image '{LISTENER_IMAGE_NAME}'...")
            script_dir = Path(__file__).parent / "docker" / "listener"
            
            try:
                self.docker_client.images.build(
                    path=str(script_dir),
                    dockerfile="Dockerfile", 
                    tag=LISTENER_IMAGE_NAME,
                    rm=True
                )
                self.logger.info("Image built successfully via Docker SDK")
            except Exception as e:
                self.logger.warning(f"Docker SDK build failed: {e}")
                self.logger.info("Falling back to docker command...")
                
                import subprocess
                result = subprocess.run(
                    ["docker", "build", "-t", LISTENER_IMAGE_NAME, str(script_dir)],
                    capture_output=True, text=True
                )
                if result.returncode != 0:
                    raise RuntimeError(f"Docker build failed: {result.stderr}")
                self.logger.info("Image built successfully via docker command")
                
    async def start_elasticsearch(self) -> docker.models.containers.Container:
        """Start Elasticsearch container"""
        container_name = ES_CONTAINER_NAME
        
        try:
            container = self.docker_client.containers.get(container_name)
            if container.status == "running":
                self.logger.debug("Elasticsearch already running")
                return container
            else:
                self.logger.info("Starting existing Elasticsearch container...")
                container.start()
                return container
        except docker.errors.NotFound:
            self.logger.info("Creating new Elasticsearch container...")
            
            environment = [
                "discovery.type=single-node",
                "xpack.security.enabled=false", 
                "ES_JAVA_OPTS=-Xms2g -Xmx2g"
            ]
            
            container = self.docker_client.containers.run(
                image=DEFAULT_ES_IMAGE,
                name=container_name,
                network=NETWORK_NAME,
                ports={"9200/tcp": ("127.0.0.1", ELASTICSEARCH_PORT)},
                environment=environment,
                detach=True
            )
            
            self.containers_to_cleanup.append(container_name)
            return container
            
    async def start_listener(self) -> docker.models.containers.Container:
        """Start listener container"""
        self.build_listener_image_if_needed()
        
        try:
            container = self.docker_client.containers.get(LISTENER_CONTAINER_NAME)
            if container.status == "running":
                self.logger.debug("Listener already running")
                return container
            else:
                self.logger.info("Starting existing listener container...")
                container.start()
                return container
        except docker.errors.NotFound:
            self.logger.info("Creating new listener container...")
            
            container = self.docker_client.containers.run(
                image=LISTENER_IMAGE_NAME,
                name=LISTENER_CONTAINER_NAME,
                network=NETWORK_NAME,
                ports={f"{LISTENER_PORT}/tcp": ("127.0.0.1", LISTENER_PORT)},
                detach=True,
                remove=False
            )
            
            self.containers_to_cleanup.append(LISTENER_CONTAINER_NAME)
            return container
            
    async def start_logstash(self, pipeline_config: str, pipeline_id: str) -> docker.models.containers.Container:
        """Start Logstash container with dynamic pipeline"""
        
        # Check if container exists 
        try:
            container = self.docker_client.containers.get(LOGSTASH_CONTAINER_NAME)
            if container.status == "running":
                current_pipeline = container.labels.get("com.elasticsearch-run.pipeline-config", "")
                if current_pipeline == pipeline_id:
                    self.logger.debug(f"Logstash already running with correct pipeline '{pipeline_id}'")
                    return container
                else:
                    self.logger.info(f"Restarting Logstash with new pipeline '{pipeline_id}'")
                    container.remove(force=True)
            else:
                # Container exists but not running (created, exited, etc.) - remove it
                self.logger.info(f"Removing existing Logstash container (status: {container.status})")
                container.remove(force=True)
        except docker.errors.NotFound:
            pass
            
        self.logger.info(f"Creating Logstash container with pipeline '{pipeline_id}'...")
        
        # Create temporary pipeline file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.conf', delete=False) as f:
            f.write(pipeline_config)
            temp_pipeline = f.name
            
        try:
            # Create config directory structure
            config_dir = Path(__file__).parent / "docker" / "logstash" / "config"
            
            volumes = {
                str(config_dir / "logstash.yml"): {"bind": "/usr/share/logstash/config/logstash.yml", "mode": "rw"},
                str(config_dir / "log4j2.properties"): {"bind": "/usr/share/logstash/config/log4j2.properties", "mode": "rw"},  
                temp_pipeline: {"bind": "/usr/share/logstash/pipeline/logstash.conf", "mode": "rw"}
            }
            
            environment = [
                "xpack.monitoring.enabled=false",
                f"LS_JAVA_OPTS=-Xms{LOGSTASH_HEAP_SIZE} -Xmx{LOGSTASH_HEAP_SIZE}",
                f"PIPELINE_WORKERS={LOGSTASH_PIPELINE_WORKERS}"
            ]
            
            container = self.docker_client.containers.run(
                image=DEFAULT_LOGSTASH_IMAGE,
                name=LOGSTASH_CONTAINER_NAME,
                network=NETWORK_NAME,
                ports={f"{LOGSTASH_PORT}/tcp": ("127.0.0.1", LOGSTASH_PORT)},
                volumes=volumes,
                environment=environment,
                labels={"com.elasticsearch-run.pipeline-config": pipeline_id},
                detach=True
            )
            
            self.containers_to_cleanup.append(LOGSTASH_CONTAINER_NAME)
            return container
            
        finally:
            # Clean up temp file
            try:
                os.unlink(temp_pipeline)
            except:
                pass
                
    async def wait_for_service(self, url: str, service_name: str, timeout: int = 60) -> bool:
        """Wait for service to be ready with exponential backoff"""
        self.logger.info(f"Waiting for {service_name} at {url}...")
        
        start_time = time.time()
        delays = [0.5, 1, 2, 4, 8]  # Exponential backoff
        delay_idx = 0
        
        while time.time() - start_time < timeout:
            try:
                response = await self.http_client.get(url, timeout=2.0)
                if response.status_code == 200:
                    elapsed = int(time.time() - start_time)
                    self.logger.info(f"{service_name} ready after {elapsed} seconds")
                    return True
            except (httpx.RequestError, httpx.TimeoutException):
                pass
                
            delay = delays[min(delay_idx, len(delays) - 1)]
            await asyncio.sleep(delay)
            delay_idx += 1
            
        self.logger.error(f"{service_name} failed to start within {timeout}s")
        return False
        
    async def start_all_services(self, pipeline_config: str, pipeline_id: str = "default") -> bool:
        """Start all services in parallel and wait for readiness"""
        self.ensure_network()
        
        # Start containers in parallel
        self.logger.info("Starting all containers in parallel...")
        start_time = time.time()
        
        tasks = [
            self.start_elasticsearch(),
            self.start_listener(), 
            self.start_logstash(pipeline_config, pipeline_id)
        ]
        
        try:
            containers = await asyncio.gather(*tasks)
            startup_time = time.time() - start_time
            self.logger.info(f"Container startup completed in {startup_time:.1f}s")
            
            # Wait for services to be ready in parallel  
            health_tasks = [
                self.wait_for_service(f"http://localhost:{ELASTICSEARCH_PORT}", "Elasticsearch", 60),
                self.wait_for_service(f"http://localhost:{LISTENER_PORT}/health", "Listener", 30),
                self.wait_for_service(f"http://localhost:{LOGSTASH_PORT}", "Logstash", 60)
            ]
            
            results = await asyncio.gather(*health_tasks)
            
            if all(results):
                total_time = time.time() - start_time  
                self.logger.info(f"All services ready in {total_time:.1f}s")
                return True
            else:
                self.logger.error("Some services failed to start")
                return False
                
        except Exception as e:
            self.logger.error(f"Container startup failed: {e}")
            return False
            
    async def process_through_logstash(self, docs: List[Dict]) -> List[Dict]:
        """Send documents through Logstash and capture results"""
        self.logger.info(f"Processing {len(docs)} documents through Logstash...")
        
        # Start capturing listener output
        listener_container = self.docker_client.containers.get(LISTENER_CONTAINER_NAME)
        
        # Send documents to Logstash
        headers = {"Content-Type": "application/x-ndjson"}
        ndjson_payload = "\n".join(json.dumps(doc) for doc in docs)
        
        try:
            response = await self.http_client.post(
                f"http://localhost:{LOGSTASH_PORT}",
                content=ndjson_payload,
                headers=headers,
                timeout=20.0
            )
            response.raise_for_status()
            self.logger.debug("Data sent to Logstash successfully")
        except httpx.RequestError as e:
            raise RuntimeError(f"Failed to send data to Logstash: {e}")
            
        # Wait for processing and get results
        await asyncio.sleep(3)  # Give processing time
        
        # Get listener logs (processed results)
        logs = listener_container.logs(since=int(time.time() - 10)).decode()
        
        # Parse JSON results from logs
        results = []
        for line in logs.split('\n'):
            if line.strip() and not line.startswith('[') and '{' in line:
                try:
                    result = json.loads(line.strip())
                    results.append(result)
                except json.JSONDecodeError:
                    continue
                    
        self.logger.info(f"Received {len(results)} processed documents")
        return results
        
    async def simulate_elasticsearch(self, pipeline: Dict, processed_docs: List[Dict]) -> Dict:
        """Run Elasticsearch ingest pipeline simulation"""
        self.logger.info("Running Elasticsearch ingest pipeline simulation...")
        
        # Format docs for ES simulation
        docs_array = [{"_source": doc} for doc in processed_docs]
        payload = {
            "pipeline": pipeline,
            "docs": docs_array
        }
        
        try:
            response = await self.http_client.post(
                f"http://localhost:{ELASTICSEARCH_PORT}/_ingest/pipeline/_simulate",
                json=payload,
                timeout=30.0
            )
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            raise RuntimeError(f"Elasticsearch simulation failed: {e}")
            
    async def cleanup(self, keep_alive: bool = False):
        """Clean up containers"""
        if keep_alive:
            self.logger.info("Containers left running (--keep-alive option)")
            cleanup_cmd = " && ".join([
                f"docker rm -f {name}" for name in self.containers_to_cleanup
            ])
            self.logger.info(f"To manually cleanup: {cleanup_cmd}")
        else:
            self.logger.info("Shutting down containers...")
            for container_name in self.containers_to_cleanup:
                try:
                    container = self.docker_client.containers.get(container_name)
                    container.remove(force=True)
                    self.logger.debug(f"Removed {container_name}")
                except docker.errors.NotFound:
                    pass
            self.logger.info("Cleanup complete")
            
        await self.http_client.aclose()

# --- Pipeline Generation ---
def build_pipeline_config(filter_file: Optional[str] = None, working_directory: Optional[str] = None) -> Tuple[str, str]:
    """Build Logstash pipeline configuration from template and filter
    
    Args:
        filter_file: Explicit filter file path
        working_directory: Directory to search for project-specific pipeline files
    """
    
    # Input template
    input_config = """
    http {
        port => 8080
        codec => "json_lines"
    }
    """.strip()
    
    # Auto-detect project-specific pipeline file if not explicitly provided
    if not filter_file and working_directory:
        project_pipeline_candidates = [
            "logstash.conf",
            "pipeline.conf", 
            "filter.conf",
            f"{Path(working_directory).name}.conf",  # e.g., oots.conf for ~/projects/oots/
            ".logstash.conf",  # Hidden file variant
        ]
        
        for candidate in project_pipeline_candidates:
            candidate_path = Path(working_directory) / candidate
            if candidate_path.exists():
                filter_file = str(candidate_path)
                print(f"Auto-detected project pipeline: {candidate}")
                break
    
    # Filter configuration
    if filter_file and Path(filter_file).exists():
        with open(filter_file, 'r') as f:
            filter_content = f.read().strip()
        pipeline_id = Path(filter_file).stem
        
        # Check if filter already contains filter { } wrapper
        if filter_content.startswith('filter {'):
            # Extract content inside filter { }
            # Find the opening brace and extract everything until the last closing brace
            start_idx = filter_content.find('{') + 1
            # Count braces to find the matching closing brace
            brace_count = 0
            end_idx = len(filter_content) - 1
            for i in range(len(filter_content) - 1, -1, -1):
                if filter_content[i] == '}':
                    if brace_count == 0:
                        end_idx = i
                        break
                    brace_count -= 1
                elif filter_content[i] == '{':
                    brace_count += 1
            filter_config = filter_content[start_idx:end_idx].strip()
        else:
            filter_config = filter_content
    else:
        # Default empty filter
        filter_config = "# No additional filtering"
        pipeline_id = "default"
        
    # Output template
    output_config = f"""
    http {{
        url => "http://{LISTENER_CONTAINER_NAME}:{LISTENER_PORT}/"
        http_method => "post"
        format => "json_batch"
        keepalive => false
    }}
    """.strip()
    
    # Build complete pipeline
    pipeline = f"""
input {{
{input_config}
}}

filter {{
{filter_config}
}}

output {{
{output_config}
}}
    """.strip()
    
    return pipeline, pipeline_id

# --- Main CLI ---
async def async_main(verbose: bool, quiet: bool, debug: bool, keep_alive: bool, pipeline: Optional[str], cwd: Optional[str]):
    
    # Setup logging (but suppress if quiet mode)
    logger = setup_logging(verbose and not quiet, debug and not quiet)
    
    # Setup signal handling
    def signal_handler(signum, frame):
        logger.info("Received interrupt signal, cleaning up...")
        sys.exit(1)
        
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        # Read input payload
        if not quiet:
            logger.info("Reading JSON payload from stdin...")
            
        payload_text = sys.stdin.read()
        if not payload_text.strip():
            logger.error("No input received from stdin")
            sys.exit(1)
            
        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON received: {e}")
            sys.exit(1)
            
        # Extract pipeline and documents
        pipeline_def = payload.get('pipeline')
        docs_data = payload.get('docs', [])
        
        if not pipeline_def:
            logger.error("No Elasticsearch ingest pipeline found in payload")
            sys.exit(1)
            
        if not docs_data:
            logger.error("No documents found in payload")
            sys.exit(1)
            
        # Extract document sources
        docs = []
        for doc in docs_data:
            if '_source' in doc:
                docs.append(doc['_source'])
            else:
                docs.append(doc)
                
        if not quiet:
            logger.info(f"Found {len(docs)} documents to process")
            
        # Build pipeline configuration with auto-detection
        working_dir = cwd or os.getcwd()
        pipeline_config, pipeline_id = build_pipeline_config(pipeline, working_dir)
        
        # Process through containers
        async with ContainerOrchestrator(logger) as orchestrator:
            # Start all services
            if not await orchestrator.start_all_services(pipeline_config, pipeline_id):
                logger.error("Failed to start services")
                sys.exit(1)
                
            # Process documents through Logstash
            processed_docs = await orchestrator.process_through_logstash(docs)
            
            if not processed_docs:
                logger.error("Logstash processing returned no results")
                sys.exit(1)
                
            # Run Elasticsearch simulation
            es_result = await orchestrator.simulate_elasticsearch(pipeline_def, processed_docs)
            
            # Set keep_alive flag for context manager cleanup
            orchestrator._keep_alive = keep_alive
            
        # Output results
        if 'error' in es_result:
            logger.error("Elasticsearch simulation failed:")
            if not quiet:
                logger.error(json.dumps(es_result, indent=2))
            sys.exit(1)
        else:
            if quiet:
                # Output only the processed document sources
                for doc in es_result.get('docs', []):
                    if 'doc' in doc and '_source' in doc['doc']:
                        print(json.dumps(doc['doc']['_source']))
            else:
                logger.info("Processing complete - success!")
                for doc in es_result.get('docs', []):
                    if 'doc' in doc and '_source' in doc['doc']:
                        print(json.dumps(doc['doc']['_source']))
        
    except Exception as e:
        logger.error(f"Pipeline processing failed: {e}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        sys.exit(1)

@click.command()
@click.option('-v', '--verbose', is_flag=True, help='Verbose logging')
@click.option('-q', '--quiet', is_flag=True, help='Quiet output (JSON only)')
@click.option('-d', '--debug', is_flag=True, help='Debug logging') 
@click.option('-k', '--keep-alive', is_flag=True, help='Keep containers running after completion')
@click.option('--pipeline', type=click.Path(exists=True), help='Custom Logstash filter file')
@click.option('--cwd', type=click.Path(exists=True, file_okay=False), help='Working directory for auto-detecting project pipelines')
def main(verbose: bool, quiet: bool, debug: bool, keep_alive: bool, pipeline: Optional[str], cwd: Optional[str]):
    """
    Modern Python Elasticsearch pipeline processor.
    
    Reads JSON payload from stdin and processes it through:
    Logstash → Elasticsearch simulation → JSON output
    """
    asyncio.run(async_main(verbose, quiet, debug, keep_alive, pipeline, cwd))

if __name__ == '__main__':
    main()