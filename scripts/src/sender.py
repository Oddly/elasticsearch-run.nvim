# /// script
# requires-python = ">=3.8"
# dependencies = ["requests", "click", "python-dotenv"]
# ///
import click
import json
import logging
import sys
import requests
import os
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

LOGSTASH_INPUT_URL = f"http://localhost:{os.getenv('LOGSTASH_PORT')}"
logging.basicConfig(level=logging.INFO, format="%(asctime)s - SENDER - %(levelname)s - %(message)s", stream=sys.stderr)

@click.command()
def send_data():
    """Leest data van stdin en stuurt het naar Logstash."""
    try:
        input_docs = [json.loads(line) for line in sys.stdin if line.strip()]
    except json.JSONDecodeError as e:
        logging.error(f"Fout bij het parsen van JSON van stdin: {e}")
        sys.exit(1)
    if not input_docs: return
    
    headers = {"Content-Type": "application/x-ndjson"}
    ndjson_payload = "\n".join(json.dumps(d) for d in input_docs)
    try:
        logging.info(f"Versturen van {len(input_docs)} documenten naar Logstash...")
        requests.post(LOGSTASH_INPUT_URL, data=ndjson_payload, headers=headers, timeout=20).raise_for_status()
        logging.info("Payload succesvol afgeleverd.")
    except requests.exceptions.RequestException as e:
        logging.error(f"Kon geen verbinding maken met Logstash: {e}")
        sys.exit(1)

if __name__ == "__main__":
    send_data()