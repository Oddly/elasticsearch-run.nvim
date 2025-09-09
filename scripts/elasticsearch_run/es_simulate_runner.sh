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

#echo "docs:"
#echo "$docs"

log "Processing $(echo "$docs" | wc -l) documents through Logstash..."

logstash_results="$(echo "$docs" | uv run "$LOGSTASH_PROCESSOR_SCRIPT")"

#echo "logstash_results:"
#echo "$logstash_results"
if [ -z "$logstash_results" ]; then
    log "ERROR: Logstash processor returned no results."
    exit 1
fi

log "Logstash processing complete. Re-creating docs for Elasticsearch..."

# Convert NDJSON to array, preserving nulls and wrapping non-nulls in _source
docs_array=$(echo "$logstash_results" | jq -s 'map(if . == null then { "_source": { null } } else {_source: .} end)')

# Create the final payload for the ES simulator script  
final_payload=$(jq -n --argjson p "$pipeline_def" --argjson d "$docs_array" \
  '{ "pipeline": $p, "docs": $d }')

#echo $final_payload | jq .

log "Running final Elasticsearch pipeline simulation..."

# Write payload to temporary file
temp_file=$(mktemp)
echo "$final_payload" > "$temp_file"

# Use curl with file reference
response=$(curl -s -X POST "http://localhost:9200/_ingest/pipeline/_simulate" \
    -H "Content-Type: application/json" \
    -d "@$temp_file")

# Clean up temporary file
rm "$temp_file"

#response=$(curl -s -X POST "http://localhost:9200/_ingest/pipeline/_simulate" \
#    -H "Content-Type: application/json" \
#    -d "$final_payload")

if echo "$response" | jq -e '.error' > /dev/null; then
    echo "--- ELASTICSEARCH SIMULATION ERROR ---" >&2
    echo "$response"
    exit 1
else
    echo "$response" | jq '.docs[].doc._source'
    exit 0
fi 
log "Simulation complete."
