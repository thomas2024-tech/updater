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
Both the updater and the firmwares are dockerized (via the respective Dockerfiles). Also examples of docker-compose.yml are also provided

## Configuration

## Usage

### Running the Main Application

### Running the Docker Compose RPC Service
