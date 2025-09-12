#!/bin/bash
# A robust script to run a Logstash -> Elasticsearch pipeline simulation.

set -e

# --- Argument Parsing ---
VERBOSE=false
QUIET=false
for arg in "$@"; do
  case $arg in
    -v|--verbose)
      VERBOSE=true
      shift
      ;;
    -q|--quiet)
      QUIET=true
      shift
      ;;
  esac
done

# --- Logging Functie ---
log() {
    if [[ "$VERBOSE" == "true" ]]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S.%N')] - BASH - $@" >&2
    fi
}

# --- Script Start ---
log "Simulation started (Verbose: ${VERBOSE}, Quiet: ${QUIET})."
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)
LOGSTASH_PROCESSOR_SCRIPT="$SCRIPT_DIR/logstash_processor.py"

if ! nc -z localhost 8080 >/dev/null 2>&1; then echo "ERROR: Logstash on port 8080 is not reachable." >&2; exit 1; fi
if ! curl --silent --fail --output /dev/null "http://localhost:9200"; then echo "ERROR: Elasticsearch on port 9200 is not reachable." >&2; exit 1; fi
log "Containers are ready."

payload=$(cat)
if ! echo "$payload" | jq -e . > /dev/null 2>&1; then log "ERROR: Invalid JSON received from stdin."; exit 1; fi
pipeline_def=$(echo "$payload" | jq -c '.pipeline')
docs=$(echo "$payload" | jq -c '.docs[]._source')
if [ -z "$docs" ]; then log "ERROR: No docs found in payload."; exit 1; fi

# --- Stap 1: Logstash Processing ---
doc_count=$(echo "$docs" | wc -l | tr -d ' ')
log "Starting Logstash processing for ${doc_count} documents..."
logstash_results="$(echo "$docs" | uv run "$LOGSTASH_PROCESSOR_SCRIPT")"
log "Logstash processing complete."

if [ -z "$logstash_results" ]; then log "ERROR: Logstash processor returned no results."; exit 1; fi

log "Preparing final payload for Elasticsearch..."
docs_array=$(echo "$logstash_results" | jq -s 'map(if . == null then { "_source": { "error": "document_dropped_or_timed_out" } } else {_source: .} end)')
final_payload=$(jq -n --argjson p "$pipeline_def" --argjson d "$docs_array" '{ "pipeline": $p, "docs": $d }')
log "Payload preparation complete."

# --- Stap 3: Elasticsearch Simulation ---
log "Running final Elasticsearch pipeline simulation..."
temp_file=$(mktemp)
echo "$final_payload" > "$temp_file"
response=$(curl -s -X POST "http://localhost:9200/_ingest/pipeline/_simulate" -H "Content-Type: application/json" -d "@$temp_file")
rm "$temp_file"
log "Elasticsearch simulation complete."

# --- Resultaat Verwerken ---
if echo "$response" | jq -e '.error' > /dev/null; then
    echo "--- ELASTICSEARCH SIMULATION ERROR ---" >&2
    echo "$response"
    exit 1
else
    if [[ "$QUIET" == "false" ]]; then
        echo "$response" | jq '.docs[].doc._source'
    fi
    exit 0
fi

log "Simulation finished."
