#!/usr/bin/env python3
# /// script
# dependencies = ["docker", "click", "python-dotenv"]
# ///
import click
import docker
import os
import sys
from dotenv import load_dotenv

# Laad .env vanuit de bovenliggende map
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

# --- Constanten uit .env ---
CONTAINER_NAME = os.getenv("LISTENER_CONTAINER_NAME")
IMAGE_NAME = os.getenv("LISTENER_IMAGE_NAME")
NETWORK_NAME = os.getenv("NETWORK_NAME")
LISTENER_PORT = os.getenv("LISTENER_PORT")
client = docker.from_env()

def ensure_network():
    """Zorgt ervoor dat ons gedeelde Docker-netwerk bestaat."""
    try:
        client.networks.get(NETWORK_NAME)
    except docker.errors.NotFound:
        print(f"Netwerk '{NETWORK_NAME}' wordt aangemaakt...")
        client.networks.create(NETWORK_NAME, driver="bridge")

@click.group()
def cli():
    """Beheer de Listener container."""
    pass

@cli.command()
def build():
    """Bouwt de Docker image."""
    print(f"Image '{IMAGE_NAME}' wordt gebouwd...")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    try:
        client.images.build(path=script_dir, dockerfile="Dockerfile", tag=IMAGE_NAME, rm=True)
        print("Image succesvol gebouwd.")
    except docker.errors.BuildError as e:
        print(f"Fout tijdens het bouwen van de image: {e}")

@cli.command()
def start():
    """Start de container."""
    ensure_network()
    
    # Check if image exists, build if not
    try:
        client.images.get(IMAGE_NAME)
    except docker.errors.ImageNotFound:
        print(f"Image '{IMAGE_NAME}' niet gevonden, wordt gebouwd...")
        script_dir = os.path.dirname(os.path.abspath(__file__))
        try:
            # Build with no auth to avoid credential store issues
            client.images.build(
                path=script_dir, 
                dockerfile="Dockerfile", 
                tag=IMAGE_NAME, 
                rm=True,
                pull=True
            )
            print("Image succesvol gebouwd.")
        except Exception as e:  # Catch all Docker SDK errors
            print(f"Docker SDK build failed: {e}")
            print("Trying fallback build with docker command...")
            # Fallback to docker command if SDK fails
            import subprocess
            try:
                subprocess.run(
                    ["docker", "build", "-t", IMAGE_NAME, script_dir], 
                    check=True, 
                    capture_output=True, 
                    text=True
                )
                print("Image succesvol gebouwd via docker command.")
            except subprocess.CalledProcessError as cmd_e:
                print(f"Fout tijdens het bouwen van de image: {cmd_e.stderr}")
                sys.exit(1)
    
    try:
        container = client.containers.get(CONTAINER_NAME)
        if container.status != "running":
            print(f"Container '{CONTAINER_NAME}' wordt gestart...")
            container.start()
        else:
            print(f"Container '{CONTAINER_NAME}' draait al.")
    except docker.errors.NotFound:
        print(f"Container '{CONTAINER_NAME}' wordt aangemaakt en gestart...")
        client.containers.run(
            image=IMAGE_NAME, name=CONTAINER_NAME, network=NETWORK_NAME,
            ports={f"{LISTENER_PORT}/tcp": ("127.0.0.1", int(LISTENER_PORT))}, detach=True, remove=False
        )
    print(f"Container '{CONTAINER_NAME}' is gestart op netwerk '{NETWORK_NAME}'.")

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