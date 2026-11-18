#!/bin/sh
set -eu

exec python -m gunicorn -w 4 --bind 0.0.0.0:8000 app:app
