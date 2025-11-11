#!/usr/bin/env bash
set -u
# Updated run-dotty.sh — verbose startup with diagnostics, venv, deps, mqtt test, and exec.
# Replace REPO_URL / REPO_DIR / APP_ENTRY / PYTHON_BIN as needed.

REPO_URL="https://github.com/TheChaseFiore/Dotty.git"
REPO_DIR="/home/chase/Dotty"
APP_ENTRY="main.py"
PYTHON_BIN="/usr/bin/python3"

# runtime logfile
LOG_DIR="${REPO_DIR:-/tmp}/logs"
mkdir -p "$LOG_DIR"
LOGFILE="$LOG_DIR/dotty_startup_$(date +%Y%m%d-%H%M%S).log"

# tee all output to logfile (and console)
exec > >(tee -a "$LOGFILE") 2>&1

echo "=== Dotty updater ==="
echo "Logfile: $LOGFILE"
echo "Started: $(date -u +"%Y-%m-%d %H:%M:%SZ")"
echo "Shell PID $$, User=$(id -un), CWD=$(pwd)"
echo

# mask utility for secrets in logs
mask() {
  local val="$1"
  if [ -z "$val" ]; then
    echo "<empty>"
  else
    if [ ${#val} -le 6 ]; then
      echo "*****"
    else
      echo "${val:0:2}*****${val: -2}"
    fi
  fi
}

echo "ENV summary:"
echo "  DOTTY_MQTT_BROKER = ${DOTTY_MQTT_BROKER:-<unset>}"
echo "  DOTTY_MQTT_PORT   = ${DOTTY_MQTT_PORT:-<unset>}"
echo "  DOTTY_MQTT_USER   = $(mask "${DOTTY_MQTT_USER:-}")"
echo "  DOTTY_MQTT_PASS   = $( [ -n "${DOTTY_MQTT_PASS:-}" ] && echo '<set>' || echo '<unset>' )"
echo "  SHOW_SECONDS_FILE = ${SHOW_SECONDS_FILE:-/tmp/dotty_show_seconds}"
echo

echo "Using PYTHON_BIN: $PYTHON_BIN"
"$PYTHON_BIN" --version || echo "[!] python --version failed"
echo "Which python: $(command -v "$PYTHON_BIN" || echo '<not found>')"
echo

# ----- clone or update -----
if [ -d "$REPO_DIR/.git" ]; then
    echo "[*] repo exists at $REPO_DIR — updating"
    cd "$REPO_DIR" || { echo "[ERR] cd $REPO_DIR failed"; exit 1; }

    # ensure remote exists
    if ! git remote get-url origin >/dev/null 2>&1; then
        echo "[*] adding origin $REPO_URL"
        git remote add origin "$REPO_URL" || echo "[WARN] git remote add failed"
    fi

    echo "[*] fetching origin..."
    if ! git fetch origin --tags --prune; then
        echo "[WARN] git fetch returned non-zero"
    fi

    DEFAULT_BRANCH=$(git remote show origin 2>/dev/null | awk '/HEAD branch/ {print $NF}')
    [ -z "$DEFAULT_BRANCH" ] && DEFAULT_BRANCH="master"
    echo "[*] default branch: $DEFAULT_BRANCH"

    echo "[*] checking out $DEFAULT_BRANCH"
    if ! git checkout "$DEFAULT_BRANCH"; then
        echo "[WARN] git checkout $DEFAULT_BRANCH failed"
    fi

    echo "[*] resetting to origin/$DEFAULT_BRANCH"
    if ! git reset --hard "origin/$DEFAULT_BRANCH"; then
        echo "[WARN] git reset --hard origin/$DEFAULT_BRANCH failed"
    fi

    echo "[*] repo recent commits:"
    git --no-pager log -n 5 --pretty=format:'  %h %ad %s <%an>' --date=short || true
else
    echo "[*] cloning $REPO_URL -> $REPO_DIR"
    if ! git clone "$REPO_URL" "$REPO_DIR"; then
        echo "[ERR] git clone failed"
    fi
    cd "$REPO_DIR" || { echo "[ERR] cd $REPO_DIR failed"; exit 1; }
fi

cd "$REPO_DIR" || { echo "[ERR] cd $REPO_DIR failed"; exit 1; }

# ----- venv -----
if [ ! -d "venv" ]; then
    echo "[*] creating venv..."
    if ! "$PYTHON_BIN" -m venv venv; then
        echo "[ERR] failed to create venv"
    fi
fi

# Activate venv for the rest of this script's commands
# shellcheck disable=SC1091
source venv/bin/activate || { echo "[ERR] failed to source venv"; exit 1; }
echo "[*] activated venv: $(which python)"

# ----- pip / deps -----
echo "[*] upgrading pip and installing basic deps..."
set -x
python -m pip install --upgrade pip
python -m pip install --upgrade wheel setuptools
python -m pip install pyserial numpy pillow paho-mqtt || echo "[WARN] pip install basic deps failed"
set +x

if [ -f requirements.txt ]; then
    echo "[*] installing requirements.txt..."
    set -x
    python -m pip install -r requirements.txt || echo "[WARN] requirements install failed"
    set +x
fi

echo "[*] pip freeze (top 50):"
python - <<'PY'
import pkg_resources
for p in sorted(pkg_resources.working_set, key=lambda p: p.project_name.lower())[:50]:
    print("  ", p.project_name, p.version)
PY

# quick python import checks to catch missing modules
echo "[*] validating imports..."
python - <<'PY'
import sys
failed = []
for mod in ("serial", "numpy", "paho.mqtt.client"):
    try:
        __import__(mod.split(".")[0])
        print("[OK] import", mod)
    except Exception as e:
        print("[ERR] import", mod, "->", e)
        failed.append(mod)
if failed:
    sys.exit(2)
PY
if [ $? -ne 0 ]; then
    echo "[WARN] import validation failed (see log)"
fi

# ----- MQTT broker connectivity test (if broker configured) -----
if [ -n "${DOTTY_MQTT_BROKER:-}" ]; then
    BROKER="${DOTTY_MQTT_BROKER}"
    PORT="${DOTTY_MQTT_PORT:-1883}"

    echo "[*] testing TCP connectivity to MQTT broker $BROKER:$PORT ..."
    if command -v nc >/dev/null 2>&1; then
        if nc -vz "$BROKER" "$PORT"; then
            echo "[OK] nc connect succeeded"
        else
            echo "[WARN] nc connect failed (broker may be unreachable)"
        fi
    else
        echo "[*] nc not available; using python socket test..."
        python - <<'PY'
import socket, os, sys
b = os.environ.get("DOTTY_MQTT_BROKER")
p = int(os.environ.get("DOTTY_MQTT_PORT", "1883"))
s = socket.socket()
s.settimeout(3.0)
try:
    s.connect((b, p))
    print("[OK] socket connect succeeded")
except Exception as e:
    print("[WARN] socket connect failed:", e)
    sys.exit(1)
finally:
    try:
        s.close()
    except:
        pass
PY
        if [ $? -ne 0 ]; then
            echo "[WARN] python socket test failed"
        fi
    fi
else
    echo "[*] DOTTY_MQTT_BROKER not set; skipping broker connectivity test"
fi

# log a little environment dump (non-sensitive)
echo "[*] small environment dump:"
echo "  PATH=$PATH"
echo "  PWD=$(pwd)"
echo "  USER=$(id -un)"
echo "  UPTIME=$(uptime -p 2>/dev/null || true)"
echo

# ----- final start -----
echo "[*] starting app: $PYTHON_BIN $APP_ENTRY"
echo "  (app stdout+stderr will also be appended to $LOGFILE)"
# trap to record exit
trap 'EXIT_CODE=$?; echo "=== dotty startup script exiting with $EXIT_CODE at $(date -u +"%Y-%m-%d %H:%M:%SZ")" >> '"$LOGFILE"'; exit $EXIT_CODE' EXIT

# Use exec so systemd will track the python process; preserve logs via tee above
exec "$PYTHON_BIN" "$APP_ENTRY"
