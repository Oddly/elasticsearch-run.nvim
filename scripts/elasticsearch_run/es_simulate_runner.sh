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
LOGSTASH_PROCESSOR_SCRIPT="$SCRIPT_DIR/http_batch_processor.sh"
ES_SIMULATOR_SCRIPT="$SCRIPT_DIR/es_pipeline_simulator.sh"


# --- CONTAINER MANAGEMENT ---
echo "Checking containers are ready..." >&2

# Check Elasticsearch
if ! curl --silent --output /dev/null "http://localhost:9200"; then
    echo "Starting Elasticsearch container..." >&2
    uv run "$ELASTICSEARCH_MANAGER_SCRIPT" start
    
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
fi
echo "Elasticsearch is ready." >&2

# Check Logstash
if ! docker ps --filter name=logstash-dev --filter status=running | grep -q logstash-dev; then
    echo "Starting Logstash container..." >&2
    uv run "$LOGSTASH_MANAGER_SCRIPT" start
    
    TRIES=0
    MAX_TRIES=30
    until docker ps --filter name=logstash-dev --filter status=running | grep -q logstash-dev; do
        TRIES=$((TRIES + 1))
        if [ $TRIES -ge $MAX_TRIES ]; then
            echo "ERROR: Logstash did not become available after 150 seconds." >&2
            exit 1
        fi
        sleep 5
    done
fi
echo "Logstash is ready. Reading payload from stdin..." >&2

# --- EXECUTION ---
# Read the entire stdin stream into a variable.
payload=$(cat)

if echo "$payload" | jq empty > /dev/null 2>&1; then
    echo "Input JSON is valid" >&2
else
    echo "ERROR: JSON validation failed, check your payload in Neovim." >&2
    exit 1
fi

if [ -z "$payload" ]; then
    echo "ERROR: Received empty payload from Neovim." >&2
    exit 1
fi

# Extract docs from payload for Logstash processing (compact JSON)
docs=$(echo "$payload" | jq -c '.docs[]._source')
if [ -z "$docs" ]; then
    echo "ERROR: No docs found in payload. Expected format: {\"pipeline\": {...}, \"docs\": [{\"_source\": {...}}, ...]}" >&2
    exit 1
fi

echo "Processing $(echo "$docs" | wc -l) documents through Logstash..." >&2

# Create a temporary file to store the pipeline definition
PIPELINE_FILE=$(mktemp)
echo "$payload" > "$PIPELINE_FILE"

# Count documents
doc_count=$(echo "$docs" | wc -l)
echo "Processing $doc_count documents (optimized batch processing)..." >&2

# Process ALL documents through Logstash in a single batch
echo "Sending batch to Logstash..." >&2
logstash_results=$(echo "$docs" | bash "$LOGSTASH_PROCESSOR_SCRIPT" 2>/dev/null)

if [ $? -ne 0 ] || [ -z "$logstash_results" ]; then
    echo "ERROR: Logstash batch processing failed" >&2
    exit 1
fi

# Count logstash results to ensure we got all documents back
logstash_count=$(echo "$logstash_results" | wc -l)
echo "Logstash processed $logstash_count documents, now running ES pipeline simulation..." >&2

# Process each Logstash result through ES pipeline simulation
processed_docs=()
current_doc=0

while IFS= read -r logstash_result; do
    if [ -n "$logstash_result" ]; then
        current_doc=$((current_doc + 1))
        
        # Process through ES pipeline simulation
        es_result=$(echo "$logstash_result" | bash "$ES_SIMULATOR_SCRIPT" "$PIPELINE_FILE" 2>/dev/null)
        
        if [ $? -ne 0 ] || [ -z "$es_result" ]; then
            echo "ERROR: ES simulation failed for document $current_doc" >&2
            echo "Logstash output: $logstash_result" >&2
            continue
        fi
        
        processed_docs+=("$es_result")
    fi
done <<< "$logstash_results"

# Clean up
rm -f "$PIPELINE_FILE"

# Output results
if [ ${#processed_docs[@]} -eq 0 ]; then
    echo "ERROR: No documents were successfully processed" >&2
    exit 1
fi

# Format as JSON array
echo "["
for i in "${!processed_docs[@]}"; do
    echo -n "${processed_docs[i]}"
    if [ $i -lt $((${#processed_docs[@]} - 1)) ]; then
        echo ","
    fi
done
echo "]"
