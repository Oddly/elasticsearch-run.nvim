#!/bin/bash
# Real integration test that actually spins up containers and tests functionality
set -e

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)
cd "$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Load environment
source .env

# Test state
TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0
CLEANUP_NEEDED=()

log_test() {
    echo -e "${BLUE}[TEST]${NC} $1"
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
}

log_pass() {
    echo -e "${GREEN}[PASS]${NC} $1"
    PASSED_TESTS=$((PASSED_TESTS + 1))
}

log_fail() {
    echo -e "${RED}[FAIL]${NC} $1"
    if [[ -n "$2" ]]; then
        echo -e "${RED}Error details:${NC} $2"
    fi
    FAILED_TESTS=$((FAILED_TESTS + 1))
}

log_info() {
    echo -e "${YELLOW}[INFO]${NC} $1"
}

cleanup() {
    log_info "Cleaning up test environment..."
    
    # Stop and remove all test containers
    for container in "$LOGSTASH_CONTAINER_NAME" "$LISTENER_CONTAINER_NAME" "es-run-elasticsearch"; do
        if docker ps -a --format "table {{.Names}}" | grep -q "^${container}$"; then
            log_info "Removing container: $container"
            docker rm -f "$container" 2>/dev/null || true
        fi
    done
    
    # Remove test network
    if docker network ls --format "table {{.Name}}" | grep -q "^${NETWORK_NAME}$"; then
        log_info "Removing network: $NETWORK_NAME"
        docker network rm "$NETWORK_NAME" 2>/dev/null || true
    fi
    
    # Remove listener image if it exists
    if docker images --format "table {{.Repository}}:{{.Tag}}" | grep -q "^${LISTENER_IMAGE_NAME}:latest$"; then
        log_info "Removing image: $LISTENER_IMAGE_NAME"
        docker rmi "$LISTENER_IMAGE_NAME" 2>/dev/null || true
    fi
    
    log_info "Cleanup complete"
}

wait_for_service() {
    local host="$1"
    local port="$2"
    local service_name="$3"
    local timeout="${4:-30}"
    
    log_info "Waiting for $service_name on $host:$port (timeout: ${timeout}s)"
    
    for i in $(seq 1 $timeout); do
        if nc -z "$host" "$port" 2>/dev/null; then
            log_info "$service_name is ready"
            return 0
        fi
        sleep 1
    done
    
    # Show container status and logs on timeout
    local container_status=""
    local container_logs=""
    if docker ps -a --format "table {{.Names}} {{.Status}}" | grep -q "$service_name"; then
        container_status=$(docker ps -a --format "table {{.Names}} {{.Status}}" | grep "$service_name")
        container_logs=$(docker logs --tail 10 "$service_name" 2>&1 || echo "No logs available")
    fi
    log_fail "$service_name failed to start within ${timeout}s" "Container status: $container_status | Last logs: $container_logs"
    return 1
}

test_container_lifecycle() {
    local service_name="$1"
    local management_script="$2"
    local container_name="$3"
    
    log_test "Container lifecycle: $service_name"
    
    # Test start from clean state
    local start_output
    if ! start_output=$(uv run "$management_script" start 2>&1); then
        log_fail "$service_name - Failed to start" "$start_output"
        return 1
    fi
    
    # Verify container is running
    if ! docker ps --format "table {{.Names}}" | grep -q "^${container_name}$"; then
        log_fail "$service_name - Container not found after start"
        return 1
    fi
    
    # Test idempotent start (should not fail)
    if ! uv run "$management_script" start >/dev/null 2>&1; then
        log_fail "$service_name - Second start should be idempotent"
        return 1
    fi
    
    # Test stop
    if ! uv run "$management_script" stop >/dev/null 2>&1; then
        log_fail "$service_name - Failed to stop"
        return 1
    fi
    
    # Verify container is stopped
    if docker ps --format "table {{.Names}}" | grep -q "^${container_name}$"; then
        log_fail "$service_name - Container still running after stop"
        return 1
    fi
    
    # Test destroy
    if ! uv run "$management_script" destroy >/dev/null 2>&1; then
        log_fail "$service_name - Failed to destroy"
        return 1
    fi
    
    log_pass "Container lifecycle: $service_name"
    return 0
}

test_sender_without_logstash() {
    log_test "Sender without Logstash (should fail gracefully)"
    
    # Ensure Logstash is not running
    docker rm -f "$LOGSTASH_CONTAINER_NAME" 2>/dev/null || true
    
    # Test sender behavior
    if echo '{"test":"data"}' | timeout 10 uv run src/sender.py 2>/dev/null; then
        log_fail "Sender without Logstash - Should have failed"
        return 1
    else
        log_pass "Sender without Logstash - Failed gracefully as expected"
        return 0
    fi
}

test_logstash_pipeline_validation() {
    log_test "Logstash pipeline validation"
    
    # Test with valid filter file
    if ! uv run docker/logstash/manage.py start --pipeline examples/oots/filter.conf >/dev/null 2>&1; then
        log_fail "Logstash pipeline validation - Valid filter rejected"
        return 1
    fi
    
    # Test pipeline switching (should fail with running container)
    if uv run docker/logstash/manage.py start --pipeline docker/logstash/templates/empty_filter.conf >/dev/null 2>&1; then
        log_fail "Logstash pipeline validation - Should prevent pipeline switching"
        return 1
    fi
    
    # Cleanup for next test
    uv run docker/logstash/manage.py destroy >/dev/null 2>&1 || true
    
    log_pass "Logstash pipeline validation"
    return 0
}

test_end_to_end_pipeline() {
    log_test "End-to-end pipeline integration"
    
    # Start all services with error capture
    log_info "Starting Elasticsearch..."
    local es_output
    if ! es_output=$(uv run src/manage_es.py start 2>&1); then
        log_fail "Failed to start Elasticsearch" "$es_output"
        return 1
    fi
    wait_for_service localhost 9200 "Elasticsearch" 60 || return 1
    
    log_info "Building and starting listener..."
    local listener_build_output
    if ! listener_build_output=$(uv run docker/listener/manage.py build 2>&1); then
        log_fail "Failed to build listener" "$listener_build_output"
        return 1
    fi
    local listener_start_output  
    if ! listener_start_output=$(uv run docker/listener/manage.py start 2>&1); then
        log_fail "Failed to start listener" "$listener_start_output"
        return 1
    fi
    wait_for_service localhost "$LISTENER_PORT" "Listener" 30 || return 1
    
    log_info "Starting Logstash with OOTS filter..."
    local logstash_output
    if ! logstash_output=$(uv run docker/logstash/manage.py start --pipeline examples/oots/filter.conf 2>&1); then
        log_fail "Failed to start Logstash" "$logstash_output"
        return 1
    fi
    wait_for_service localhost "$LOGSTASH_PORT" "Logstash" 60 || return 1
    
    # Test data flow
    log_info "Testing data flow through pipeline..."
    
    # Send test data and capture output
    temp_output=$(mktemp)
    docker logs -f "$LISTENER_CONTAINER_NAME" > "$temp_output" 2>&1 &
    log_pid=$!
    
    sleep 2  # Give logs time to start
    
    # Send data
    if ! head -1 examples/oots/test_data.ndjson | uv run src/sender.py >/dev/null 2>&1; then
        kill $log_pid 2>/dev/null || true
        rm -f "$temp_output"
        log_fail "End-to-end pipeline - Failed to send data"
        return 1
    fi
    
    sleep 5  # Wait for processing
    kill $log_pid 2>/dev/null || true
    
    # Check if data was processed
    if grep -q "parsedQueryRequest\|parsedQueryResponse" "$temp_output"; then
        log_pass "End-to-end pipeline integration"
        rm -f "$temp_output"
        return 0
    else
        log_fail "End-to-end pipeline - No processed data found in output"
        cat "$temp_output"
        rm -f "$temp_output"
        return 1
    fi
}

test_network_connectivity() {
    log_test "Container network connectivity"
    
    # Start listener and logstash
    uv run docker/listener/manage.py start >/dev/null 2>&1
    uv run docker/logstash/manage.py start --pipeline examples/oots/filter.conf >/dev/null 2>&1
    
    # Wait for services
    wait_for_service localhost "$LISTENER_PORT" "Listener" 30 || return 1
    wait_for_service localhost "$LOGSTASH_PORT" "Logstash" 60 || return 1
    
    # Test network connectivity from Logstash to Listener using health endpoint
    local curl_output
    if curl_output=$(docker exec "$LOGSTASH_CONTAINER_NAME" curl -s -f "http://$LISTENER_CONTAINER_NAME:$LISTENER_PORT/health" 2>&1); then
        if echo "$curl_output" | grep -q "healthy"; then
            log_pass "Container network connectivity"
            return 0
        else
            log_fail "Container network connectivity - Unexpected response" "Response: $curl_output"
            return 1
        fi
    else
        log_fail "Container network connectivity - Logstash cannot reach Listener" "Curl output: $curl_output"
        return 1
    fi
}

test_keep_alive_option() {
    log_test "Keep-alive option functionality"
    
    # Run with keep-alive option
    local test_output
    if ! test_output=$(echo '{"pipeline":{"processors":[{"set":{"field":"test","value":true}}]},"docs":[{"_source":{"msg":"test"}}]}' | timeout 60 uv run elasticsearch_runner.py --keep-alive --quiet 2>&1); then
        log_fail "Keep-alive option - Failed to run with --keep-alive" "$test_output"
        return 1
    fi
    
    # Verify containers are still running
    if ! docker ps --format "table {{.Names}}" | grep -q "es-run-elasticsearch" || 
       ! docker ps --format "table {{.Names}}" | grep -q "es-run-listener" ||
       ! docker ps --format "table {{.Names}}" | grep -q "es-run-logstash"; then
        log_fail "Keep-alive option - Containers should still be running"
        return 1
    fi
    
    # Manual cleanup for this test
    uv run docker/logstash/manage.py destroy >/dev/null 2>&1 || true
    uv run docker/listener/manage.py destroy >/dev/null 2>&1 || true  
    uv run src/manage_es.py destroy >/dev/null 2>&1 || true
    
    log_pass "Keep-alive option functionality"
    return 0
}

test_error_handling() {
    log_test "Error handling and recovery"
    
    # Test invalid JSON
    if echo "invalid json" | uv run src/sender.py >/dev/null 2>&1; then
        log_fail "Error handling - Should reject invalid JSON"
        return 1
    fi
    
    # Test missing pipeline file
    if uv run docker/logstash/manage.py start --pipeline /nonexistent/pipeline.conf >/dev/null 2>&1; then
        log_fail "Error handling - Should reject missing pipeline"
        return 1
    fi
    
    log_pass "Error handling and recovery"
    return 0
}

# Set up cleanup trap
trap cleanup EXIT INT TERM

echo "================================================================="
echo "REAL INTEGRATION TEST SUITE"
echo "================================================================="
echo

log_info "Starting comprehensive integration tests..."
log_info "This will create and destroy actual Docker containers"

# Ensure clean start
cleanup

echo -e "\n${BLUE}=== ERROR HANDLING TESTS ===${NC}"
test_sender_without_logstash
test_error_handling

echo -e "\n${BLUE}=== KEEP-ALIVE OPTION TESTS ===${NC}"
test_keep_alive_option

echo -e "\n${BLUE}=== CONTAINER LIFECYCLE TESTS ===${NC}"
test_container_lifecycle "Elasticsearch" "src/manage_es.py" "es-run-elasticsearch"
test_container_lifecycle "Listener" "docker/listener/manage.py" "$LISTENER_CONTAINER_NAME"

# Logstash lifecycle test needs special handling - requires pipeline parameter
log_test "Container lifecycle: Logstash (with pipeline requirement)"
log_info "Testing Logstash container lifecycle with pipeline requirement..."
local logstash_start_output
if ! logstash_start_output=$(uv run docker/logstash/manage.py start --pipeline examples/oots/filter.conf 2>&1); then
    log_fail "Logstash - Failed to start with filter" "$logstash_start_output"
else
    if docker ps --format "table {{.Names}}" | grep -q "^$LOGSTASH_CONTAINER_NAME$"; then
        # Test stop
        if uv run docker/logstash/manage.py stop >/dev/null 2>&1; then
            # Test destroy
            if uv run docker/logstash/manage.py destroy >/dev/null 2>&1; then
                log_pass "Container lifecycle: Logstash (with pipeline requirement)"
            else
                log_fail "Logstash - Failed to destroy"
            fi
        else
            log_fail "Logstash - Failed to stop"
        fi
    else
        log_fail "Logstash - Container not found after start"
    fi
fi

echo -e "\n${BLUE}=== LOGSTASH SPECIFIC TESTS ===${NC}"
test_logstash_pipeline_validation

echo -e "\n${BLUE}=== NETWORK CONNECTIVITY TESTS ===${NC}"
test_network_connectivity

echo -e "\n${BLUE}=== END-TO-END INTEGRATION TESTS ===${NC}"
test_end_to_end_pipeline

# Final summary
echo
echo "================================================================="
echo "INTEGRATION TEST SUMMARY"
echo "================================================================="
echo -e "Total integration tests: ${BLUE}$TOTAL_TESTS${NC}"
echo -e "Tests passed: ${GREEN}$PASSED_TESTS${NC}"
echo -e "Tests failed: ${RED}$FAILED_TESTS${NC}"

if [[ $FAILED_TESTS -eq 0 ]]; then
    echo -e "\n${GREEN}ALL INTEGRATION TESTS PASSED! 🎉${NC}"
    echo "The system is fully functional and ready for production use."
    exit 0
else
    echo -e "\n${RED}SOME INTEGRATION TESTS FAILED! ❌${NC}"
    echo "Please review the failed tests above."
    exit 1
fi