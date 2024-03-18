#!/bin/sh

# Create and activate the virtual environment
python -m venv venv
. venv/bin/activate
export PYTHONPATH="."

pytest

gunicorn -w 4 --bind 0.0.0.0:8000 app:app