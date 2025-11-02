#!/bin/bash
set -e

REPO_URL="https://github.com/TheChaseFiore/Dotty"
REPO_DIR="/home/chase/Dotty"   # use your real path
PYTHON_SCRIPT="/home/chase/Dotty/Dotty/main.py"
PYTHON_BIN="/usr/bin/python3"

if [ -d "$REPO_DIR/.git" ]; then
    echo "[*] Repository exists. Pulling latest changes..."
    cd "$REPO_DIR"

    # make sure origin exists
    if ! git remote get-url origin >/dev/null 2>&1; then
        git remote add origin "$REPO_URL"
    fi

    # fetch EVERYTHING first
    git fetch origin

    # ask git what the default branch is
    DEFAULT_BRANCH=$(git remote show origin 2>/dev/null | awk '/HEAD branch/ {print $NF}')
    [ -z "$DEFAULT_BRANCH" ] && DEFAULT_BRANCH="main"   # fallback

    # check out that branch locally
    if ! git rev-parse --verify "$DEFAULT_BRANCH" >/dev/null 2>&1; then
        git checkout -b "$DEFAULT_BRANCH" "origin/$DEFAULT_BRANCH"
    else
        git checkout "$DEFAULT_BRANCH"
    fi

    # now it is safe to hard reset
    git reset --hard "origin/$DEFAULT_BRANCH"
else
    echo "[*] Cloning repository..."
    git clone "$REPO_URL" "$REPO_DIR"
    cd "$REPO_DIR"
fi
