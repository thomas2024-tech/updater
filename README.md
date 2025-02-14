# Application Version Management System

This repository has a Python script designed to manage Docker services using Redis pub-sub and RPC mechanisms. The system listens for version updates, compares running versions with available versions on Docker Hub, and sends RPC commands to update applications when necessary.

## Table of Contents

- Introduction
- Architecture Overview
- Components
  - Main Application
  - Docker Compose RPC Service
- Setup Instructions
  - Prerequisites
- Installation
- Configuration
- Usage
 - Running the Main Application
 - Running the Docker Compose RPC Service


## Introduction

This system automates the management of Dockerized applications by monitoring version updates and handling dependencies between applications. It uses Redis for messaging and RPC, and interacts with Docker Hub to fetch available image versions.

## Architecture Overview

- Main Application: Orchestrates version management across multiple applications.
- Docker Compose RPC Service: Runs on application host machines, exposing an RPC service to handle Docker Compose commands like updating the application version or bringing down services.

## Components
### Main Application

**Purpose**: 

- Manages version updates and application dependencies.

**Functionality**:

- Listens for version updates on a Redis pub-sub channel.
- Interacts with Docker Hub to retrieve available image versions.
- Compares running versions with available versions.
- Handles application dependencies.
- Sends RPC commands to update applications when necessary.

**Key Classes and Functions**:

- VersionMessage: Defines the message format for version updates.
- DockerCommandRequest & DockerCommandResponse: Define RPC message formats for Docker commands.
- RPCDockerManager: Manages RPC clients for sending Docker commands.
- DockerHubManager: Manages interactions with Docker Hub.
- MainApplication: Initializes all components and starts the version listener.

### Docker Compose RPC Service

**Purpose**:

- Exposes an RPC service on application host machines to handle Docker Compose commands.

**Functionality**:

- Handles down and update_version commands.
- Updates the docker-compose.yml file with new image versions.
- Restarts Docker services as needed.
- Publishes version information to the Redis pub-sub channel.

**Key Classes and Functions**:

- VersionMessage: Defines the message format for version updates.
- DockerCommandRequest & DockerCommandResponse: Define RPC message formats for Docker commands.
- DockerComposeRPCService: Handles incoming RPC requests to manage Docker services.
- load_docker_compose_data(): Reads application name and version from docker-compose.yml.
- publish_version(): Publishes version information to the Redis pub-sub channel.

## Setup Instructions
**Prerequisites**:

- Docker and Docker Compose
- Access to Docker Hub
- Access to Github

## Installation
The updater app runs after the installation of the respective requirements (preferably on a virual enviroment).
The firmwares (apps) are dockerized (via the respective Dockerfiles). Examples of docker-compose.yml are also provided. 
The redis server is dockerizer with the use of respective docker compose yml that is supposed to start as a system service (the respective .sh file is also provided). * Also the docker compose yml and the dockerfile are setup in a way that if user chose it can also dockerize the updater app (if this is chosen, code must be altered since right now interacts with user via terminal).

## Configuration
Redis is configured by the redis file provided "redis.conf" (it allows the access from all ip's and not just localhost)

## Usage
Via this system a user is able to auto update dockerized firmwares to systems that belong to same network (or have access to each other) based on the compatibility demands (dependencies) that are specified of each.

### Running the Main Application

updater.py make use of redis in order to listen for apps (firmwares) that publish on specific channel their version and their dependencies (all of which are dockerized). Updater app then check the respective docker hub repo for confirmation that dependencies exist and issue commands via RPC to each system that stop containers, change version and start containers again. Also updater checks every hour for new versions of docker images on docker hub in order to inform user if a new version is located and give him choise to update (also by issuing commands via RPC).

### Running the Docker Compose RPC Service

In order all this coordination to work, each system (app) will have a docker-compose.yml of which the first app will be a dockerized version of a python code. This code is responsible to publish via redis the version of the app and its dependencies (minimum versions needed in order to work as expected).User is free to change this app by adding functionality or add (as a second app) a complete different code or firmware. 

The changes/updates of each app firmware can be part of a CI/CD pipeline that will automatically create a new docker image and publish it to docker hub everytime a staging Git branch is merger to main. (example of Git Action is provided). User only have to setup version and dependencies.
