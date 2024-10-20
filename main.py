import os
import time
import json
import logging
import threading
import signal
import sys
import requests
from commlib.node import Node
from commlib.transports.redis import ConnectionParameters, Subscriber
from commlib.pubsub import PubSubMessage
from commlib.rpc import RPCClient, RPCMessage
from packaging.version import parse as parse_version

# Configure logging to write to the console
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)

def flush_logs():
    """Flush the console handler."""
    for handler in logging.getLogger().handlers:
        handler.flush()

# Update the VersionMessage class to include dependencies
class VersionMessage(PubSubMessage):
    """Message format for version updates."""
    appname: str
    version_number: str
    dependencies: dict  # New field to store dependent apps and their versions

# Define RPC message classes
class DockerCommandRequest(RPCMessage):
    """RPC message for docker command requests."""
    command: str  # e.g., 'down', 'update_version'
    directory: str
    new_version: str = None  # Optional, needed for 'update_version' command

class DockerCommandResponse(RPCMessage):
    """RPC response for docker command execution."""
    success: bool
    message: str

class RPCDockerManager:
    def __init__(self):
        redis_host = os.getenv('REDIS_HOST', 'localhost')
        redis_port = int(os.getenv('REDIS_PORT', 6379))
        redis_db = int(os.getenv('REDIS_DB', 0))
        self.conn_params = ConnectionParameters(
            host=redis_host,
            port=redis_port,
            db=redis_db
        )
        # Initialize the Node
        self.node = Node(node_name='updater_node', connection_params=self.conn_params)
        # Start the node's event loop in a separate thread
        self.node.run_threaded()

        # Map app names to RPC clients
        self.app_to_rpc_client = {
            'app1': RPCClient(
                node=self.node,
                rpc_name='docker_compose_service_machine1',
                msg_type=DockerCommandRequest,
                resp_type=DockerCommandResponse
            ),
            'app2': RPCClient(
                node=self.node,
                rpc_name='docker_compose_service_machine2',
                msg_type=DockerCommandRequest,
                resp_type=DockerCommandResponse
            ),
            'app3': RPCClient(
                node=self.node,
                rpc_name='docker_compose_service_machine3',
                msg_type=DockerCommandRequest,
                resp_type=DockerCommandResponse
            ),
        }

    def update_app_version(self, appname, directory, new_version):
        rpc_client = self.app_to_rpc_client.get(appname)
        if not rpc_client:
            logging.error(f"No RPC client found for app '{appname}'")
            return

        request = DockerCommandRequest(
            command='update_version',
            directory=directory,
            new_version=new_version
        )
        try:
            response = rpc_client.call(request)
            if response.success:
                logging.info(f"Successfully updated {appname} to version {new_version}")
            else:
                logging.error(f"Failed to update {appname}: {response.message}")
        except Exception as e:
            logging.error(f"Exception while updating {appname}: {e}")

class DockerHubManager:
    def __init__(self):
        self.username = os.getenv('DOCKER_HUB_USERNAME')
        self.token = os.getenv('DOCKER_HUB_TOKEN')
        if not self.username or not self.token:
            logging.error("Docker Hub credentials are not set in environment variables.")
            sys.exit(1)
        self.image_versions = self.list_docker_images()

    def list_docker_images(self):
        """Lists Docker images and their tags in the Docker Hub account."""
        image_versions = {}
        try:
            base_url = f"https://hub.docker.com/v2/repositories/{self.username}/?page_size=100"
            headers = {'Authorization': f'Bearer {self.token}'}
            logging.info(f"Listing images and tags for Docker Hub account '{self.username}':")

            url = base_url
            while url:
                response = requests.get(url, headers=headers)
                if response.status_code == 200:
                    data = response.json()
                    repositories = data.get('results', [])

                    for repo in repositories:
                        repo_name = repo['name']
                        image_versions[repo_name] = []

                        # Fetch tags for the repository
                        tags_url = f"https://hub.docker.com/v2/repositories/{self.username}/{repo_name}/tags?page_size=100"
                        while tags_url:
                            tags_response = requests.get(tags_url, headers=headers)
                            if tags_response.status_code == 200:
                                tags_data = tags_response.json()
                                tags = tags_data.get('results', [])

                                for tag in tags:
                                    tag_name = tag['name']
                                    # Store the tag
                                    image_versions[repo_name].append(tag_name)
                                    # Output in the desired format
                                    logging.info(f"{repo_name}:{tag_name}")

                                # Get the next page of tags
                                tags_url = tags_data.get('next')
                            else:
                                logging.error(f"Failed to retrieve tags for repository '{repo_name}': {tags_response.status_code} - {tags_response.text}")
                                break

                    # Get the next page of repositories
                    url = data.get('next')
                else:
                    logging.error(f"Failed to retrieve repositories: {response.status_code} - {response.text}")
                    break
        except Exception as e:
            logging.error(f"Exception in list_docker_images: {e}")

        return image_versions

class VersionListener:
    def __init__(self, docker_hub_manager, rpc_manager):
        self.docker_hub_manager = docker_hub_manager
        self.rpc_manager = rpc_manager
        redis_host = os.getenv('REDIS_HOST', 'localhost')
        redis_port = int(os.getenv('REDIS_PORT', 6379))
        redis_db = int(os.getenv('REDIS_DB', 0))

        self.conn_params = ConnectionParameters(
            host=redis_host,
            port=redis_port,
            db=redis_db
        )

        self.subscriber = Subscriber(
            conn_params=self.conn_params,
            topic='version_channel',
            msg_type=VersionMessage,
            on_message=self.on_message_received
        )

        self.current_versions = {}  # Store current versions of apps

        # Read app-to-directory mapping from environment variable
        app_to_directory_str = os.getenv('APP_TO_DIRECTORY')
        if app_to_directory_str:
            try:
                self.app_to_directory = json.loads(app_to_directory_str)
            except json.JSONDecodeError as e:
                logging.error(f"Error parsing APP_TO_DIRECTORY environment variable: {e}")
                sys.exit(1)
        else:
            logging.error("APP_TO_DIRECTORY environment variable is not set.")
            sys.exit(1)

        self._stop_event = threading.Event()

    def on_message_received(self, msg: VersionMessage):
        logging.info(f"Received message: App '{msg.appname}' is running version '{msg.version_number}'")
        # Update current versions
        self.current_versions[msg.appname] = msg.version_number
        self.process_version_message(msg)
        flush_logs()

    def version_compare(self, v1, v2):
        """Compare version strings."""
        v1_parsed = parse_version(v1)
        v2_parsed = parse_version(v2)
        if v1_parsed > v2_parsed:
            return 1
        elif v1_parsed == v2_parsed:
            return 0
        else:
            return -1

    def process_version_message(self, msg):
        """Processes the received version message."""
        try:
            appname = msg.appname
            version_number = msg.version_number
            dependencies = msg.dependencies  # Get dependencies

            # Check if the app exists in Docker Hub
            if appname in self.docker_hub_manager.image_versions:
                available_versions = self.docker_hub_manager.image_versions[appname]
                if version_number in available_versions:
                    logging.info(f"App '{appname}' is running version '{version_number}', which is available on Docker Hub.")
                else:
                    logging.warning(f"App '{appname}' is running version '{version_number}', which is not found on Docker Hub.")
                    logging.info(f"Available versions for '{appname}': {', '.join(available_versions)}")
            else:
                logging.error(f"App '{appname}' not found in Docker Hub repositories.")

            # Now check the dependencies
            for dep_appname, dep_version_required in dependencies.items():
                dep_version_running = self.current_versions.get(dep_appname)
                if dep_version_running is None:
                    logging.warning(f"No version information for dependency '{dep_appname}'")
                    continue

                compare_result = self.version_compare(dep_version_running, dep_version_required)
                if compare_result >= 0:
                    logging.info(f"Dependency '{dep_appname}' is at version '{dep_version_running}', which satisfies the required version '{dep_version_required}'.")
                else:
                    logging.warning(f"Dependency '{dep_appname}' is at version '{dep_version_running}', which does not satisfy the required version '{dep_version_required}'.")
                    # Send RPC command to update the dependency
                    directory = self.app_to_directory.get(dep_appname)
                    if directory:
                        logging.info(f"Sending update command to app '{dep_appname}' to update to version '{dep_version_required}'")
                        self.rpc_manager.update_app_version(dep_appname, directory, dep_version_required)
                    else:
                        logging.error(f"No directory information for app '{dep_appname}'")
        except Exception as e:
            logging.error(f"Error processing message: {e}")
        flush_logs()

    def listen(self):
        """Starts the subscriber to listen to the version channel."""
        try:
            self.subscriber.run()
            while not self._stop_event.is_set():
                time.sleep(0.1)
        except Exception as e:
            logging.error(f"Exception in listener thread: {e}")

    def stop(self):
        """Stops the listener."""
        self._stop_event.set()
        self.subscriber.stop()

class MainApplication:
    def __init__(self):
        self.docker_hub_manager = DockerHubManager()
        self.rpc_manager = RPCDockerManager()
        self.version_listener = VersionListener(self.docker_hub_manager, self.rpc_manager)

    def setup_signal_handlers(self):
        """Set up signal handlers for graceful shutdown."""
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

    def signal_handler(self, sig, frame):
        """Handles shutdown signals."""
        logging.info('Shutdown signal received. Exiting...')
        self.version_listener.stop()
        flush_logs()
        sys.exit(0)

    def run(self):
        """Main function to handle version updates and RPC functionality."""
        # Start the listener in a separate thread
        listener_thread = threading.Thread(target=self.version_listener.listen, daemon=True)
        listener_thread.start()

        flush_logs()

        # Keep the application running
        try:
            while True:
                time.sleep(1)
                if not listener_thread.is_alive():
                    logging.error("Listener thread has stopped unexpectedly. Exiting...")
                    break
        except KeyboardInterrupt:
            logging.info("KeyboardInterrupt received. Exiting...")
        finally:
            self.version_listener.stop()
            listener_thread.join()

if __name__ == "__main__":
    app = MainApplication()
    app.setup_signal_handlers()
    app.run()
