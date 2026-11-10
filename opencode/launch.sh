#!/bin/bash
set -euo pipefail

url="http://127.0.0.1:${AI_CONTAINER_OPENCODE_PORT:?}"
command="${AI_CONTAINER_OPENCODE_COMMAND:-opencode}"
mkdir -p "${XDG_STATE_HOME:?}"
log="$XDG_STATE_HOME/opencode-server.log"
if [ "${AI_CONTAINER_OPENCODE_ATTACH:-false}" != true ]; then
    "$command" serve --hostname 0.0.0.0 --port "$AI_CONTAINER_OPENCODE_PORT" >"$log" 2>&1 &
    server_pid=$!
    trap 'kill "$server_pid" 2>/dev/null || true; wait "$server_pid" 2>/dev/null || true' EXIT
fi
trap 'exit 130' INT
trap 'exit 143' TERM

ready=false
deadline=$((SECONDS + 30))
for ((attempt = 0; attempt < 100; attempt++)); do
    if ((SECONDS >= deadline)); then break; fi
    if [ -n "${server_pid:-}" ] && ! kill -0 "$server_pid" 2>/dev/null; then
        cat "$log" >&2
        exit 1
    fi
    if timeout 2 "$command" --server "$url" api get /api/info >/dev/null 2>&1; then
        ready=true
        break
    fi
    sleep 0.1
done
if [ "$ready" = false ]; then
    printf 'OpenCode server did not become ready. See %s\n' "$log" >&2
    exit 1
fi
"$command" --server "$url" "$@"
