#!/bin/bash
set -e

REPO_URL="https://github.com/TheChaseFiore/Dotty.git"
REPO_DIR="/home/chase/Dotty"
APP_ENTRY="Dotty/main.py"
PYTHON_BIN="/usr/bin/python3"

echo "=== Dotty updater ==="

# ----- clone or update -----
if [ -d "$REPO_DIR/.git" ]; then
    cd "$REPO_DIR"

    # make sure remote exists
    if ! git remote get-url origin >/dev/null 2>&1; then
        git remote add origin "$REPO_URL"
    fi

    git fetch origin
    DEFAULT_BRANCH=$(git remote show origin 2>/dev/null | awk '/HEAD branch/ {print $NF}')
    [ -z "$DEFAULT_BRANCH" ] && DEFAULT_BRANCH="master"

    git checkout "$DEFAULT_BRANCH"
    git reset --hard "origin/$DEFAULT_BRANCH"
else
    git clone "$REPO_URL" "$REPO_DIR"
    cd "$REPO_DIR"
fi

cd "$REPO_DIR"

# ----- venv -----
if [ ! -d "venv" ]; then
    echo "[*] creating venv..."
    $PYTHON_BIN -m venv venv
fi

# shellcheck source=/dev/null
source venv/bin/activate

# ----- deps -----
python -m pip install --upgrade pip
# your code imports serial and numpy
python -m pip install pyserial numpy

# if you later add a requirements.txt, this will pick it up too
if [ -f requirements.txt ]; then
    python -m pip install -r requirements.txt || echo "[!] requirements install failed"
fi

echo "[*] starting app..."
exec python "$APP_ENTRY"
