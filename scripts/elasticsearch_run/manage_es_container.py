#!/usr/bin/env python3

# /// script
# dependencies = [
#     "docker",
# ]
# ///

import sys
import docker

CONTAINER_NAME = "elasticsearch-dev"
DEFAULT_IMAGE = "docker.elastic.co/elasticsearch/elasticsearch:8.15.1"

try:
    client = docker.from_env()
except docker.errors.DockerException:
    print("Error: Could not connect to the Docker daemon.", file=sys.stderr)
    print("Is the Docker daemon running?", file=sys.stderr)
    sys.exit(1)

def start_container(image=None):
    if image is None:
        image = DEFAULT_IMAGE
    
    try:
        container = client.containers.get(CONTAINER_NAME)
        
        # Check if existing container uses the same image
        existing_image = container.image.tags[0] if container.image.tags else container.image.id
        if existing_image != image:
            print(f"Container '{CONTAINER_NAME}' exists but uses different image:")
            print(f"  Existing: {existing_image}")
            print(f"  Requested: {image}")
            print("Recreating container with new image...")
            
            # Stop and remove existing container
            if container.status == 'running':
                container.stop()
            container.remove()
            
            # Create new container with requested image
            client.containers.run(
                image,
                name=CONTAINER_NAME,
                ports={"9200/tcp": 9200},
                environment=["discovery.type=single-node", "xpack.security.enabled=false"],
                detach=True,
                remove=False,
            )
            print("Container recreated and started.")
            return
        
        # Same image, just start if not running
        if container.status == 'running':
            print(f"Container '{CONTAINER_NAME}' is already running.")
            return
        else:
            print(f"Container '{CONTAINER_NAME}' exists, starting it...")
            container.start()
            print("Container started.")
    except docker.errors.NotFound:
        print(f"Container '{CONTAINER_NAME}' not found. Creating and starting...")
        try:
            client.containers.run(
                image,
                name=CONTAINER_NAME,
                ports={"9200/tcp": 9200},
                environment=["discovery.type=single-node", "xpack.security.enabled=false"],
                detach=True,
                remove=False,
            )
            print("Container created and started.")
        except Exception as e:
            print(f"Failed to create or start container: {e}", file=sys.stderr)
            sys.exit(1)

def stop_container(name=CONTAINER_NAME):
    try:
        container = client.containers.get(name)
        if container.status == 'running':
            print(f"Stopping container '{name}'...")
            container.stop()
            print("Container stopped.")
        else:
            print(f"Container '{name}' is already stopped.")
    except docker.errors.NotFound:
        print(f"Container '{name}' not found.")

def destroy_container():
    stop_container(CONTAINER_NAME)
    try:
        container = client.containers.get(CONTAINER_NAME)
        print("Removing container...")
        container.remove()
        print("Container removed.")
    except docker.errors.NotFound:
        print(f"Container '{CONTAINER_NAME}' not found, nothing to remove.")
    except Exception as e:
        print(f"An error occurred during removal: {e}", file=sys.stderr)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: manage_es_container.py [start|stop|destroy] [image]", file=sys.stderr)
        print("  start [image] - Start container (optionally with specific image)", file=sys.stderr)
        print("  stop          - Stop container", file=sys.stderr)
        print("  destroy       - Stop and remove container", file=sys.stderr)
        sys.exit(1)
    
    command = sys.argv[1]
    image = None
    if len(sys.argv) > 2:
        image = sys.argv[2]
    
    if command == "start":
        start_container(image)
    elif command == "stop":
        stop_container()
    elif command == "destroy":
        destroy_container()
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)
