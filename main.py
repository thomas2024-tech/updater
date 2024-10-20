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

# Configure logging to write to the console with a specific format
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)

def flush_logs():
    """
    Flushes the console handler to ensure all logging messages are outputted promptly.
    This can be useful in environments where the output is buffered.
    """
    for handler in logging.getLogger().handlers:
        handler.flush()

# Define a message class for publishing version updates
class VersionMessage(PubSubMessage):
    """
    Message format for version updates in the publish-subscribe system.
    Attributes:
        appname (str): Name of the application sending the version update.
        version_number (str): The current version number of the application.
        dependencies (dict): A dictionary of dependencies with their required versions.
    """
    appname: str
    version_number: str
    dependencies: dict  # To store dependent apps and their versions

# Define RPC message classes for Docker commands
class DockerCommandRequest(RPCMessage):
    """
    RPC message for requesting Docker commands to be executed.
    Attributes:
        command (str): The command to execute (e.g., 'down', 'update_version').
        directory (str): The directory where the Docker command should be executed.
        new_version (str, optional): The new version to update to, if applicable.
    """
    command: str
    directory: str
    new_version: str = None

class DockerCommandResponse(RPCMessage):
    """
    RPC response message after executing a Docker command.
    Attributes:
        success (bool): Indicates if the command was executed successfully.
        message (str): Additional information or error message.
    """
    success: bool
    message: str

class RPCDockerManager:
    """
    Manages RPC clients for sending Docker commands to different applications.
    Initializes RPC clients for each application and provides methods to update app versions.
    """
    def __init__(self):
        # Retrieve Redis connection parameters from environment variables or use defaults
        redis_host = os.getenv('REDIS_HOST', 'localhost')
        redis_port = int(os.getenv('REDIS_PORT', 6379))
        redis_db = int(os.getenv('REDIS_DB', 0))

        # Set up connection parameters for Redis
        self.conn_params = ConnectionParameters(
            host=redis_host,
            port=redis_port,
            db=redis_db
        )

        # Initialize a Node for RPC communication
        self.node = Node(node_name='updater_node', connection_params=self.conn_params)

        # Start the node's event loop in a separate thread to handle asynchronous communication
        self.node.run_threaded()

        # Map application names to their respective RPC clients
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
        """
        Sends an RPC command to update the application's version.
        Args:
            appname (str): Name of the application to update.
            directory (str): Directory where the Docker command should be executed.
            new_version (str): The new version to update the application to.
        """
        # Retrieve the RPC client for the specified application
        rpc_client = self.app_to_rpc_client.get(appname)
        if not rpc_client:
            logging.error(f"No RPC client found for app '{appname}'")
            return

        # Create a request message with the command details
        request = DockerCommandRequest(
            command='update_version',
            directory=directory,
            new_version=new_version
        )
        try:
            # Send the RPC request and wait for the response
            response = rpc_client.call(request)
            if response.success:
                logging.info(f"Successfully updated {appname} to version {new_version}")
            else:
                logging.error(f"Failed to update {appname}: {response.message}")
        except Exception as e:
            logging.error(f"Exception while updating {appname}: {e}")

class DockerHubManager:
    """
    Manages interactions with Docker Hub to retrieve available images and their tags.
    Uses Docker Hub API to list repositories and their versions.
    """
    def __init__(self):
        # Retrieve Docker Hub credentials from environment variables
        self.username = os.getenv('DOCKER_HUB_USERNAME')
        self.token = os.getenv('DOCKER_HUB_TOKEN')
        if not self.username or not self.token:
            logging.error("Docker Hub credentials are not set in environment variables.")
            sys.exit(1)

        # Fetch the list of images and their available versions
        self.image_versions = self.list_docker_images()

    def list_docker_images(self):
        """
        Retrieves a list of Docker images and their tags from the Docker Hub account.
        Returns:
            dict: A dictionary mapping image names to a list of their tags.
        """
        image_versions = {}
        try:
            # Base URL for Docker Hub API to list repositories
            base_url = f"https://hub.docker.com/v2/repositories/{self.username}/?page_size=100"

            # Set up headers with the authentication token
            headers = {'Authorization': f'Bearer {self.token}'}
            logging.info(f"Listing images and tags for Docker Hub account '{self.username}':")

            url = base_url
            while url:
                # Make a GET request to retrieve repositories
                response = requests.get(url, headers=headers)
                if response.status_code == 200:
                    data = response.json()
                    repositories = data.get('results', [])

                    for repo in repositories:
                        repo_name = repo['name']
                        image_versions[repo_name] = []

                        # Fetch tags for each repository
                        tags_url = f"https://hub.docker.com/v2/repositories/{self.username}/{repo_name}/tags?page_size=100"
                        while tags_url:
                            # Make a GET request to retrieve tags
                            tags_response = requests.get(tags_url, headers=headers)
                            if tags_response.status_code == 200:
                                tags_data = tags_response.json()
                                tags = tags_data.get('results', [])

                                for tag in tags:
                                    tag_name = tag['name']
                                    # Store the tag in the image_versions dictionary
                                    image_versions[repo_name].append(tag_name)
                                    # Log the image and tag
                                    logging.info(f"{repo_name}:{tag_name}")

                                # Get the URL for the next page of tags, if any
                                tags_url = tags_data.get('next')
                            else:
                                logging.error(f"Failed to retrieve tags for repository '{repo_name}': {tags_response.status_code} - {tags_response.text}")
                                break

                    # Get the URL for the next page of repositories, if any
                    url = data.get('next')
                else:
                    logging.error(f"Failed to retrieve repositories: {response.status_code} - {response.text}")
                    break
        except Exception as e:
            logging.error(f"Exception in list_docker_images: {e}")

        return image_versions

class VersionListener:
    """
    Listens for version update messages on a Redis pub-sub channel and processes them.
    Compares running versions with available versions and handles dependencies.
    """
    def __init__(self, docker_hub_manager, rpc_manager):
        self.docker_hub_manager = docker_hub_manager  # Manages Docker Hub interactions
        self.rpc_manager = rpc_manager  # Manages RPC communications

        # Retrieve Redis connection parameters from environment variables or use defaults
        redis_host = os.getenv('REDIS_HOST', 'localhost')
        redis_port = int(os.getenv('REDIS_PORT', 6379))
        redis_db = int(os.getenv('REDIS_DB', 0))

        # Set up connection parameters for Redis
        self.conn_params = ConnectionParameters(
            host=redis_host,
            port=redis_port,
            db=redis_db
        )

        # Initialize a subscriber to listen to the 'version_channel' topic
        self.subscriber = Subscriber(
            conn_params=self.conn_params,
            topic='version_channel',
            msg_type=VersionMessage,
            on_message=self.on_message_received
        )

        self.current_versions = {}  # Stores the current versions of apps

        # Read app-to-directory mapping from environment variable
        app_to_directory_str = os.getenv('APP_TO_DIRECTORY')
        if app_to_directory_str:
            try:
                # Parse the JSON string into a dictionary
                self.app_to_directory = json.loads(app_to_directory_str)
            except json.JSONDecodeError as e:
                logging.error(f"Error parsing APP_TO_DIRECTORY environment variable: {e}")
                sys.exit(1)
        else:
            logging.error("APP_TO_DIRECTORY environment variable is not set.")
            sys.exit(1)

        self._stop_event = threading.Event()  # Event to signal the listener to stop

    def on_message_received(self, msg: VersionMessage):
        """
        Callback function that is called when a new message is received on the 'version_channel'.
        Args:
            msg (VersionMessage): The received version message.
        """
        logging.info(f"Received message: App '{msg.appname}' is running version '{msg.version_number}'")
        # Update the current version of the app
        self.current_versions[msg.appname] = msg.version_number
        # Process the received message
        self.process_version_message(msg)
        flush_logs()

    def version_compare(self, v1, v2):
        """
        Compares two version strings.
        Args:
            v1 (str): The first version string.
            v2 (str): The second version string.
        Returns:
            int: 1 if v1 > v2, 0 if v1 == v2, -1 if v1 < v2
        """
        v1_parsed = parse_version(v1)
        v2_parsed = parse_version(v2)
        if v1_parsed > v2_parsed:
            return 1
        elif v1_parsed == v2_parsed:
            return 0
        else:
            return -1

    def process_version_message(self, msg):
        """
        Processes the received version message by checking if updates are needed.
        Args:
            msg (VersionMessage): The version message to process.
        """
        try:
            appname = msg.appname
            version_number = msg.version_number
            dependencies = msg.dependencies  # Get the app's dependencies

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

            # Check dependencies to see if they need updates
            for dep_appname, dep_version_required in dependencies.items():
                # Get the current version of the dependency
                dep_version_running = self.current_versions.get(dep_appname)
                if dep_version_running is None:
                    logging.warning(f"No version information for dependency '{dep_appname}'")
                    continue

                # Compare the running version with the required version
                compare_result = self.version_compare(dep_version_running, dep_version_required)
                if compare_result >= 0:
                    logging.info(f"Dependency '{dep_appname}' is at version '{dep_version_running}', which satisfies the required version '{dep_version_required}'.")
                else:
                    logging.warning(f"Dependency '{dep_appname}' is at version '{dep_version_running}', which does not satisfy the required version '{dep_version_required}'.")
                    # Send an RPC command to update the dependency
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
        """
        Starts the subscriber to listen to the 'version_channel' for incoming messages.
        Runs in a loop until a stop event is set.
        """
        try:
            self.subscriber.run()
            while not self._stop_event.is_set():
                time.sleep(0.1)  # Sleep briefly to avoid busy waiting
        except Exception as e:
            logging.error(f"Exception in listener thread: {e}")

    def stop(self):
        """
        Signals the listener to stop listening for messages and shuts down the subscriber.
        """
        self._stop_event.set()
        self.subscriber.stop()

class MainApplication:
    """
    The main application that initializes all components and starts the version listener.
    Handles graceful shutdown on receiving termination signals.
    """
    def __init__(self):
        # Initialize the DockerHubManager to interact with Docker Hub
        self.docker_hub_manager = DockerHubManager()
        # Initialize the RPCDockerManager to handle RPC communications
        self.rpc_manager = RPCDockerManager()
        # Initialize the VersionListener to listen for version updates
        self.version_listener = VersionListener(self.docker_hub_manager, self.rpc_manager)

    def setup_signal_handlers(self):
        """
        Sets up signal handlers to gracefully handle shutdown signals like SIGINT and SIGTERM.
        """
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

    def signal_handler(self, sig, frame):
        """
        Handles shutdown signals by stopping the version listener and exiting the application.
        Args:
            sig: The signal number.
            frame: The current stack frame.
        """
        logging.info('Shutdown signal received. Exiting...')
        self.version_listener.stop()
        flush_logs()
        sys.exit(0)

    def run(self):
        """
        Starts the version listener in a separate thread and keeps the application running.
        """
        # Start the listener thread
        listener_thread = threading.Thread(target=self.version_listener.listen, daemon=True)
        listener_thread.start()

        flush_logs()

        # Keep the application running indefinitely
        try:
            while True:
                time.sleep(1)
                # Check if the listener thread is still alive
                if not listener_thread.is_alive():
                    logging.error("Listener thread has stopped unexpectedly. Exiting...")
                    break
        except KeyboardInterrupt:
            logging.info("KeyboardInterrupt received. Exiting...")
        finally:
            # Ensure the listener is stopped and the thread is joined before exiting
            self.version_listener.stop()
            listener_thread.join()

if __name__ == "__main__":
    # Entry point of the application
    app = MainApplication()
    app.setup_signal_handlers()
    app.run()
