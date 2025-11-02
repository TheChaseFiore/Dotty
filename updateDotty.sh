#!/bin/bash

# --- Configuration ---
REPO_URL="https://github.com/TheChaseFiore/Dotty"
REPO_DIR="/Dotty"
PYTHON_SCRIPT="Dotty/main.py"   # Change to your script name
PYTHON_BIN="/usr/bin/python3"  # Adjust if needed

# --- Script Start ---
set -e  # Exit on error
echo "=== Updating and running repo ==="

# If the repo already exists, update it; otherwise, clone it
if [ -d "$REPO_DIR/.git" ]; then
    echo "[*] Repository exists. Pulling latest changes..."
    cd "$REPO_DIR"
    git fetch origin main 2>/dev/null || true
    git reset --hard origin/main
else
    echo "[*] Cloning repository..."
    git clone "$REPO_URL" "$REPO_DIR"
    cd "$REPO_DIR"
fi

# Optional: Create or update Python virtual environment
if [ ! -d "venv" ]; then
    echo "[*] Creating virtual environment..."
    $PYTHON_BIN -m venv venv
fi

source venv/bin/activate
pip install -U pip
pip install -r requirements.txt || echo "[!] No requirements.txt found."

# --- Run the Python script ---
echo "[*] Running $PYTHON_SCRIPT..."
$PYTHON_BIN "$PYTHON_SCRIPT"

echo "=== Done ==="
