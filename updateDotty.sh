#!/bin/bash
set -e

# --- config ---
REPO_URL="https://github.com/TheChaseFiore/Dotty.git"
REPO_DIR="/home/chase/Dotty"
APP_ENTRY="Dotty/main.py"       # this matches your traceback
PYTHON_BIN="/usr/bin/python3"   # system python

echo "=== Dotty updater ==="

# 1) clone or update
if [ -d "$REPO_DIR/.git" ]; then
    cd "$REPO_DIR"

    # make sure 'origin' exists
    if ! git remote get-url origin >/dev/null 2>&1; then
        git remote add origin "$REPO_URL"
    fi

    # fetch all
    git fetch origin

    # figure out default branch
    DEFAULT_BRANCH=$(git remote show origin 2>/dev/null | awk '/HEAD branch/ {print $NF}')
    [ -z "$DEFAULT_BRANCH" ] && DEFAULT_BRANCH="master"

    # checkout & hard reset
    git checkout "$DEFAULT_BRANCH"
    git reset --hard "origin/$DEFAULT_BRANCH"
else
    # first time
    git clone "$REPO_URL" "$REPO_DIR"
    cd "$REPO_DIR"
fi

# 2) venv
cd "$REPO_DIR"
if [ ! -d "venv" ]; then
    echo "[*] creating venv..."
    $PYTHON_BIN -m venv venv
fi

# shellcheck source=/dev/null
source venv/bin/activate

# 3) deps (don't kill the whole service if requirements.txt is missing)
pip install -U pip || echo "[!] pip upgrade failed (network?)"
if [ -f requirements.txt ]; then
    pip install -r requirements.txt || echo "[!] requirements install failed"
fi

echo "[*] starting app..."
# 4) replace shell with python so systemd tracks it
exec "$REPO_DIR/venv/bin/python" "$REPO_DIR/$APP_ENTRY"
