FROM python:3.11-slim-bookworm AS build

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
  # dependencies for building Python packages
  && apt-get install -y --no-install-recommends build-essential \
  # psycopg2 dependencies
  && apt-get install -y --no-install-recommends libpq-dev \
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

# The web pipeline uses the large English spaCy model.
ARG SPACY_MODEL=en_core_web_lg
RUN python -m spacy download "${SPACY_MODEL}"
RUN pip install --use-pep517 pytest

FROM build AS dev-models

# The desktop and experimental pipelines use these additional assets.
RUN python -m spacy download en_core_web_sm \
  && python -m spacy download en_core_web_trf \
  && python -m spacy download en_core_web_md

RUN mkdir -p models/spacy models/fasttext models/glove

COPY scripts/prepare_models.py /home/wannadb/scripts/prepare_models.py
RUN python /home/wannadb/scripts/prepare_models.py

COPY scripts/prepare_glove.py /home/wannadb/scripts/prepare_glove.py
RUN python /home/wannadb/scripts/prepare_glove.py

FROM dev-models AS worker

FROM dev-models AS dev
CMD ["flask", "--app", "app", "--no-debug", "run", "--host", "0.0.0.0", "--port", "8000"]

FROM build AS worker-prod

# Seed the caches used by the web preprocessing and matching pipelines.
RUN python -c "import stanza; stanza.download('en', model_dir='models/stanza', processors='tokenize,mwt,pos,ner')"
RUN python -c "from transformers import BertModel, BertTokenizerFast; \
    BertTokenizerFast.from_pretrained('bert-large-cased', cache_dir='models/transformers'); \
    BertModel.from_pretrained('bert-large-cased', cache_dir='models/transformers')"
RUN python -c "from sentence_transformers import SentenceTransformer; \
    SentenceTransformer('bert-large-nli-mean-tokens', cache_folder='models/sentence-transformers', device='cpu')"
ENV HF_HUB_OFFLINE=1

COPY app.py celery_app.py ./
COPY wannadb ./wannadb
COPY wannadb_parsql ./wannadb_parsql
COPY wannadb_ui ./wannadb_ui
COPY wannadb_web ./wannadb_web
COPY tests ./tests

FROM worker-prod AS prod
CMD ["sh", "./wannadb_web/entrypoint.sh"]
