#!/usr/bin/env python3
# /// script
# dependencies = ["docker"]
# ///
import os
import sys
import docker
import argparse
import shutil

# ... (Constants and client setup remain the same) ...
CONTAINER_NAME = "logstash-dev"
DEFAULT_IMAGE = "docker.elastic.co/logstash/logstash:8.15.1"
DEFAULT_PIPELINE = "default_pipeline.conf"
CONFIG_LABEL = "com.elasticsearch-run.pipeline-config"
try:
    client = docker.from_env()
except docker.errors.DockerException:
    print("Error: Could not connect to the Docker daemon.", file=sys.stderr)
    sys.exit(1)

# ... (start_container function remains the same) ...
def start_container(image=None, pipeline_file=None):
    if image is None:
        image = DEFAULT_IMAGE
    desired_config_key = pipeline_file if pipeline_file else DEFAULT_PIPELINE
    try:
        container = client.containers.get(CONTAINER_NAME)
        if container.status == "running":
            running_config_key = container.labels.get(CONFIG_LABEL, "unknown")
            if running_config_key != desired_config_key:
                print(f"Error: Container is running with a different pipeline ('{running_config_key}').", file=sys.stderr)
                print(f"Please run 'uv run ./manage_logstash_container.py destroy' first to switch to '{desired_config_key}'.", file=sys.stderr)
                sys.exit(1)
            else:
                print(f"Container '{CONTAINER_NAME}' is already running with the correct pipeline ('{running_config_key}').")
                return
        print(f"Container '{CONTAINER_NAME}' exists, starting it...", file=sys.stderr)
        container.start()
        print("Container started.")
    except docker.errors.NotFound:
        print(f"Container '{CONTAINER_NAME}' not found. Creating and starting...", file=sys.stderr)
        create_container(name=CONTAINER_NAME, image=image, pipeline_file=pipeline_file)
        print(f"Container '{CONTAINER_NAME}' created and started with pipeline: '{desired_config_key}'.")


def create_container(name, image, pipeline_file=None):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_dir = os.path.join(script_dir, "logstash_configs")
    
    pipeline_to_mount = pipeline_file if pipeline_file else DEFAULT_PIPELINE
    pipeline_source_path = os.path.join(config_dir, "conf.d", pipeline_to_mount)
    if not os.path.exists(pipeline_source_path):
        print(f"Error: Pipeline file not found at {pipeline_source_path}", file=sys.stderr)
        sys.exit(1)

    yml_source_path = os.path.join(config_dir, "logstash.yml")
    if not os.path.exists(yml_source_path):
        print(f"Error: logstash.yml not found at {yml_source_path}", file=sys.stderr)
        sys.exit(1)
    
    volumes = {
        yml_source_path: {"bind": "/usr/share/logstash/config/logstash.yml", "mode": "rw"},
        pipeline_source_path: {"bind": "/usr/share/logstash/pipeline/logstash.conf", "mode": "rw"}
    }

    client.containers.run(
        image=image,
        name=name,
        ports={"8080/tcp": 8080},
        volumes=volumes,
        # THE FIX: Explicitly map host.docker.internal to the host gateway.
        # This makes container-to-host communication reliable on all platforms.
        extra_hosts={"host.docker.internal": "host-gateway"},
        command=["--config.reload.automatic"],
        labels={CONFIG_LABEL: pipeline_to_mount},
        environment=["xpack.monitoring.enabled=false", "http.host=0.0.0.0"],
        detach=True,
        remove=False,
    )

# ... (destroy_container and stop_container functions remain the same) ...
def destroy_container():
    try:
        container = client.containers.get(CONTAINER_NAME)
        print(f"Stopping container '{CONTAINER_NAME}'...")
        container.stop(timeout=10)
        print(f"Removing container '{CONTAINER_NAME}'...")
        container.remove()
        print("Container removed.")
    except docker.errors.NotFound:
        print(f"Container '{CONTAINER_NAME}' not found.")

def stop_container():
    try:
        container = client.containers.get(CONTAINER_NAME)
        if container.status == "running":
            print(f"Stopping container '{CONTAINER_NAME}'...")
            container.stop(timeout=10)
            print("Container stopped.")
        else:
            print(f"Container '{CONTAINER_NAME}' is already stopped.")
    except docker.errors.NotFound:
        print(f"Container '{CONTAINER_NAME}' not found.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Manage the Logstash development container.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    parser_start = subparsers.add_parser("start", help="Start or create the Logstash container.")
    parser_start.add_argument("image", nargs="?", default=DEFAULT_IMAGE, help=f"The Docker image to use (default: {DEFAULT_IMAGE}).")
    parser_start.add_argument("--pipeline", help=f"Specify a pipeline .conf file from 'logstash_configs/conf.d/'.")
    subparsers.add_parser("stop", help="Stop the Logstash container.")
    subparsers.add_parser("destroy", help="Stop and remove the container.")
    args = parser.parse_args()
    if args.command == "start":
        start_container(image=args.image, pipeline_file=args.pipeline)
    elif args.command == "stop":
        stop_container()
    elif args.command == "destroy":
        destroy_container()
