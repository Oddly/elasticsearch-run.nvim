# /// script
# requires-python = ">=3.8"
# dependencies = [
#   "flask",
#   "requests",
# ]
# ///

import json
import logging
import sys
import threading
import time

import requests
from flask import Flask, request

# --- Configuratie ---
# Pas deze waarden aan indien nodig.
LOGSTASH_INPUT_URL = "http://localhost:8080"
LISTENER_HOST = "0.0.0.0"  # Luister op alle netwerkinterfaces
LISTENER_PORT = 5001

# --- Logging Setup ---
# Configureer logging voor duidelijke en informatieve output.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(threadName)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)

# --- De Ontvanger (Flask Webserver) ---
# Deze server luistert naar de gebeurtenissen die door de Logstash output worden teruggestuurd.

app = Flask(__name__)

# Schakel de standaard Flask logging uit om dubbele logs te voorkomen.
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

@app.route('/', methods=['POST'])
def receive_event_from_logstash():
    """
    Dit eindpunt ontvangt de POST-verzoeken van de Logstash http output.
    """
    logging.info(f"Gebeurtenis ontvangen van Logstash op poort {LISTENER_PORT}!")
    try:
        # Haal de JSON-data uit het verzoek.
        event_data = request.get_json()
        if not event_data:
            logging.warning("Verzoek ontvangen, maar het bevatte geen JSON-data.")
            return {"status": "error", "message": "No JSON body received"}, 400

        # Log de ontvangen data op een mooie, leesbare manier.
        logging.info("Ontvangen data:\n" + json.dumps(event_data, indent=2))
        
        # Controleer of onze custom field aanwezig is.
        if event_data.get("processed_by_logstash"):
            logging.info("Verificatie geslaagd: Het veld 'processed_by_logstash' is aanwezig.")
        else:
            logging.warning("Verificatie mislukt: Het veld 'processed_by_logstash' ontbreekt.")

        return {"status": "ok"}, 200

    except Exception as e:
        logging.error(f"Fout bij het verwerken van inkomend verzoek: {e}")
        return {"status": "error", "message": "Internal server error"}, 500


def run_listener_server():
    """
    Start de Flask-server. Deze functie wordt in een aparte thread uitgevoerd.
    """
    logging.info(f"Start de listener-server op http://{LISTENER_HOST}:{LISTENER_PORT}")
    try:
        # We gebruiken debug=False omdat dit in een thread draait en we de auto-reloader niet willen.
        app.run(host=LISTENER_HOST, port=LISTENER_PORT, debug=False)
    except OSError as e:
        logging.error(f"Kon de listener-server niet starten op poort {LISTENER_PORT}: {e}")
        logging.error("Is de poort al in gebruik?")


# --- De Zender ---
# Deze functie stuurt gebeurtenissen naar de Logstash http input.

def send_events_to_logstash():
    """
    Creëert en verstuurt een reeks testgebeurtenissen naar Logstash.
    """
    logging.info(f"Beginnen met het versturen van gebeurtenissen naar Logstash op {LOGSTASH_INPUT_URL}")

    # Definieer de headers. Omdat we de `json_lines` codec gebruiken,
    # is `application/x-ndjson` de meest correcte Content-Type.
    headers = {
        "Content-Type": "application/x-ndjson"
    }

    # Een lijst van voorbeeldgebeurtenissen om te versturen.
    events = [
        {"id": 1, "message": "Dit is de eerste testgebeurtenis."},
        {"id": 2, "message": "Deze gebeurtenis wordt gedropt.", "status": "drop_me"},
        {"id": 3, "message": "De derde gebeurtenis zou moeten slagen."},
        {"id": 4, "message": "Nog een succesvolle gebeurtenis."}
    ]

    # Converteer de lijst van dicts naar een newline-delimited JSON string.
    ndjson_payload = "\n".join(json.dumps(e) for e in events)

    logging.info(f"Voorbereide payload die wordt verstuurd:\n---\n{ndjson_payload}\n---")

    try:
        response = requests.post(LOGSTASH_INPUT_URL, data=ndjson_payload, headers=headers)
        
        # Controleer de response van Logstash.
        response.raise_for_status()  # Genereert een error bij een slechte status code (4xx of 5xx)
        
        logging.info(f"Payload succesvol verstuurd naar Logstash. Status Code: {response.status_code}")
        logging.info("Logstash accepteerde de data. Controleer de output van de listener.")

    except requests.exceptions.RequestException as e:
        logging.error(f"Fout bij het versturen van data naar Logstash: {e}")
        logging.error("Controleer of Logstash draait en de http input correct is geconfigureerd op poort 8080.")


# --- Hoofdprogramma ---
# Start de listener en roept vervolgens de zender aan.

if __name__ == "__main__":
    # 1. Start de listener-server in een achtergrondthread.
    # We gebruiken `daemon=True` zodat de thread automatisch stopt als het hoofdscript klaar is.
    listener_thread = threading.Thread(
        target=run_listener_server, 
        name="ListenerThread", 
        daemon=True
    )
    listener_thread.start()

    # 2. Wacht even om de server de tijd te geven om op te starten.
    logging.info("Wachten voor 2 seconden om de listener-server op te starten...")
    time.sleep(2)

    # 3. Stuur de gebeurtenissen naar Logstash.
    send_events_to_logstash()
    
    # 4. Wacht nog even om Logstash de tijd te geven de gebeurtenissen te verwerken
    #    en terug te sturen naar onze listener.
    logging.info("Verzenden voltooid. Wachten voor 5 seconden op de respons van Logstash...")
    time.sleep(5)
    
    logging.info("Script voltooid.")
