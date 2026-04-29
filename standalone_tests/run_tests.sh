#!/usr/bin/env sh
# SPDX-License-Identifier: Unlicense
# Orchestrates MCP Stdio Bridge standalone tests.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

TEST="local-mock"
SSH_HOST="user@remote-host"
SSH_ARGS=""
REMOTE_CONFIG="/path/to/remote/config.yaml"
SSE_URL="http://localhost:8000"
API_KEY=""
HELP=0
TEST_EXPLICIT=0

usage_full() {
    cat <<EOF

MCP Stdio Bridge Test Orchestrator
-----------------------------------
Usage:
  ./run_tests.sh [-t <scenario>] [options]
  ./run_tests.sh -t <scenario> -h   (show options for that scenario)

  Default: -t local-mock

Local Scenarios:
  local-mock         Run stdio wrapper test locally against mock WP-CLI
  start-bridge-sse   Start a local SSE bridge (use with test-sse in another terminal)
  test-sse           Run SSE client test against a running local bridge
                     Options: -u <url>  -k <key>
  ssh                Run stdio test against a real remote host via SSH
                     Options: -H <user@host>  -c <path>  -s <args>

Docker Scenarios:
  docker-local       Run local-mock test inside Docker
  docker-sse         Run SSE pipeline test inside Docker
  docker-ssh-direct  Run direct SSH scenario inside Docker
  docker-ssh-proxy   Run SSE-to-SSH proxy scenario inside Docker

EOF
}

usage_scenario() {
    case "$TEST" in
        local-mock)
            printf '\nlocal-mock\n'
            printf '  Run stdio wrapper test locally against mock WP-CLI.\n'
            printf '  No additional options.\n\n'
            ;;
        start-bridge-sse)
            printf '\nstart-bridge-sse\n'
            printf '  Generate config and start a local SSE bridge on port 8000.\n'
            printf '  Run test-sse in a separate terminal to send requests.\n'
            printf '  No additional options.\n\n'
            ;;
        test-sse)
            printf '\ntest-sse\n'
            printf '  Run SSE client test against a running local bridge.\n\n'
            printf '  -u <url>   Base URL of the bridge  (default: http://localhost:8000)\n'
            printf '  -k <key>   API key if authentication is configured  (default: none)\n\n'
            ;;
        ssh)
            printf '\nssh\n'
            printf '  Run stdio test against a real remote host via SSH.\n\n'
            printf '  -H <user@host>   Remote host to connect to  (default: user@remote-host)\n'
            printf '  -c <path>        Path to config.yaml on the remote host\n'
            printf '  -s <args>        Extra arguments to pass to ssh  (optional)\n\n'
            ;;
        docker-*)
            printf '\n%s\n' "$TEST"
            printf '  No additional options.\n\n'
            ;;
        *)
            printf '\nUnknown scenario: %s\n\n' "$TEST"
            ;;
    esac
}

while getopts "t:H:s:c:u:k:h" opt; do
    case "$opt" in
        t) TEST="$OPTARG";  TEST_EXPLICIT=1 ;;
        H) SSH_HOST="$OPTARG" ;;
        s) SSH_ARGS="$OPTARG" ;;
        c) REMOTE_CONFIG="$OPTARG" ;;
        u) SSE_URL="$OPTARG" ;;
        k) API_KEY="$OPTARG" ;;
        h) HELP=1 ;;
        *) usage_full; exit 1 ;;
    esac
done

if [ "$HELP" = "1" ]; then
    if [ "$TEST_EXPLICIT" = "1" ]; then
        usage_scenario
    else
        usage_full
    fi
    exit 0
fi

export PYTHONPATH="$PROJECT_ROOT/src"
cd "$SCRIPT_DIR"

case "$TEST" in
    docker-*) IS_DOCKER=1 ;;
    *)        IS_DOCKER=0 ;;
esac

YAML="docker-compose.test.yml"
PROJECT="mcp-test"

docker_compose() {
    docker compose \
        -p "$PROJECT" -f "$YAML" \
        --progress plain --ansi never \
        "$@"
}

docker_cleanup() {
    docker compose -p "$PROJECT" -f "$YAML" down -v --timeout 0 --remove-orphans 2>/dev/null || true
    docker rm -f \
        mcp-ssh-server mcp-ssh-direct mcp-ssh-proxy-bridge mcp-ssh-proxy-client \
        mcp-local-mock mcp-bridge-server mcp-bridge-client 2>/dev/null || true
}

if [ "$IS_DOCKER" = "1" ]; then
    export COMPOSE_NO_TTY=1
    export COMPOSE_DOCKER_CLI_HINTS=false
    export DOCKER_SCAN_SUGGEST=false
    docker_cleanup
fi

run_test() {
    case "$TEST" in
        local-mock)
            python test_local_mock.py
            ;;

        start-bridge-sse)
            python generate_local_config.py
            python -m mcp_stdio_bridge.main \
                --config config.generated.yaml --transport sse --port 8000 --verbose
            ;;

        test-sse)
            if [ -n "$API_KEY" ]; then
                python test_mcp_local_bridge.py --url "$SSE_URL" --api-key "$API_KEY"
            else
                python test_mcp_local_bridge.py --url "$SSE_URL"
            fi
            ;;

        ssh)
            if [ -n "$SSH_ARGS" ]; then
                python test_mcp_ssh_stdio.py \
                    --host "$SSH_HOST" --config "$REMOTE_CONFIG" --ssh-args "$SSH_ARGS"
            else
                python test_mcp_ssh_stdio.py \
                    --host "$SSH_HOST" --config "$REMOTE_CONFIG"
            fi
            ;;

        docker-local)
            echo "[*] Running Docker Local Mock..."
            docker_compose up --build --abort-on-container-exit \
                --exit-code-from local-mock local-mock
            ;;

        docker-sse)
            echo "[*] Running Docker SSE Pipeline..."
            docker_compose up --build -d bridge
            docker_compose up --build --abort-on-container-exit \
                --exit-code-from client bridge client
            ;;

        docker-ssh-direct)
            echo "[*] Running Docker SSH Direct..."
            docker_compose up --build -d ssh-server
            docker_compose up --build --abort-on-container-exit \
                --exit-code-from ssh-direct-test ssh-server ssh-direct-test
            ;;

        docker-ssh-proxy)
            echo "[*] Running Docker SSH Proxy (Forcing Clean Build)..."
            docker_compose build --no-cache
            docker_compose up --force-recreate --abort-on-container-exit \
                --exit-code-from ssh-proxy-client \
                ssh-server ssh-proxy-bridge ssh-proxy-client
            ;;

        *)
            printf 'Unknown test scenario: %s\n' "$TEST" >&2
            usage_full >&2
            exit 1
            ;;
    esac
}

if [ "$IS_DOCKER" = "1" ]; then
    trap 'echo "[*] Cleaning up Docker resources..."; docker_cleanup' EXIT
fi

run_test
