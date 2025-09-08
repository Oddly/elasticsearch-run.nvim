#!/usr/bin/env python3

# /// script
# dependencies = [
#     "docker",
# ]
# ///

import os
import sys

import docker

CONTAINER_NAME = "logstash-dev"
DEFAULT_IMAGE = "docker.elastic.co/logstash/logstash:8.15.1"

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
        try:
            existing_image = (
                container.image.tags[0] if container.image.tags else container.image.id
            )
        except (IndexError, AttributeError):
            print(
                f"Warning: Could not determine existing container image, recreating container",
                file=sys.stderr,
            )
            existing_image = None
        if existing_image != image:
            print(f"Container '{CONTAINER_NAME}' exists but uses different image:")
            print(f"  Existing: {existing_image}")
            print(f"  Requested: {image}")
            print("Recreating container with new image...")

            # Stop and remove existing container
            try:
                if container.status == "running":
                    container.stop(timeout=10)
                container.remove()
            except docker.errors.APIError as e:
                print(
                    f"Error stopping/removing existing container: {e}", file=sys.stderr
                )
                sys.exit(1)

            create_container(name=CONTAINER_NAME, image=image)

            print("Container recreated and started.")
            return

        # Same image, just start if not running
        if container.status == "running":
            print(f"Container '{CONTAINER_NAME}' is already running.")
            return
        else:
            print(f"Container '{CONTAINER_NAME}' exists, starting it...")
            try:
                container.start()
                print("Container started.")
            except docker.errors.APIError as e:
                print(f"Error starting existing container: {e}", file=sys.stderr)
                sys.exit(1)
    except docker.errors.NotFound:
        print(f"Container '{CONTAINER_NAME}' not found.")
        create_container(name=CONTAINER_NAME, image=image)
        print(f"Container '{CONTAINER_NAME}' created and started.")


def stop_container(name=CONTAINER_NAME):
    try:
        container = client.containers.get(name)
        if container.status == "running":
            print(f"Stopping container '{name}'...")
            try:
                container.stop(timeout=10)
                print("Container stopped.")
            except docker.errors.APIError as e:
                print(f"Error stopping container: {e}", file=sys.stderr)
        else:
            print(f"Container '{name}' is already stopped.")
    except docker.errors.NotFound:
        print(f"Container '{name}' not found.")


def create_container(name, image):
    # Create new container with requested image
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_dir = os.path.join(script_dir, "logstash_configs")
    os.makedirs(config_dir, exist_ok=True)

    client.containers.run(
        image=image,
        name=name,
        ports={
            "8080/tcp": 8080,
            "9999/tcp": 9999,
        },  # HTTP input and result output
        volumes={
            config_dir: {
                "bind": "/etc/logstash/",
                "mode": "ro",
            }
        },
        environment=[
            "xpack.monitoring.enabled=false",
            "pipeline.batch.size=125",
            "pipeline.batch.delay=5",
            "pipeline.workers=2",
            "queue.type=memory",
            "pipeline.unsafe_shutdown=true",
            "log.level=warn",
            "http.host=0.0.0.0",
        ],
        detach=True,
        remove=False,
        stdin_open=True,
    )


def destroy_container():
    stop_container(CONTAINER_NAME)
    try:
        container = client.containers.get(CONTAINER_NAME)

        # Clean up any temporary directories that might be mounted
        try:
            mounts = container.attrs.get("Mounts", [])
            for mount in mounts:
                if mount.get("Source", "").startswith("/tmp/logstash_output_"):
                    temp_dir = mount["Source"]
                    print(f"Cleaning up temporary directory: {temp_dir}")
                    import shutil

                    shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception as cleanup_error:
            print(
                f"Warning: Could not clean up temporary directories: {cleanup_error}",
                file=sys.stderr,
            )

        print("Removing container...")
        container.remove()
        print("Container removed.")
    except docker.errors.NotFound:
        print(f"Container '{CONTAINER_NAME}' not found, nothing to remove.")
    except Exception as e:
        print(f"An error occurred during removal: {e}", file=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(
            "Usage: manage_logstash_container.py [start|stop|destroy] [image]",
            file=sys.stderr,
        )
        print(
            "  start [image] - Start container (optionally with specific image)",
            file=sys.stderr,
        )
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
