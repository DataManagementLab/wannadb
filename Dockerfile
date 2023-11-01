FROM python:3.9

USER root
RUN mkdir /home/wannadb
WORKDIR /home/wannadb
COPY . .

EXPOSE 8080

# Create virtual environment
RUN python -m venv venv
RUN . venv/bin/activate
RUN export PYTHONPATH="."

# Install dependencies
RUN pip install --upgrade pip
RUN pip install --use-pep517 -r requirements.txt

# installing torch manually
RUN pip install torch==1.10.0
RUN pip install torchvision==0.11.1

# Run tests
RUN pip install --use-pep517 pytest
RUN pytest

# Keep container running
RUN while true; do sleep 1000