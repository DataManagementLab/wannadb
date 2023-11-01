#!/bin/sh

# Create and activate the virtual environment
python -m venv venv
. venv/bin/activate
export PYTHONPATH="."

pytest

flask --app backend/app.py run

sleep infinity
