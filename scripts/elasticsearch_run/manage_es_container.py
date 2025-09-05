#!/usr/bin/env python3

# /// script
# dependencies = [
#     "docker",
# ]
# ///

import sys
import docker

CONTAINER_NAME = "elasticsearch-dev"

try:
    client = docker.from_env()
except docker.errors.DockerException:
    print("Error: Could not connect to the Docker daemon.", file=sys.stderr)
    print("Is the Docker daemon running?", file=sys.stderr)
    sys.exit(1)

def start_container():
    try:
        container = client.containers.get(CONTAINER_NAME)
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
            # You may want to update this version over time
            client.containers.run(
                "docker.elastic.co/elasticsearch/elasticsearch:8.16.4",
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
    # If a command IS provided (stop, destroy)...
    if len(sys.argv) > 1:
        command = sys.argv[1]
        if command == "stop":
            stop_container()
        elif command == "destroy":
            destroy_container()
        else:
            print(f"Unknown command: {command}", file=sys.stderr)
            sys.exit(1)
    # If NO command is provided, run the default action.
    else:
        start_container()
