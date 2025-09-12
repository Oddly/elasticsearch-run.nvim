# /// script
# requires-python = ">=3.8"
# dependencies = ["flask", "waitress"]
# ///
import json
import logging
import os
from flask import Flask, request
import waitress

# --- Configuratie ---
LISTENER_HOST = "0.0.0.0"
LISTENER_PORT = int(os.getenv("LISTENER_PORT", 8081))

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - LISTENER - %(message)s")
logger = logging.getLogger(__name__)
logging.getLogger('waitress').setLevel(logging.ERROR)
logging.getLogger('werkzeug').setLevel(logging.ERROR)

# --- Flask App ---
app = Flask(__name__)

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for connectivity testing."""
    return {"status": "healthy"}, 200

@app.route('/', methods=['POST'])
def receive_event():
    """Ontvangt een batch en print deze naar stdout."""
    try:
        event_batch = request.get_json(silent=True)
        if not event_batch:
            logger.warning("Request ontvangen zonder valide JSON body.")
            return {"status": "bad request"}, 400
            
        events = event_batch if isinstance(event_batch, list) else [event_batch]
        for event in events:
            if event:
                print(json.dumps(event), flush=True)
        return {"status": "ok"}, 200
    except Exception as e:
        logger.error(f"Fout bij ontvangen van event batch: {e}")
        return {"status": "error"}, 500

if __name__ == "__main__":
    logger.info(f"Listener wordt gestart op http://{LISTENER_HOST}:{LISTENER_PORT}")
    waitress.serve(app, host=LISTENER_HOST, port=LISTENER_PORT, threads=8)