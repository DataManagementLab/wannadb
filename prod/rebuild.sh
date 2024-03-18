#!/bin/bash

docker stop $(docker ps -a -q)
docker rm $(docker ps -a -q)

docker compose -f docker-compose-prod.yaml build

docker compose -f docker-compose-prod.yaml up -d
