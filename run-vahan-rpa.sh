#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API_DIR="$ROOT_DIR/apps/api-server"
WEB_DIR="$ROOT_DIR/apps/web-ui"
LOG_DIR="${TMPDIR:-/tmp}"
API_LOG="$LOG_DIR/vahan-rpa-api.log"
WEB_LOG="$LOG_DIR/vahan-rpa-web-ui.log"

fail() {
  printf 'Lỗi: %s\n' "$*" >&2
  exit 1
}

for tool in lsof ps curl npm; do
  command -v "$tool" >/dev/null 2>&1 || fail "Không tìm thấy lệnh cần thiết: $tool"
done

[[ -x "$API_DIR/.venv/bin/python" ]] || fail "Thiếu Python môi trường ảo: $API_DIR/.venv/bin/python"
[[ -x "$WEB_DIR/node_modules/.bin/vite" ]] || fail "Thiếu Vite dependencies; hãy chạy npm install trong apps/web-ui."

process_cwd() {
  lsof -a -p "$1" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -n 1
}

listener_pids() {
  lsof -nP -t -iTCP:"$1" -sTCP:LISTEN 2>/dev/null | sort -u || true
}

stop_old_service() {
  local port="$1"
  local app_dir="$2"
  local service="$3"
  local listeners pid cwd proc_command parent_pid parent_cwd parent_command remaining
  local -a stop_pids=()

  listeners="$(listener_pids "$port")"
  if [[ -z "$listeners" ]]; then
    printf '%s chưa chạy trên cổng %s.\n' "$service" "$port"
    return 0
  fi

  for pid in $listeners; do
    cwd="$(process_cwd "$pid")"
    proc_command="$(ps -p "$pid" -o command= 2>/dev/null || true)"
    [[ "$cwd" == "$app_dir" ]] || fail "Cổng $port đang được PID $pid dùng ngoài thư mục dự án; không dừng tiến trình lạ."

    if [[ "$service" == "BE" ]]; then
      if [[ "$proc_command" != *"uvicorn app.main:application"* && "$proc_command" != *"spawn_main"* ]]; then
        fail "PID $pid đang dùng cổng $port nhưng không nhận diện được là backend VAHAN."
      fi
    else
      [[ "$proc_command" == *"$WEB_DIR/node_modules/.bin/vite"* ]] || fail "PID $pid đang dùng cổng $port nhưng không nhận diện được là Web UI VAHAN."
    fi

    stop_pids+=("$pid")

    if [[ "$service" == "FE" ]]; then
      parent_pid="$(ps -p "$pid" -o ppid= 2>/dev/null | tr -d ' ')"
      if [[ "$parent_pid" =~ ^[0-9]+$ ]]; then
        parent_cwd="$(process_cwd "$parent_pid")"
        parent_command="$(ps -p "$parent_pid" -o command= 2>/dev/null || true)"
        if [[ "$parent_cwd" == "$WEB_DIR" && "$parent_command" == *"npm run dev"* ]]; then
          stop_pids+=("$parent_pid")
        fi
      fi
    fi
  done

  printf 'Đang dừng %s cũ trên cổng %s...\n' "$service" "$port"
  for pid in "${stop_pids[@]}"; do
    kill -TERM "$pid" 2>/dev/null || true
  done

  for ((attempt = 0; attempt < 10; attempt++)); do
    [[ -z "$(listener_pids "$port")" ]] && return 0
    sleep 1
  done

  remaining="$(listener_pids "$port")"
  for pid in $remaining; do
    cwd="$(process_cwd "$pid")"
    [[ "$cwd" == "$app_dir" ]] || fail "Cổng $port chuyển sang tiến trình lạ; không buộc dừng PID $pid."
    kill -KILL "$pid" 2>/dev/null || true
  done

  sleep 1
  [[ -z "$(listener_pids "$port")" ]] || fail "Không thể giải phóng cổng $port."
}

wait_for_api() {
  for ((attempt = 0; attempt < 30; attempt++)); do
    if curl -fsS -m 2 http://127.0.0.1:8000/api/health 2>/dev/null | grep -Eq '"status"[[:space:]]*:[[:space:]]*"ok"'; then
      printf 'BE sẵn sàng: http://127.0.0.1:8000 (health OK)\n'
      return 0
    fi
    sleep 1
  done
  printf 'BE chưa sẵn sàng. Log gần nhất:\n' >&2
  tail -n 60 "$API_LOG" >&2 || true
  return 1
}

wait_for_web() {
  for ((attempt = 0; attempt < 30; attempt++)); do
    if curl -fsS -m 2 -o /dev/null http://127.0.0.1:5173 2>/dev/null; then
      printf 'FE sẵn sàng: http://127.0.0.1:5173\n'
      return 0
    fi
    sleep 1
  done
  printf 'FE chưa sẵn sàng. Log gần nhất:\n' >&2
  tail -n 60 "$WEB_LOG" >&2 || true
  return 1
}

stop_old_service 8000 "$API_DIR" BE
stop_old_service 5173 "$WEB_DIR" FE

printf 'Đang chạy backend mới...\n'
(
  cd "$API_DIR"
  nohup ./.venv/bin/python -m uvicorn app.main:application --host 127.0.0.1 --port 8000 --reload >"$API_LOG" 2>&1 &
)

printf 'Đang chạy Web UI mới...\n'
(
  cd "$WEB_DIR"
  nohup npm run dev >"$WEB_LOG" 2>&1 &
)

wait_for_api
wait_for_web
printf 'Hoàn tất. Log: %s và %s\n' "$API_LOG" "$WEB_LOG"
