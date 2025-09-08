#!/bin/bash
# A robust script to run a Logstash -> Elasticsearch pipeline simulation.
set -e

# Send all diagnostic 'echo' output to stderr.
log() { echo "$@" >&2; }

log "Starting simulation..."

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)
LOGSTASH_PROCESSOR_SCRIPT="$SCRIPT_DIR/logstash_processor.py"
ES_SIMULATOR_SCRIPT="$SCRIPT_DIR/es_pipeline_simulator.sh"
# No longer need the container managers here, assume they are running for speed.

# --- Fast container check ---
if ! curl --silent --fail --output /dev/null "http://localhost:9200" || ! nc -z localhost 8080; then
    log "ERROR: Elasticsearch or Logstash is not running or not reachable."
    log "Hint: Run the container start commands from Neovim first."
    exit 1
fi
log "Containers are ready."

# --- EXECUTION ---
payload=$(cat)

if ! echo "$payload" | jq -e > /dev/null 2>&1; then
    log "ERROR: Invalid JSON received from Neovim."
    exit 1
fi

# Extract the pipeline definition for the final ES simulation step
pipeline_def=$(echo "$payload" | jq -c '.pipeline')
if [ -z "$pipeline_def" ] || [ "$pipeline_def" == "null" ]; then
    log "ERROR: No pipeline definition found in payload."
    exit 1
fi

# Extract docs to be sent to Logstash
docs=$(echo "$payload" | jq -c '.docs[]._source')
if [ -z "$docs" ]; then
    log "ERROR: No docs found in payload."
    exit 1
fi

log "Processing $(echo "$docs" | wc -l) documents through Logstash..."

logstash_results="$(echo "$docs" | uv run "$LOGSTASH_PROCESSOR_SCRIPT")"

if [ -z "$logstash_results" ]; then
    log "ERROR: Logstash processor returned no results."
    exit 1
fi

log "Logstash processing complete. Re-creating docs for Elasticsearch..."

# --- REBUILD THE ES PAYLOAD ---
# Re-assemble the Logstash results into the final array of "_source" objects
# for the Elasticsearch simulate API. jq handles the 'null' values correctly.
echo "$logstash_results"
final_docs=$(echo "$logstash_results" | jq -s 'map(if . == null then null else { "_source": . } end)')
echo "final_docs: $final_docs"

# Create the final payload for the ES simulator script
final_payload=$(jq -n --argjson p "$pipeline_def" --argjson d "$final_docs" \
  '{ "pipeline": $p, "docs": $d }')
#echo "final_payload: $final_payload"

log "Running final Elasticsearch pipeline simulation..."

# --- RUN ES SIMULATION ---
# This script is assumed to call the _simulate API and return the final,
# formatted JSON array.
bash "$ES_SIMULATOR_SCRIPT" <<< "$final_payload"

log "Simulation complete."
