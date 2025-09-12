#!/usr/bin/env python3
# /// script
# dependencies = ["docker", "click", "python-dotenv", "psutil"]
# ///
import click
import docker
import os
import psutil
import sys
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

# --- Constanten ---
DEFAULT_IMAGE = "docker.elastic.co/logstash/logstash:8.15.1"
CONTAINER_NAME = os.getenv("LOGSTASH_CONTAINER_NAME")
NETWORK_NAME = os.getenv("NETWORK_NAME")
LOGSTASH_PORT = os.getenv("LOGSTASH_PORT")
LOGSTASH_HEAP_SIZE = os.getenv("LOGSTASH_HEAP_SIZE", "2g")
LOGSTASH_PIPELINE_WORKERS = os.getenv("LOGSTASH_PIPELINE_WORKERS") or str(psutil.cpu_count() or 1)
CONFIG_LABEL = "com.elasticsearch-run.pipeline-config"

client = docker.from_env()

def ensure_network():
    try:
        client.networks.get(NETWORK_NAME)
    except docker.errors.NotFound:
        print(f"Netwerk '{NETWORK_NAME}' wordt aangemaakt...")
        client.networks.create(NETWORK_NAME, driver="bridge")

@click.group()
def cli():
    """Beheer de Logstash container."""
    pass

@cli.command()
@click.option('--pipeline', 'pipeline_file', required=True, type=click.Path(exists=True, resolve_path=True), help="Pad naar het Logstash pipeline .conf bestand.")
@click.option('--image', default=DEFAULT_IMAGE, help="De te gebruiken Docker image.")
def start(pipeline_file, image):
    """Start de Logstash container met een specifieke pipeline."""
    ensure_network()
    pipeline_key = os.getenv("PIPELINE_ID", os.path.basename(pipeline_file))

    try:
        container = client.containers.get(CONTAINER_NAME)
        if container.status == "running":
            running_config_key = container.labels.get(CONFIG_LABEL, "unknown")
            if running_config_key != pipeline_key:
                print(f"Error: Container draait met een andere pipeline ('{running_config_key}'). Stop/verwijder deze eerst.")
                sys.exit(1)
            else:
                print(f"Container '{CONTAINER_NAME}' draait al met de juiste pipeline.")
                return
        print(f"Bestaande container '{CONTAINER_NAME}' wordt gestart...")
        container.start()
    except docker.errors.NotFound:
        print(f"Container '{CONTAINER_NAME}' wordt aangemaakt en gestart...")
        
        config_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config")
        
        volumes = {
            os.path.join(config_dir, "logstash.yml"): {"bind": "/usr/share/logstash/config/logstash.yml", "mode": "rw"},
            os.path.join(config_dir, "log4j2.properties"): {"bind": "/usr/share/logstash/config/log4j2.properties", "mode": "rw"},
            pipeline_file: {"bind": "/usr/share/logstash/pipeline/logstash.conf", "mode": "rw"}
        }

        environment = [
            "xpack.monitoring.enabled=false",
            f"LS_JAVA_OPTS=-Xms{LOGSTASH_HEAP_SIZE} -Xmx{LOGSTASH_HEAP_SIZE}",
            f"PIPELINE_WORKERS={LOGSTASH_PIPELINE_WORKERS}"
        ]
        
        client.containers.run(
            image=image, name=CONTAINER_NAME, network=NETWORK_NAME,
            ports={f"{LOGSTASH_PORT}/tcp": ("127.0.0.1", int(LOGSTASH_PORT))},
            volumes=volumes,
            environment=environment,
            labels={CONFIG_LABEL: pipeline_key},
            detach=True
        )
    print(f"Container '{CONTAINER_NAME}' is gestart met pipeline '{pipeline_key}'.")

@cli.command()
def stop():
    """Stopt de container."""
    try:
        container = client.containers.get(CONTAINER_NAME)
        print("Container wordt gestopt...")
        container.stop()
        print("Container gestopt.")
    except docker.errors.NotFound:
        print("Container niet gevonden.")

@cli.command()
def destroy():
    """Stopt en verwijdert de container."""
    try:
        container = client.containers.get(CONTAINER_NAME)
        print("Container wordt gestopt en verwijderd...")
        container.remove(force=True)
        print("Container verwijderd.")
    except docker.errors.NotFound:
        print("Container niet gevonden.")

if __name__ == '__main__':
    cli()