FROM python:3.9

USER root
RUN mkdir /home/wannadb
WORKDIR /home/wannadb
COPY requirements.txt requirements.txt

# Install dependencies
RUN pip install --use-pep517 torch==1.10.0

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

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8080
EXPOSE 5000

# Define the entrypoint.sh
CMD ["/entrypoint.sh"]