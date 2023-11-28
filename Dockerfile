FROM python:3.9 as build

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

FROM build as dev 

#CMD [ "python", "app.py" ]
CMD ["flask", "--app", "app", "--debug", "run","--host","0.0.0.0", "--port", "8000" ]


FROM build as prod

RUN chmod +x entrypoint.sh

# Define the entrypoint.sh
CMD ["sh","./entrypoint.sh"]

