FROM python:3.9

USER root
RUN mkdir /home/wannadb
WORKDIR /home/wannadb

# install torch
RUN pip install --use-pep517 torch==1.10.0

# Install dependencies
COPY requirements.txt requirements.txt
RUN pip install --use-pep517 -r requirements.txt
##################################
##      do not change above     ##
##      changes above cause     ##
##      long loading times      ##
##################################

# Run tests
RUN pip install --use-pep517 pytest
#RUN pytest

#copy the rest
COPY . .

RUN chmod +x entrypoint.sh


# Define the entrypoint.sh
ENTRYPOINT "/home/wannadb/entrypoint.sh" 