#!/bin/bash
set -euo pipefail

# === CONFIG ===
REPO_URL="https://github.com/TheChaseFiore/Dotty.git"
REPO_DIR="/home/chase/Dotty"
APP_ENTRY="main.py"
PYTHON_BIN="/usr/bin/python3"

# === COLORS ===
RED="\033[0;31m"
GREEN="\033[0;32m"
YELLOW="\033[1;33m"
BLUE="\033[0;34m"
RESET="\033[0m"

# === FUNCTIONS ===
log() {
    echo -e "${BLUE}[$(date '+%H:%M:%S')]${RESET} $*"
}

ok() {
    echo -e "${GREEN}[$(date '+%H:%M:%S')] ✓${RESET} $*"
}

warn() {
    echo -e "${YELLOW}[$(date '+%H:%M:%S')] ⚠${RESET} $*"
}

err() {
    echo -e "${RED}[$(date '+%H:%M:%S')] ✗${RESET} $*" >&2
}

# === MAIN ===
log "=== Dotty Updater Started ==="
log "Repository: $REPO_URL"
log "Local path: $REPO_DIR"
log "Python binary: $PYTHON_BIN"

# ----- clone or update -----
if [ -d "$REPO_DIR/.git" ]; then
    log "Repository already exists. Updating..."
    cd "$REPO_DIR"

    if git remote get-url origin >/dev/null 2>&1; then
        log "Remote 'origin' exists: $(git remote get-url origin)"
    else
        warn "No remote 'origin' found. Adding it..."
        git remote add origin "$REPO_URL"
        ok "Remote added."
    fi

    log "Fetching latest changes from origin..."
    if ! git fetch origin; then
        err "Failed to fetch updates from origin!"
        exit 1
    fi
    ok "Fetched successfully."

    DEFAULT_BRANCH=$(git remote show origin 2>/dev/null | awk '/HEAD branch/ {print $NF}')
    [ -z "$DEFAULT_BRANCH" ] && DEFAULT_BRANCH="master"
    log "Default branch detected: $DEFAULT_BRANCH"

    log "Checking out and resetting branch..."
    git checkout "$DEFAULT_BRANCH" >/dev/null 2>&1 || {
        err "Failed to checkout branch $DEFAULT_BRANCH"
        exit 1
    }
    git reset --hard "origin/$DEFAULT_BRANCH" >/dev/null 2>&1 || {
        err "Failed to reset branch to origin/$DEFAULT_BRANCH"
        exit 1
    }
    ok "Repository synced to origin/$DEFAULT_BRANCH"

else
    warn "Repository not found. Cloning from $REPO_URL..."
    git clone "$REPO_URL" "$REPO_DIR" || {
        err "Git clone failed!"
        exit 1
    }
    cd "$REPO_DIR"
    ok "Repository cloned successfully."
fi

# ----- venv -----
log "Checking virtual environment..."
if [ ! -d "venv" ]; then
    warn "No venv found. Creating new virtual environment..."
    if "$PYTHON_BIN" -m venv venv; then
        ok "Virtual environment created."
    else
        err "Failed to create virtual environment!"
        exit 1
    fi
else
    ok "Virtual environment already exists."
fi

# shellcheck source=/dev/null
log "Activating virtual environment..."
source venv/bin/activate

# ----- deps -----
log "Upgrading pip..."
python -m pip install --upgrade pip >/dev/null 2>&1 && ok "pip upgraded." || warn "pip upgrade failed."

log "Installing core dependencies: pyserial, numpy..."
if python -m pip install pyserial numpy >/dev/null 2>&1; then
    ok "Core dependencies installed."
else
    warn "Dependency installation encountered issues."
fi

if [ -f requirements.txt ]; then
    log "Found requirements.txt. Installing additional dependencies..."
    if python -m pip install -r requirements.txt >/dev/null 2>&1; then
        ok "requirements.txt installed successfully."
    else
        warn "requirements.txt installation failed."
    fi
else
    warn "No requirements.txt found."
fi

# ----- run -----
log "Starting application: $APP_ENTRY"
if [ -f "$APP_ENTRY" ]; then
    exec python "$APP_ENTRY"
else
    err "Application entry file '$APP_ENTRY' not found!"
    exit 1
fi
