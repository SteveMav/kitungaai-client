#!/usr/bin/env bash
set -e

cd "$(dirname "$0")/.."
git pull origin main || true

VENV_DIR="${KITUNGA_VENV_DIR:-.venv}"

if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install -r requirements.txt
fi

exec "$VENV_DIR/bin/python" main.py
