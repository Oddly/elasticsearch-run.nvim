#!/usr/bin/env python3
# /// script
# dependencies = ["docker", "click", "python-dotenv"]
# ///
import click
import docker
import os
import sys
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

# --- Constanten ---
DEFAULT_IMAGE = "docker.elastic.co/elasticsearch/elasticsearch:8.15.1"
CONTAINER_NAME = "es-run-elasticsearch"
NETWORK_NAME = os.getenv("NETWORK_NAME")

client = docker.from_env()

def ensure_network():
    try:
        client.networks.get(NETWORK_NAME)
    except docker.errors.NotFound:
        print(f"Netwerk '{NETWORK_NAME}' wordt aangemaakt...")
        client.networks.create(NETWORK_NAME, driver="bridge")

@click.group()
def cli():
    """Beheer de Elasticsearch container."""
    pass

@cli.command()
@click.option('--image', default=DEFAULT_IMAGE, help="De te gebruiken Docker image.")
def start(image):
    """Start de Elasticsearch container."""
    ensure_network()
    try:
        container = client.containers.get(CONTAINER_NAME)
        if container.status != "running":
            print(f"Container '{CONTAINER_NAME}' wordt gestart...")
            container.start()
        else:
            print(f"Container '{CONTAINER_NAME}' draait al.")
    except docker.errors.NotFound:
        print(f"Container '{CONTAINER_NAME}' wordt aangemaakt en gestart...")
        environment = [
            "discovery.type=single-node",
            "xpack.security.enabled=false",
            "ES_JAVA_OPTS=-Xms2g -Xmx2g"
        ]
        client.containers.run(
            image=image, name=CONTAINER_NAME, network=NETWORK_NAME,
            ports={"9200/tcp": ("127.0.0.1", 9200)},
            environment=environment,
            detach=True
        )
    print(f"Container '{CONTAINER_NAME}' is gestart op netwerk '{NETWORK_NAME}'.")

@cli.command()
def stop():
    """Stop de Elasticsearch container."""
    try:
        container = client.containers.get(CONTAINER_NAME)
        print("Container wordt gestopt...")
        container.stop()
        print("Container gestopt.")
    except docker.errors.NotFound:
        print("Container niet gevonden.")

@cli.command()
def destroy():
    """Stop en verwijder de Elasticsearch container."""
    try:
        container = client.containers.get(CONTAINER_NAME)
        print("Container wordt gestopt en verwijderd...")
        container.remove(force=True)
        print("Container verwijderd.")
    except docker.errors.NotFound:
        print("Container niet gevonden.")

if __name__ == '__main__':
    cli()