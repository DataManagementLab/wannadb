#!/bin/sh
set -eu

python -m pytest tests
exec python -m gunicorn -w 4 --bind 0.0.0.0:8000 app:app
