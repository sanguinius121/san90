#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="$PROJECT_DIR/.run"
cd "$PROJECT_DIR"
mkdir -p "$RUNTIME_DIR"

usage() {
  printf '%s\n' \
    "Usage:" \
    "  $0 start backend [san90|simulator]" \
    "  $0 stop backend" \
    "  $0 start frontend" \
    "  $0 stop frontend" \
    "  $0 status"
}

process_start_ticks() {
  local stat remainder
  IFS= read -r stat < "/proc/$1/stat" 2>/dev/null || return 1
  remainder="${stat##*) }"
  awk '{print $20}' <<< "$remainder"
}

managed_pid() {
  local service="$1" pid_file="$RUNTIME_DIR/$1.pid" pid saved_ticks current_ticks
  [[ -f "$pid_file" ]] || return 1
  read -r pid saved_ticks < "$pid_file" || return 1
  [[ "$pid" =~ ^[0-9]+$ && "$saved_ticks" =~ ^[0-9]+$ ]] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  current_ticks="$(process_start_ticks "$pid")"
  [[ -n "$current_ticks" && "$current_ticks" == "$saved_ticks" ]] || return 1
  printf '%s\n' "$pid"
}

port_is_open() {
  python3 - "$1" <<'PY'
import socket
import sys

with socket.socket() as sock:
    sock.settimeout(0.2)
    raise SystemExit(0 if sock.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0 else 1)
PY
}

wait_for_port() {
  local port="$1"
  for _ in {1..50}; do
    port_is_open "$port" && return 0
    sleep 0.1
  done
  return 1
}

reset_san90_for_handoff() {
  [[ "${SAN90_USB_HANDOFF_RESET:-1}" != "0" ]] || return 0
  "$PROJECT_DIR/scripts/reset-san90-usb.sh"
}

resolve_node_path() {
  local candidate version major minor user_data_dir
  user_data_dir="$(getent passwd "$(id -u)" | cut -d: -f6)"
  for candidate in \
    "${NODE_BIN_DIR:-}/node" \
    "${NVM_BIN:-}/node" \
    "$(command -v node 2>/dev/null || true)" \
    "$user_data_dir"/.local/nodejs/node-v*/bin/node \
    "$user_data_dir"/.nvm/versions/node/*/bin/node \
    "$user_data_dir"/.volta/bin/node \
    "/tmp/node-v22.17.0-linux-x64/bin/node"; do
    [[ -x "$candidate" ]] || continue
    version="$($candidate -p 'process.versions.node' 2>/dev/null || true)"
    major="${version%%.*}"
    minor="${version#*.}"; minor="${minor%%.*}"
    if [[ "$major" =~ ^[0-9]+$ ]] && (( major > 20 || (major == 20 && minor >= 19) )); then
      dirname "$candidate"
      return 0
    fi
  done
  printf '%s\n' "Frontend requires Node.js 20.19 or newer. Activate a current Node version or set NODE_BIN_DIR." >&2
  return 1
}

start_service() {
  local service="$1" source="${2:-}" pid log port node_path
  case "$service" in
    backend) port=8000 ;;
    frontend) port=5173 ;;
    *) usage >&2; return 2 ;;
  esac
  if pid="$(managed_pid "$service")"; then
    if port_is_open "$port"; then
      printf '%s is already running (PID %s).\n' "$service" "$pid"
      return 0
    fi
    printf '%s PID %s is alive but port %s is closed; completing stale shutdown.\n' "$service" "$pid" "$port" >&2
    stop_service "$service"
  fi
  rm -f "$RUNTIME_DIR/$service.pid"

  case "$service" in
    backend)
      source="${source:-san90}"
      [[ "$source" == "san90" || "$source" == "simulator" ]] || {
        printf 'Unknown analyzer source: %s\n' "$source" >&2
        return 2
      }
      if port_is_open "$port"; then
        printf 'Port %s is already in use by a process not managed here.\n' "$port" >&2
        return 1
      fi
      if [[ "$source" == "san90" ]]; then
        reset_san90_for_handoff
      fi
      log="$RUNTIME_DIR/backend.log"
      setsid env \
        ANALYZER_SOURCE="$source" \
        SAN90_STATUS_HZ="${SAN90_STATUS_HZ:-2}" \
        SAN90_RF_SWITCH_ENABLED="${SAN90_RF_SWITCH_ENABLED:-true}" \
        python3 -m uvicorn backend.main:app --host 0.0.0.0 --port "$port" \
        >"$log" 2>&1 < /dev/null &
      ;;
    frontend)
      if port_is_open "$port"; then
        printf 'Port %s is already in use by a process not managed here. The existing frontend may still be running.\n' "$port" >&2
        return 1
      fi
      node_path="$(resolve_node_path)"
      log="$RUNTIME_DIR/frontend.log"
      setsid env PATH="$node_path:$PATH" npm run dev -- --host 0.0.0.0 --port "$port" \
        >"$log" 2>&1 < /dev/null &
      ;;
  esac

  pid=$!
  printf '%s %s\n' "$pid" "$(process_start_ticks "$pid")" > "$RUNTIME_DIR/$service.pid"
  if [[ "$service" == "backend" ]]; then
    printf '%s\n' "$source" > "$RUNTIME_DIR/backend.source"
  fi
  if ! wait_for_port "$port"; then
    printf '%s failed to start; inspect %s\n' "$service" "$log" >&2
    tail -n 30 "$log" >&2 || true
    stop_service "$service" >/dev/null 2>&1 || true
    return 1
  fi
  printf '%s started (PID %s, port %s). Log: %s\n' "$service" "$pid" "$port" "$log"
}

stop_service() {
  local service="$1" pid pgid managed_source=""
  if ! pid="$(managed_pid "$service")"; then
    rm -f "$RUNTIME_DIR/$service.pid"
    [[ "$service" != "backend" ]] || rm -f "$RUNTIME_DIR/backend.source"
    printf '%s is not running under the project service manager.\n' "$service"
    return 0
  fi
  if [[ "$service" == "backend" && -f "$RUNTIME_DIR/backend.source" ]]; then
    IFS= read -r managed_source < "$RUNTIME_DIR/backend.source"
  fi
  pgid="$(ps -o pgid= -p "$pid" | tr -d ' ')"
  [[ "$pgid" =~ ^[0-9]+$ ]] || {
    printf 'Could not resolve the process group for %s PID %s.\n' "$service" "$pid" >&2
    return 1
  }
  kill -TERM -- "-$pgid"
  for _ in {1..30}; do
    kill -0 "$pid" 2>/dev/null || break
    sleep 0.1
  done
  if kill -0 "$pid" 2>/dev/null; then
    printf '%s is still finishing shutdown; sending an interrupt.\n' "$service" >&2
    kill -INT -- "-$pgid"
    for _ in {1..70}; do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.1
    done
  fi
  if kill -0 "$pid" 2>/dev/null; then
    printf '%s did not stop after TERM and INT; leaving it running for inspection.\n' "$service" >&2
    return 1
  fi
  rm -f "$RUNTIME_DIR/$service.pid"
  rm -f "$RUNTIME_DIR/$service.source"
  if [[ "$service" == "backend" && "$managed_source" == "san90" ]]; then
    reset_san90_for_handoff
  fi
  printf '%s stopped.\n' "$service"
}

show_status() {
  local service pid port
  for service in backend frontend; do
    port=8000; [[ "$service" == "frontend" ]] && port=5173
    if pid="$(managed_pid "$service")"; then
      printf '%-8s managed/running PID=%s port=%s\n' "$service" "$pid" "$port"
    elif port_is_open "$port"; then
      printf '%-8s unmanaged process is listening on port %s\n' "$service" "$port"
    else
      printf '%-8s stopped\n' "$service"
    fi
  done
}

action="${1:-}"
case "$action" in
  start)
    [[ $# -ge 2 ]] || { usage >&2; exit 2; }
    start_service "$2" "${3:-}"
    ;;
  stop)
    [[ $# -eq 2 ]] || { usage >&2; exit 2; }
    stop_service "$2"
    ;;
  status)
    [[ $# -eq 1 ]] || { usage >&2; exit 2; }
    show_status
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
