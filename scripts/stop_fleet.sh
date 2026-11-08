#!/usr/bin/env bash
# Stop the fleet and all its twin workers (matches only the venv python, never a shell).
PY=$(cd "$(dirname "$0")/.." && pwd)/venv/bin/python
pkill -u "$(id -u)" -f "^$PY (-m sidekick\.fleet|-c from multiprocessing\.spawn)"
sleep 2
pgrep -u "$(id -u)" -f "^$PY (-m sidekick\.fleet|-c from multiprocessing\.spawn)" | wc -l
