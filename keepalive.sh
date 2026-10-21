#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
#  AI STV - keepalive: giữ bot chạy nền và tự chạy lại khi crash.
#
#  Cách dùng (trong thư mục repo, hoặc bất kỳ đâu):
#      bash keepalive.sh          # chạy nền, tách khỏi terminal
#      bash keepalive.sh --loop   # chạy ngay tại terminal (debug)
#      bash keepalive.sh --stop   # dừng
#      bash keepalive.sh --status # xem trạng thái
#
#  Lưu ý: script này chống CRASH và chống tắt terminal/SSH.
#  Nó KHÔNG chống được việc nền tảng (DataCamp/Colab) thu hồi máy —
#  lúc đó cần chạy lại lệnh, hoặc dùng host chạy 24/7 (VPS/Railway).
# ─────────────────────────────────────────────────────────────────────
set -uo pipefail

APP_DIR="${AISTV_DIR:-$HOME/AISTV}"
LOG_DIR="${AISTV_LOG_DIR:-$HOME/stv_agent/logs}"
LOG="$LOG_DIR/bot.log"
PID_FILE="$LOG_DIR/keepalive.pid"
RESTART_DELAY="${AISTV_RESTART_DELAY:-10}"

mkdir -p "$LOG_DIR" 2>/dev/null || true

running() {
  [[ -f "$PID_FILE" ]] || return 1
  local pid; pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

case "${1:-}" in
  --stop)
    if running; then
      pid="$(cat "$PID_FILE")"
      kill "$pid" 2>/dev/null || true
      # dừng cả cây tiến trình con (python bot + opencode)
      pkill -TERM -P "$pid" 2>/dev/null || true
      sleep 2
      kill -9 "$pid" 2>/dev/null || true
      rm -f "$PID_FILE"
      echo "Đã dừng keepalive (pid $pid)."
    else
      echo "Không có tiến trình nào đang chạy."
    fi
    exit 0
    ;;
  --status)
    if running; then
      echo "Đang chạy · pid $(cat "$PID_FILE") · log $LOG"
      tail -n 5 "$LOG" 2>/dev/null
    else
      echo "Không chạy."
    fi
    exit 0
    ;;
  --loop)
    ;;
  "")
    if running; then
      echo "Đã chạy sẵn · pid $(cat "$PID_FILE") · log $LOG"
      exit 0
    fi
    cd "$APP_DIR" 2>/dev/null || { echo "Không vào được $APP_DIR"; exit 1; }
    nohup setsid bash "$0" --loop >>"$LOG" 2>&1 &
    echo $! > "$PID_FILE"
    sleep 1
    echo "Đã chạy nền · pid $! · log: $LOG"
    echo "Xem: bash keepalive.sh --status · Dừng: bash keepalive.sh --stop"
    exit 0
    ;;
  *)
    echo "Dùng: bash keepalive.sh [--loop|--stop|--status]"
    exit 1
    ;;
esac

# ── Chế độ --loop: chạy run.sh, chết thì chạy lại ────────────────────
cd "$APP_DIR" 2>/dev/null || { echo "Không vào được $APP_DIR"; exit 1; }
trap 'echo "[keepalive] nhận tín hiệu dừng"; exit 0' INT TERM

n=0
while true; do
  n=$((n + 1))
  echo "[keepalive] $(date '+%F %T') lần chạy #$n"
  bash "$APP_DIR/run.sh"
  code=$?
  if [[ "$code" == "0" ]]; then
    echo "[keepalive] $(date '+%F %T') bot thoát bình thường — không chạy lại."
    rm -f "$PID_FILE"
    exit 0
  fi
  echo "[keepalive] $(date '+%F %T') bot thoát (code $code) — chạy lại sau ${RESTART_DELAY}s"
  sleep "$RESTART_DELAY"
done
