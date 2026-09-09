FROM python:3.11-slim-bullseye as build

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
  # dependencies for building Python packages
  && apt-get install -y --no-install-recommends build-essential \
  # psycopg2 dependencies
  && apt-get install -y --no-install-recommends libpq-dev \
  # Additional dependencies
  && apt-get install -y --no-install-recommends telnet netcat \
  # PyQt6 / Qt runtime dependencies
  && apt-get install -y --no-install-recommends \
  netcat-openbsd \
  libegl1 \
  libgl1 \
  libfontconfig1 \
  libglib2.0-0 \
  libdbus-1-3 \
  libxkbcommon-x11-0 \
  libxcb-cursor0 \
  libxcb-xinerama0 \
  # cleaning up unused files
  && apt-get purge -y --auto-remove -o APT::AutoRemove::RecommendsImportant=false \
  && rm -rf /var/lib/apt/lists/*

RUN mkdir /home/wannadb
WORKDIR /home/wannadb

# update Pip
RUN pip install --upgrade pip

# install torch
RUN pip install --use-pep517 torch==2.4.1

# Install dependencies
COPY core-requirements.txt core-requirements.txt
RUN pip install --use-pep517 -r core-requirements.txt

COPY backend-requirements.txt backend-requirements.txt
RUN pip install --use-pep517 -r backend-requirements.txt

##################################
##      do not change above     ##
##      changes above cause     ##
##      long loading times      ##
##################################

# Install the spaCy model before starting the backend.
# Replace en_core_web_sm with the value of cls._spacy_package_str.
ARG SPACY_MODEL=en_core_web_sm
RUN python -m spacy download "${SPACY_MODEL}"
ARG SPACY_MODEL=en_core_web_trf
RUN python -m spacy download "${SPACY_MODEL}"
ARG SPACY_MODEL=en_core_web_lg
RUN python -m spacy download "${SPACY_MODEL}"
ARG SPACY_MODEL=en_core_web_md
RUN python -m spacy download "${SPACY_MODEL}"

RUN mkdir -p models/spacy models/fasttext models/glove

COPY scripts/prepare_models.py /home/wannadb/scripts/prepare_models.py
RUN python /home/wannadb/scripts/prepare_models.py

# Download and extract the GloVe vectors
COPY scripts/prepare_glove.py /home/wannadb/scripts/prepare_glove.py
RUN python /home/wannadb/scripts/prepare_glove.py


# Run tests
RUN pip install --use-pep517 pytest
# RUN pytest


FROM build as worker


FROM build as worker-prod

# copy the rest
COPY . .


FROM build as dev

# CMD ["python", "app.py"]

# Note: only the last CMD in a Docker stage is used.
# CMD ["mypy", "--install-types", "--non-interactive"]

CMD ["flask", "--app", "app", "--debug", "run", "--host", "0.0.0.0", "--port", "8000"]


FROM worker-prod as prod

RUN chmod +x wannadb_web/entrypoint.sh

# Define the entrypoint.sh
CMD ["sh", "./wannadb_web/entrypoint.sh"]