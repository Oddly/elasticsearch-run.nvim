# /// script
# requires-python = ">=3.8"
# dependencies = ["flask", "requests", "click", "waitress", "psutil"]
# ///

import click
import json
import logging
import sys
import threading
import time
import uuid
import os
import socket
from queue import Queue

import requests
from flask import Flask, request
import waitress

# --- Configuratie ---
LOGSTASH_INPUT_URL = "http://localhost:8080"
LISTENER_HOST = "0.0.0.0"
LISTENER_PORT = 8081
PROCESSING_TIMEOUT = 15 # Een iets ruimere timeout

# --- Gedeelde Data en Listener ---
results_queue = Queue()
app = Flask(__name__)
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

# Onderdruk eventuele output van Click zelf
def secho(text, file=None, nl=None, err=None, color=None, **styles): pass
def echo(text, file=None, nl=None, err=None, color=None, **styles): pass
click.echo = echo
click.secho = secho

@app.route('/', methods=['POST'])
def receive_event_from_logstash():
    """Ontvangt een verwerkt evenement van Logstash en plaatst het in de queue."""
    logger = logging.getLogger('main_processor')
    logger.debug("Request ontvangen van Logstash.")
    try:
        event_batch = request.get_json()
        if isinstance(event_batch, list):
            for event_data in event_batch:
                if event_data:
                    results_queue.put(event_data)
        elif event_batch:
            results_queue.put(event_batch)
        return {"status": "ok"}, 200
    except Exception as e:
        logger.error(f"Fout bij ontvangen van event batch: {e}")
        return {"status": "error"}, 500

def run_listener_server():
    """Start de stabiele Waitress server."""
    logger = logging.getLogger('main_processor')
    try:
        waitress.serve(app, host=LISTENER_HOST, port=LISTENER_PORT, threads=8)
    except Exception as e:
        logger.critical(f"LISTENER THREAD GECRASHT MET FOUT: {e}", exc_info=True)

@click.command()
@click.option('--verbose', '-v', is_flag=True, help="Schakel gedetailleerde DEBUG logging in.")
def main(verbose):
    """
    Start de listener op de achtergrond, leest docs van stdin, stuurt ze naar Logstash,
    verzamelt de resultaten en print ze in de juiste volgorde naar stdout.
    """
    # --- Logging Setup ---
    log_level = logging.DEBUG if verbose else logging.INFO
    log_format = "%(asctime)s.%(msecs)03d - PY - %(levelname)s - %(message)s"
    logger = logging.getLogger('main_processor')
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        formatter = logging.Formatter(log_format, datefmt='%Y-%m-%d %H:%M:%S')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.setLevel(log_level)
    
    # 1. Start de listener in een DAEMON thread.
    # Een daemon thread stopt automatisch als het hoofdscript klaar is.
    listener_thread = threading.Thread(target=run_listener_server, daemon=True)
    listener_thread.start()
    
    # 2. Robuuste health check die wacht tot de poort echt open is.
    logger.info(f"Wachten tot listener op poort {LISTENER_PORT} beschikbaar is...")
    start_wait = time.time()
    server_ready = False
    check_host = "127.0.0.1" if LISTENER_HOST == "0.0.0.0" else LISTENER_HOST
    while time.time() - start_wait < 5: # Wacht maximaal 5 seconden
        try:
            with socket.create_connection((check_host, LISTENER_PORT), timeout=0.1):
                server_ready = True
                break
        except (socket.timeout, ConnectionRefusedError):
            time.sleep(0.1) # Wacht kort en probeer opnieuw

    if not server_ready:
        logger.error("Listener-server startte niet binnen de tijdslimiet. Stoppen.")
        sys.exit(1)
    logger.info("Listener is bevestigd als 'running'.")
    
    # 3. Lees en prepareer de documenten van stdin.
    try:
        input_docs = [json.loads(line) for line in sys.stdin if line.strip()]
    except json.JSONDecodeError as e:
        logger.error(f"Fout bij het parsen van JSON van stdin: {e}"); sys.exit(1)
    if not input_docs:
        logger.info("Geen documenten ontvangen van stdin. Stoppen."); return

    docs_to_send, correlation_map = [], {}
    for i, doc in enumerate(input_docs):
        correlation_id = str(uuid.uuid4())
        correlation_map[correlation_id] = i
        doc_with_id = doc.copy()
        doc_with_id["correlation_id"] = correlation_id
        docs_to_send.append(doc_with_id)
    final_results = [None] * len(input_docs)
    
    # 4. Verstuur de batch naar Logstash.
    headers = {"Content-Type": "application/x-ndjson"}
    ndjson_payload = "\n".join(json.dumps(d) for d in docs_to_send)
    
    try:
        logger.info(f"Versturen van {len(docs_to_send)} documenten naar Logstash...")
        response = requests.post(LOGSTASH_INPUT_URL, data=ndjson_payload, headers=headers, timeout=20)
        response.raise_for_status()
        logger.info("Payload succesvol afgeleverd bij Logstash.")
    except requests.exceptions.RequestException as e:
        logger.error(f"Kon geen verbinding maken met Logstash: {e}"); sys.exit(1)

    # 5. Wacht op de resultaten.
    start_time = time.time()
    received_count = 0
    logger.info("Wachten op resultaten van Logstash...")
    
    while time.time() - start_time < PROCESSING_TIMEOUT:
        if received_count == len(docs_to_send):
            logger.info("Alle verwachte resultaten zijn binnen."); break
        try:
            result = results_queue.get(timeout=1)
            corr_id = result.pop("correlation_id", None)
            if corr_id and corr_id in correlation_map:
                final_results[correlation_map[corr_id]] = result
                received_count += 1
            else:
                logger.warning(f"Resultaat ontvangen zonder (bekend) correlatie-ID: {result}")
        except Exception:
            pass
            
    if received_count < len(input_docs):
         logger.warning(f"Processing timeout bereikt. {received_count}/{len(input_docs)} documenten ontvangen.")
    else:
        logger.info(f"Alle {received_count} documenten zijn verwerkt en terug ontvangen.")

    # 6. Print de resultaten.
    for result in final_results:
        print(json.dumps(result) if result is not None else "null")

if __name__ == "__main__":
    main()
