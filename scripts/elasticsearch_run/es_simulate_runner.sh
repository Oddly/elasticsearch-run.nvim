#!/bin/bash
#
# uv run:
#   -r docker
#
# A robust script to run an Elasticsearch pipeline simulation using uv.

# Exit immediately if any command fails.
set -e

# Send all diagnostic 'echo' output to stderr.
echo "Starting simulation script via uv..." >&2

# Get the script's own directory.
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)
ELASTICSEARCH_MANAGER_SCRIPT="$SCRIPT_DIR/manage_es_container.py"
LOGSTASH_MANAGER_SCRIPT="$SCRIPT_DIR/manage_logstash_container.py"


# --- CONTAINER MANAGEMENT ---
echo "Ensuring containers are ready..." >&2
uv run "$ELASTICSEARCH_MANAGER_SCRIPT"
#uv run "$LOGSTASH_MANAGER_SCRIPT" start

# --- WAIT FOR ELASTICSEARCH ---
TRIES=0
MAX_TRIES=30
echo "Waiting for Elasticsearch to respond..." >&2
until curl --silent --output /dev/null "http://localhost:9200"; do
    TRIES=$((TRIES + 1))
    if [ $TRIES -ge $MAX_TRIES ]; then
        echo "ERROR: Elasticsearch did not become available after 150 seconds." >&2
        exit 1
    fi
    sleep 5
done
echo "Elasticsearch is ready. Reading payload from stdin..." >&2

# --- EXECUTION ---
# Read the entire stdin stream into a variable.
payload=$(cat)

if echo "$payload" | jq empty > /dev/null 2>&1; then
    echo "Valid JSON"
else
    echo "ERROR: JSON validation failed, check your payload in Neovim."
    exit 1
fi

if [ -z "$payload" ]; then
    echo "ERROR: Received empty payload from Neovim." >&2
    exit 1
fi

# Simulate the pipeline.
response=$(curl -s -X POST "http://localhost:9200/_ingest/pipeline/_simulate" \
    -H "Content-Type: application/json" \
    -d "$payload")

# --- OUTPUT ---
# Check for an error from Elasticsearch and handle output correctly.
if echo "$response" | jq -e '.error' > /dev/null; then
    echo "--- ELASTICSEARCH SIMULATION ERROR ---" >&2
    echo "$response"
    exit 1
else
    echo "$response" | jq '.docs[].doc._source'
    exit 0
fi
