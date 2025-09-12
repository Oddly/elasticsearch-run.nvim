#!/bin/bash
# Main entry point for Neovim: Logstash processing + Elasticsearch simulation
set -e

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)
cd "$SCRIPT_DIR"

# Load environment
source .env

# --- Argument Parsing ---
VERBOSE=false
QUIET=false
DEBUG=false
KEEP_ALIVE=false
PIPELINE_FILTER=""  # Default empty filter (will use default)

while [[ $# -gt 0 ]]; do
  case $1 in
    -v|--verbose)
      VERBOSE=true
      shift
      ;;
    -q|--quiet)
      QUIET=true
      shift
      ;;
    -d|--debug)
      DEBUG=true
      VERBOSE=true
      shift
      ;;
    -k|--keep-alive)
      KEEP_ALIVE=true
      shift
      ;;
    --pipeline)
      PIPELINE_FILTER="$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

# --- Logging Functions ---
log() {
    if [[ "$VERBOSE" == "true" ]]; then
        echo "[$(date '+%H:%M:%S.%3N')] - BASH - $@" >&2
    fi
}

debug() {
    if [[ "$DEBUG" == "true" ]]; then
        echo "[$(date '+%H:%M:%S.%3N')] - DEBUG - $@" >&2
    fi
}

debug_json() {
    if [[ "$DEBUG" == "true" ]]; then
        echo "[$(date '+%H:%M:%S.%3N')] - DEBUG JSON - $1:" >&2
        echo "$2" | jq . >&2 || echo "$2" >&2
        echo "--- END DEBUG JSON ---" >&2
    fi
}

# Cleanup function
cleanup() {
    if [[ "$KEEP_ALIVE" == "true" ]]; then
        log "Containers left running (--keep-alive option used)"
        log "To manually stop: uv run docker/logstash/manage.py destroy && uv run docker/listener/manage.py destroy && uv run src/manage_es.py destroy"
    else
        log "Shutting down containers..."
        uv run docker/logstash/manage.py destroy >/dev/null 2>&1 || true
        uv run docker/listener/manage.py destroy >/dev/null 2>&1 || true
        uv run src/manage_es.py destroy >/dev/null 2>&1 || true
        log "Cleanup complete."
    fi
}

# Set cleanup trap
trap cleanup EXIT INT TERM

# --- Input Processing ---
log "Reading JSON payload from stdin..."
payload=$(cat)
debug "Raw payload received"
debug_json "INPUT" "$payload"

if ! echo "$payload" | jq -e . > /dev/null 2>&1; then 
    echo "ERROR: Invalid JSON received from stdin." >&2
    exit 1
fi

# Extract ES ingest pipeline and docs
pipeline_def=$(echo "$payload" | jq -c '.pipeline // empty')
docs=$(echo "$payload" | jq -c '.docs[]._source // empty')

debug_json "EXTRACTED PIPELINE" "$pipeline_def"
debug_json "EXTRACTED DOCS" "$docs"

if [ -z "$pipeline_def" ] || [ "$pipeline_def" == "null" ] || [ "$pipeline_def" == '{}' ]; then 
    echo "ERROR: No Elasticsearch ingest pipeline found in payload." >&2
    exit 1
fi

if [ -z "$docs" ]; then 
    echo "ERROR: No docs found in payload." >&2
    exit 1
fi

doc_count=$(echo "$docs" | wc -l)
log "Found ${doc_count} documents to process"

# --- Setup Phase ---
log "Setting up containers in parallel..."

# Determine which filter to use
if [[ -z "$PIPELINE_FILTER" ]]; then
    FILTER_FILE="docker/logstash/templates/empty_filter.conf"
    PIPELINE_ID="default"
    debug "Using default empty filter"
else
    if [[ -f "$PIPELINE_FILTER" ]]; then
        FILTER_FILE="$PIPELINE_FILTER"
        PIPELINE_ID=$(basename "$PIPELINE_FILTER" .conf)
        debug "Using custom filter: $PIPELINE_FILTER (ID: $PIPELINE_ID)"
    else
        echo "ERROR: Pipeline filter not found: $PIPELINE_FILTER" >&2
        exit 1
    fi
fi

# Build dynamic pipeline from template and filter
TEMP_PIPELINE=$(mktemp)

# Build pipeline by concatenating sections directly
{
    echo "input {"
    echo "  http {"
    echo "    port => 8080"
    echo "    codec => \"json_lines\""
    echo "  }"
    echo "}"
    echo ""
    cat "$FILTER_FILE"
    echo ""
    echo "output {"
    echo "  http {"
    echo "    url => \"http://es-run-listener:8081/\""
    echo "    http_method => \"post\""
    echo "    format => \"json_batch\""
    echo "    keepalive => false"
    echo "  }"
    echo "}"
} > "$TEMP_PIPELINE"
debug "Built dynamic pipeline at: $TEMP_PIPELINE"

# Check if Logstash needs restart for different pipeline
CURRENT_LOGSTASH_PIPELINE=""
if docker ps --format "table {{.Names}}" | grep -q "^es-run-logstash$"; then
    CURRENT_LOGSTASH_PIPELINE=$(docker inspect es-run-logstash --format '{{index .Config.Labels "com.elasticsearch-run.pipeline-config"}}' 2>/dev/null || echo "")
    if [[ "$CURRENT_LOGSTASH_PIPELINE" != "$PIPELINE_ID" ]]; then
        log "Restarting Logstash with new pipeline ($PIPELINE_ID)"
        uv run docker/logstash/manage.py destroy >/dev/null 2>&1 || true
    fi
fi

# Start all containers in parallel
log "Starting Elasticsearch, Listener, and Logstash in parallel..."

# Capture background job PIDs and exit codes
es_log=$(mktemp)
listener_log=$(mktemp)
logstash_log=$(mktemp)

uv run src/manage_es.py start > "$es_log" 2>&1 &
es_pid=$!
uv run docker/listener/manage.py start > "$listener_log" 2>&1 &
listener_pid=$!
PIPELINE_ID="$PIPELINE_ID" uv run docker/logstash/manage.py start --pipeline "$TEMP_PIPELINE" > "$logstash_log" 2>&1 &
logstash_pid=$!

# Wait for each job and check exit codes
wait $es_pid
es_exit=$?
wait $listener_pid  
listener_exit=$?
wait $logstash_pid
logstash_exit=$?

# Check for failures
if [[ $es_exit -ne 0 ]]; then
    echo "ERROR: Elasticsearch startup failed:" >&2
    cat "$es_log" >&2
    exit 1
fi

if [[ $listener_exit -ne 0 ]]; then
    echo "ERROR: Listener startup failed:" >&2
    cat "$listener_log" >&2
    exit 1
fi

if [[ $logstash_exit -ne 0 ]]; then
    echo "ERROR: Logstash startup failed:" >&2
    cat "$logstash_log" >&2
    exit 1
fi

# Show output in debug mode
if [[ "$DEBUG" == "true" ]]; then
    echo "=== ES STARTUP ===" >&2
    cat "$es_log" >&2
    echo "=== LISTENER STARTUP ===" >&2
    cat "$listener_log" >&2
    echo "=== LOGSTASH STARTUP ===" >&2
    cat "$logstash_log" >&2
fi

# Cleanup temp files
rm -f "$es_log" "$listener_log" "$logstash_log"

log "All container start commands completed successfully, checking readiness..."

# Wait for Elasticsearch
log "Waiting for Elasticsearch..."
for i in {1..60}; do
    if curl -s http://localhost:9200 >/dev/null 2>&1; then 
        log "Elasticsearch ready after ${i} seconds"
        break
    fi
    sleep 1
done
if ! curl -s http://localhost:9200 >/dev/null 2>&1; then
    echo "ERROR: Elasticsearch failed to start within 60 seconds." >&2
    exit 1
fi

# Wait for Listener
log "Waiting for Listener..."
for i in {1..30}; do
    if nc -z localhost "$LISTENER_PORT" 2>/dev/null; then
        log "Listener ready after ${i} seconds"
        break
    fi
    sleep 1
done
if ! nc -z localhost "$LISTENER_PORT" 2>/dev/null; then
    echo "ERROR: Listener failed to start within 30 seconds." >&2
    exit 1
fi

# Wait for Logstash
log "Waiting for Logstash..."
for i in {1..90}; do
    if nc -z localhost "$LOGSTASH_PORT" 2>/dev/null; then
        log "Logstash ready after ${i} seconds"
        break
    fi
    sleep 1
done
if ! nc -z localhost "$LOGSTASH_PORT" 2>/dev/null; then
    echo "ERROR: Logstash failed to start within 90 seconds." >&2
    exit 1
fi

log "All containers are ready!"

# --- Logstash Processing Phase ---
log "Processing ${doc_count} documents through Logstash..."

# Start capturing listener output
temp_output=$(mktemp)
docker logs -f "$LISTENER_CONTAINER_NAME" > "$temp_output" 2>&1 &
log_pid=$!

sleep 2  # Give logs time to start

debug "Sending docs to Logstash via sender..."
if [[ "$DEBUG" == "true" ]]; then
    echo "$docs" | uv run src/sender.py
else
    echo "$docs" | uv run src/sender.py >/dev/null 2>&1
fi

# Wait for processing and capture results
log "Waiting for Logstash processing to complete..."
sleep 5
kill $log_pid 2>/dev/null || true

# Extract processed results
logstash_results=""
if [[ -s "$temp_output" ]]; then
    # Filter out log messages, keep only JSON results
    logstash_results=$(grep -v "LISTENER -" "$temp_output" | grep '{' || echo "")
    debug_json "LOGSTASH RESULTS" "$logstash_results"
else
    debug "No output captured from listener"
fi

if [ -z "$logstash_results" ]; then 
    echo "ERROR: Logstash processor returned no results." >&2
    if [[ "$DEBUG" == "true" ]]; then
        echo "Raw listener output:" >&2
        cat "$temp_output" >&2
    fi
    exit 1
fi

# --- Elasticsearch Simulation Phase ---
log "Preparing Elasticsearch simulation payload..."

# Convert logstash results to ES docs format
docs_array=$(echo "$logstash_results" | jq -s 'map(if . == null then { "_source": { "error": "document_dropped_or_timed_out" } } else {_source: .} end)')
debug_json "DOCS ARRAY FOR ES" "$docs_array"

# Create final payload for ES simulation
final_payload=$(jq -n --argjson p "$pipeline_def" --argjson d "$docs_array" '{ "pipeline": $p, "docs": $d }')
debug_json "FINAL ES PAYLOAD" "$final_payload"

log "Running Elasticsearch ingest pipeline simulation..."
temp_file=$(mktemp)
echo "$final_payload" > "$temp_file"

response=$(curl -s -X POST "http://localhost:9200/_ingest/pipeline/_simulate" -H "Content-Type: application/json" -d "@$temp_file")
rm "$temp_file"

debug_json "ES SIMULATION RESPONSE" "$response"

# --- Output Results ---
if echo "$response" | jq -e '.error' > /dev/null 2>&1; then
    echo "ERROR: Elasticsearch simulation failed:" >&2
    echo "$response" | jq . >&2
    exit 1
else
    if [[ "$QUIET" == "false" ]]; then
        echo "$response" | jq '.docs[].doc._source'
    fi
    log "Processing complete - success!"
    exit 0
fi

# Cleanup temp files
rm -f "$temp_output" "$TEMP_PIPELINE" 2>/dev/null || true
