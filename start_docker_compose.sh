#!/bin/bash
# directory where your docker-compose.yml is located
cd <path of the docker compose yml>

# Check if the network 'my_network' exists
if ! docker network ls | grep -q "my_network"; then
    echo "Creating shared_network..."
    docker network create my_network
else
    echo "shared_network already exists."
fi

# start the Docker Compose service
docker compose up --build
