# /// script
# requires-python = ">=3.8"
# dependencies = [
#   "flask",
#   "requests",
#   "click",
# ]
# ///

import click
import json
import logging
import sys
import threading
import time
import uuid
from queue import Queue

import requests
from flask import Flask, request

# --- Configuratie ---
LOGSTASH_INPUT_URL = "http://localhost:8080"
LISTENER_HOST = "0.0.0.0"
LISTENER_PORT = 5001
# Timeout in seconden. Hoe lang wachten we maximaal op alle resultaten?
PROCESSING_TIMEOUT = 2

# --- Logging Setup ---
# Verstuur alle logs naar stderr, zodat stdout schoon blijft voor de resultaten.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - PY - %(levelname)s - %(message)s",
    stream=sys.stderr,
)

# --- Gedeelde Data en Listener ---
# Een thread-safe queue om resultaten van de listener naar de main thread te sturen.
results_queue = Queue()
app = Flask(__name__)
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

def secho(text, file=None, nl=None, err=None, color=None, **styles):
    pass

def echo(text, file=None, nl=None, err=None, color=None, **styles):
    pass

click.echo = echo
click.secho = secho

@app.route('/', methods=['POST'])
def receive_event_from_logstash():
    """Ontvangt een verwerkt evenement van Logstash en plaatst het in de queue."""
    try:
        event_data = request.get_json()
        if event_data:
            # We verwachten dat het correlatie_id in het event zit.
            results_queue.put(event_data)
        return {"status": "ok"}, 200
    except Exception as e:
        logging.error(f"Fout bij ontvangen van event: {e}")
        return {"status": "error"}, 500

def run_listener_server():
    """Start de Flask-server."""
    try:
        app.run(host=LISTENER_HOST, port=LISTENER_PORT, debug=False)
    except OSError as e:
        logging.error(f"Kon de listener-server niet starten op poort {LISTENER_PORT}: {e}")

# --- Hoofdlogica ---
def main():
    """
    Leest docs van stdin, stuurt ze naar Logstash, verzamelt de resultaten
    en print ze in de juiste volgorde naar stdout.
    """
    # 1. Start de listener in een achtergrondthread.
    listener_thread = threading.Thread(target=run_listener_server, daemon=True)
    listener_thread.start()
    time.sleep(0.1) # Geef de server even de tijd om te starten.

    # 2. Lees alle documenten van stdin en voeg een uniek correlatie-ID toe.
    try:
        input_docs = [json.loads(line) for line in sys.stdin if line.strip()]
    except json.JSONDecodeError as e:
        logging.error(f"Fout bij het parsen van JSON van stdin: {e}")
        sys.exit(1)
        
    if not input_docs:
        logging.info("Geen documenten ontvangen van stdin. Stoppen.")
        return

    docs_to_send = []
    correlation_map = {}
    for i, doc in enumerate(input_docs):
        correlation_id = str(uuid.uuid4())
        # We slaan de originele index op, zodat we de volgorde kunnen herstellen.
        correlation_map[correlation_id] = i
        # Voeg het ID toe aan het document dat we versturen.
        doc_with_id = doc.copy()
        doc_with_id["correlation_id"] = correlation_id
        docs_to_send.append(doc_with_id)

    # Maak een resultatenlijst met placeholders.
    final_results = [None] * len(input_docs)

    # 3. Verstuur alle documenten in één batch.
    headers = {"Content-Type": "application/x-ndjson"}
    ndjson_payload = "\n".join(json.dumps(d) for d in docs_to_send)
    
    try:
        logging.info(f"Versturen van {len(docs_to_send)} documenten naar Logstash...")
        response = requests.post(LOGSTASH_INPUT_URL, data=ndjson_payload, headers=headers, timeout=5)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logging.error(f"Kon geen verbinding maken met Logstash: {e}")
        sys.exit(1)

    # 4. Wacht op resultaten en verwerk ze.
    start_time = time.time()
    received_count = 0
    # Het aantal verwachte resultaten is niet per se gelijk aan het aantal verstuurde
    # documenten, omdat Logstash events kan droppen.
    
    while time.time() - start_time < PROCESSING_TIMEOUT:
        if received_count == len(docs_to_send):
            break # We kunnen niet meer events ontvangen dan we hebben verstuurd
        
        try:
            result = results_queue.get(timeout=1)
            corr_id = result.pop("correlation_id", None)
            
            if corr_id and corr_id in correlation_map:
                original_index = correlation_map[corr_id]
                final_results[original_index] = result
                received_count += 1
            else:
                logging.warning(f"Resultaat ontvangen zonder (bekend) correlatie-ID: {result}")
        except Exception:
            # Queue is leeg, wacht verder.
            pass

    logging.info(f"{received_count} van de {len(input_docs)} documenten zijn verwerkt en terug ontvangen.")

    # 5. Print de uiteindelijke resultaten naar stdout.
    for result in final_results:
        if result is None:
            # Als een document niet is teruggekomen (gedropt of timeout), print 'null'.
            print("null")
        else:
            print(json.dumps(result))

if __name__ == "__main__":
    main()
