# Docker Application Updater System Documentation

## Overview

The Docker Application Updater System is a microservice designed to manage and coordinate selective updates of containerized applications across multiple machines. The system monitors application versions and orchestrates user-specified updates through a message-driven architecture using Redis pub-sub and RPC communication patterns.

## Features

- **Selective App Updates**: Updates only applications specified in user configuration
- **Docker Hub Integration**: Validates target versions exist on Docker Hub
- **Configuration-Driven Updates**: No terminal interaction required  
- **Redis-Based Communication**: Uses pub-sub for version reporting and RPC for updates
- **Containerized Deployment**: Fully dockerized with docker-compose
- **Distributed Architecture**: Apps run on separate machines from the updater

## System Architecture

### High-Level Design

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Application   │    │   Application   │    │   Application   │
│      App1       │    │      App2       │    │      App3       │
│  (Machine 1)    │    │  (Machine 2)    │    │  (Machine 3)    │
└─────────┬───────┘    └─────────┬───────┘    └─────────┬───────┘
          │                      │                      │
          │ Publishes Version    │ Publishes Version    │ Publishes Version
          │                      │                      │
          └──────────────────────┼──────────────────────┘
                                 │
                          ┌──────▼──────┐
                          │    Redis    │
                          │  Pub/Sub    │
                          │   Channel   │
                          └──────┬──────┘
                                 │ Listens
                          ┌──────▼──────┐
                          │   Updater   │
                          │   Service   │
                          └──────┬──────┘
                                 │ Checks
                          ┌──────▼──────┐
                          │ Docker Hub  │
                          │     API     │
                          └─────────────┘
```

### Core Components

1. **MainApplication**: Orchestrates the entire system
2. **VersionListener**: Monitors version update messages
3. **DockerHubManager**: Interfaces with Docker Hub API
4. **RPCDockerManager**: Manages remote procedure calls for Docker operations

## Detailed Component Analysis

### 1. Message Classes

#### VersionMessage
```python
class VersionMessage(PubSubMessage):
    appname: str
    version_number: str
    dependencies: dict
```

**Purpose**: Represents version update notifications published by applications.

**Attributes**:
- `appname`: Unique identifier for the application
- `version_number`: Current semantic version (e.g., "1.2.3")
- `dependencies`: Dictionary of dependent apps (empty in current implementation)

#### DockerCommandRequest/Response
```python
class DockerCommandRequest(RPCMessage):
    command: str
    directory: str
    new_version: str = None

class DockerCommandResponse(RPCMessage):
    success: bool
    message: str
```

**Purpose**: RPC message format for requesting Docker operations on remote machines.

**Commands Supported**:
- `update_version`: Updates an application to a specified version
- `down`: Stops the application containers

### 2. RPCDockerManager Class

#### Functionality
The RPCDockerManager handles communication with remote Docker services running on different machines.

#### Key Methods

##### `__init__()`
- Establishes Redis connection using environment variables
- Creates a communication node with name 'updater_node'
- Initializes RPC clients for each application service:
  - `app1` → `docker_compose_service_machine1`
  - `app2` → `docker_compose_service_machine2`
  - `app3` → `docker_compose_service_machine3`

##### `update_app_version(appname, directory, new_version)`
- Sends RPC command to update a specific application
- Parameters:
  - `appname`: Target application identifier
  - `directory`: Working directory for Docker operations
  - `new_version`: Desired version to update to
- Returns: Success/failure status with descriptive messages

#### Configuration
Uses environment variables for Redis connection:
- `REDIS_HOST`: Redis server hostname (default: localhost)
- `REDIS_PORT`: Redis server port (default: 6379)
- `REDIS_DB`: Redis database number (default: 0)

### 3. DockerHubManager Class

#### Functionality
Manages interactions with Docker Hub's REST API to retrieve available images and their version tags.

#### Key Methods

##### `__init__()`
- Validates Docker Hub credentials from environment variables
- Fetches complete list of images and their versions
- Exits application if credentials are missing

##### `list_docker_images()`
- **Purpose**: Retrieves all repositories and tags from the authenticated Docker Hub account
- **Process**:
  1. Queries Docker Hub API for repository list
  2. For each repository, fetches all available tags
  3. Handles pagination automatically
  4. Returns dictionary mapping: `{image_name: [tag1, tag2, ...]}`
- **Rate Limiting**: None implemented (potential API throttling risk)

#### Configuration Requirements
Environment variables:
- `DOCKER_HUB_USERNAME`: Docker Hub account username
- `DOCKER_HUB_TOKEN`: Docker Hub API access token

#### API Endpoints Used
- Repository listing: `https://hub.docker.com/v2/repositories/{username}/`
- Tag listing: `https://hub.docker.com/v2/repositories/{username}/{repo}/tags`

### 4. VersionListener Class

#### Functionality
Core component that listens for version update messages and orchestrates the update decision process.

#### Key Methods

##### `__init__(docker_hub_manager, rpc_manager)`
- Sets up Redis subscriber for 'version_channel'
- Loads application-to-directory mapping from environment
- Initializes version tracking structures

##### `on_message_received(msg: VersionMessage)`
- **Trigger**: Called when a version message arrives on Redis channel
- **Process**:
  1. Updates internal version tracking
  2. Calls `process_version_message()` for business logic
  3. Flushes logs for immediate output

##### `process_version_message(msg)`
**Core Business Logic**: Determines if updates are needed and triggers them.

**Process Flow**:
1. **Version Validation**: Checks if reported version exists on Docker Hub
2. **User Configuration Check**: Checks if app is listed in `APPS_TO_UPDATE` environment variable
3. **Target Version Comparison**: Compares running version with user-specified target version
4. **Update Execution**: If versions don't match and target exists on Docker Hub, triggers update via RPC
5. **Dependency Logging**: Dependencies in messages are logged but ignored

**Version Comparison Logic**:
```python
def version_compare(self, v1, v2):
    # Returns: 1 if v1 > v2, 0 if equal, -1 if v1 < v2
    # Uses packaging.version.parse for proper semantic versioning
```

##### `listen()`
- Starts the Redis subscriber in blocking mode
- Runs until stop event is signaled
- Handles exceptions and logs errors

#### Configuration
Environment variables:
- `APP_TO_DIRECTORY`: JSON string mapping applications to their Docker compose directories
- `APPS_TO_UPDATE`: JSON string specifying which apps to update and to which versions

**Example Configuration**:
```json
{
  "app1": "/path/to/app1",
  "app2": "/path/to/app2", 
  "app3": "/path/to/app3"
}
```

**Apps to Update Example**:
```json
{
  "app1": "2.1.0",
  "app2": "1.5.3"
}
```

### 5. MainApplication Class

#### Functionality
Orchestrates the entire system, manages lifecycle, and provides additional features like periodic version checking.

#### Key Methods

##### `__init__()`
- Initializes all manager components
- Sets up threading events for coordination

##### `setup_signal_handlers()`
- Registers handlers for SIGINT and SIGTERM
- Ensures graceful shutdown of all components

##### `validate_apps_to_update()`
**Purpose**: Validates that all user-specified app versions exist on Docker Hub at startup.

**Process**:
1. Reads `APPS_TO_UPDATE` configuration
2. Checks each specified version exists on Docker Hub
3. Logs validation results
4. Continues operation even if some versions are invalid

##### `run()`
**Main execution loop** that:
1. Starts version listener in background thread
2. Monitors thread health
3. Handles graceful shutdown
4. Runs indefinitely waiting for version messages

## System Workflows

### 1. Application Version Reporting Flow

```
Application Container
        │
        │ (1) Publishes VersionMessage (with empty dependencies)
        ▼
Redis Pub/Sub Channel ('version_channel')
        │
        │ (2) Message received
        ▼
VersionListener.on_message_received()
        │
        │ (3) Process message
        ▼
VersionListener.process_version_message()
        │
        │ (4) Check if app is in APPS_TO_UPDATE
        ▼
RPCDockerManager.update_app_version() (if version mismatch)
        │
        │ (5) Send RPC command
        ▼
Remote Docker Service
```

### 2. User-Controlled Update Flow

```
User Configuration (APPS_TO_UPDATE)
        │
        │ (1) App reports current version
        ▼
Version comparison with target version
        │
        │ (2) If versions don't match
        ▼
Validate target version exists on Docker Hub
        │
        │ (3) If target version exists
        ▼
RPCDockerManager.update_app_version()
        │
        │ (4) Send RPC command to target machine
        ▼
App updated to user-specified version
```

## Configuration Management

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `REDIS_HOST` | No | redis | Redis server hostname |
| `REDIS_PORT` | No | 6379 | Redis server port |
| `REDIS_DB` | No | 0 | Redis database number |
| `DOCKER_HUB_USERNAME` | Yes | - | Docker Hub account username |
| `DOCKER_HUB_TOKEN` | Yes | - | Docker Hub API token |
| `APP_TO_DIRECTORY` | Yes | - | JSON mapping of apps to directories |
| `APPS_TO_UPDATE` | No | {} | JSON mapping of apps to target versions |

### Sample Configuration

```bash
# Redis Configuration
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_DB=0

# Docker Hub Credentials
DOCKER_HUB_USERNAME=mycompany
DOCKER_HUB_TOKEN=dckr_pat_xyz123...

# Application Mapping
APP_TO_DIRECTORY='{"app1":"/opt/app1","app2":"/opt/app2","app3":"/opt/app3"}'

# Apps to Update (specify which apps to update and to which versions)
# Only apps listed here will be updated. Apps not listed are ignored.
APPS_TO_UPDATE='{"app1":"2.1.0","app2":"1.5.3"}'
```

## Message Formats

### Version Update Message
```json
{
  "appname": "app1",
  "version_number": "2.1.0",
  "dependencies": {}
}
```

### RPC Command Message
```json
{
  "command": "update_version",
  "directory": "/opt/app1",
  "new_version": "2.1.0"
}
```

### RPC Response Message
```json
{
  "success": true,
  "message": "Successfully updated to version 2.1.0"
}
```

## Threading Model

The system uses multiple threads for concurrent operations:

1. **Main Thread**: Runs the primary application loop
2. **Listener Thread**: Handles Redis pub-sub message reception  
3. **Node Communication Thread**: Manages RPC client communications

### Thread Safety Considerations

- **Shared State**: `current_versions` dictionary accessed from multiple threads
- **No Locking**: Current implementation lacks thread synchronization
- **Potential Race Conditions**: Version tracking and update operations

## Error Handling

### Exception Management
- **Docker Hub API Failures**: Logged but don't stop the service
- **RPC Communication Errors**: Logged with retry capability
- **Redis Connection Issues**: Can cause service failure
- **Configuration Errors**: Result in immediate application exit

### Logging Strategy
- **Level**: INFO level for normal operations
- **Format**: Timestamp, level, and message
- **Output**: Console with immediate flushing
- **Error Details**: Exception messages included in logs

## Dependencies

### Python Packages
- `commlib`: Communication library for pub-sub and RPC
- `requests`: HTTP client for Docker Hub API
- `packaging`: Semantic version parsing and comparison
- `python-dotenv`: Environment variable management

### External Services
- **Redis Server**: Message broker for pub-sub and RPC
- **Docker Hub API**: Repository and tag information
- **Remote Docker Services**: Target machines running applications

## Security Considerations

### Authentication
- **Docker Hub**: Token-based authentication
- **Redis**: No authentication configured (security risk)
- **RPC**: No authentication mechanism

### Data Privacy
- **Credentials**: Docker Hub token in memory (potential exposure in logs)
- **Network**: Unencrypted Redis communication

### Access Control
- **No authorization**: Any Redis client can publish version messages
- **No validation**: RPC commands executed without verification

## Performance Characteristics

### Startup Time
- **Docker Hub Fetch**: Synchronous, can be slow for many repositories
- **Redis Connection**: Fast, typically < 1 second

### Runtime Performance
- **Message Processing**: Near real-time (< 100ms typical)
- **Version Validation**: On-demand when apps report versions
- **Memory Usage**: Grows with number of repositories and tags

### Scalability Limits
- **Docker Hub API**: Rate limited (no explicit handling)
- **Memory**: All tags stored in memory
- **Threading**: Fixed thread pool size

## Deployment Considerations

### Docker Deployment
```dockerfile
FROM python:3.9-slim
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY updater.py .
CMD ["python", "updater.py"]
```

### Service Configuration
- **Restart Policy**: Should restart on failure
- **Health Checks**: Monitor Redis connectivity
- **Resource Limits**: CPU and memory constraints recommended

### Network Requirements
- **Outbound HTTPS**: Access to Docker Hub API
- **Redis Access**: Pub-sub and RPC communication
- **RPC Connectivity**: Access to application machines

## Monitoring and Observability

### Logs
- Application version reports  
- User-specified update decisions
- RPC command results
- Version validation results
- Dependency messages (logged but ignored)
- Error conditions and exceptions

### Metrics (Not Implemented)
- Message processing rate
- Update success/failure rates
- Docker Hub API response times
- Thread health status

## Known Limitations

1. **Manual Configuration**: Updates require manual editing of APPS_TO_UPDATE
2. **No Rollback**: Failed updates cannot be automatically reverted
3. **Single Point of Failure**: Redis dependency
4. **No Caching**: Docker Hub data fetched on every startup
5. **Thread Safety**: Race conditions in shared state access
6. **Security**: No authentication or encryption
7. **Error Recovery**: Limited retry mechanisms
8. **No Dependency Management**: Apps manage their own dependencies

## Future Enhancements

### Proposed Features
1. **Web Dashboard**: GUI for monitoring and updating APPS_TO_UPDATE configuration
2. **Policy Engine**: Automated update rules and schedules
3. **Rollback Capability**: Automatic reversion on failed updates
4. **Authentication**: Secure RPC and Redis communication
5. **Metrics Collection**: Prometheus integration
6. **Configuration UI**: Dynamic APPS_TO_UPDATE management
7. **Multi-tenancy**: Support for multiple environments
8. **Dependency Restoration**: Optional dependency management system

### Architecture Improvements
1. **Database Storage**: Persistent state instead of in-memory
2. **Load Balancing**: Multiple updater instances
3. **Circuit Breaker**: Fault tolerance patterns
4. **Event Sourcing**: Audit trail of all operations
5. **Microservice Split**: Separate concerns into distinct services 