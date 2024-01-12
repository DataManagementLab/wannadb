FROM python:3.9-slim-buster as build

ENV PYTHONUNBUFFERED 1
ENV PYTHONDONTWRITEBYTECODE 1

RUN apt-get update \
  # dependencies for building Python packages
  && apt-get install -y build-essential \
  # psycopg2 dependencies
  && apt-get install -y libpq-dev \
  # Additional dependencies
  && apt-get install -y telnet netcat \
  # cleaning up unused files
  && apt-get purge -y --auto-remove -o APT::AutoRemove::RecommendsImportant=false \
  && rm -rf /var/lib/apt/lists/*

RUN mkdir /home/wannadb
WORKDIR /home/wannadb

# install torch
RUN pip install --use-pep517 torch==1.10.0

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

# Run tests
RUN pip install --use-pep517 pytest
#RUN pytest

FROM build as worker



FROM build as dev 

#CMD [ "python", "app.py" ]

CMD ["flask", "--app", "app", "--debug", "run","--host","0.0.0.0", "--port", "8000" ]


FROM build as prod

#copy the rest
COPY . .

RUN chmod +x entrypoint.sh

# Define the entrypoint.sh
CMD ["sh","./entrypoint.sh"]

