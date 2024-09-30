import os
import time
import json
import logging
import threading
import signal
import sys
import requests
from commlib.transports.redis import ConnectionParameters, Subscriber
from commlib.pubsub import PubSubMessage

# Configure logging to write to the console
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)

def flush_logs():
    """Flush the console handler"""
    for handler in logging.getLogger().handlers:
        handler.flush()

class VersionMessage(PubSubMessage):
    """Message format for version updates."""
    appname: str
    version_number: str

class DockerComposeManager:
    def __init__(self, search_directory):
        self.search_directory = search_directory
        self.processed_directories = set()

    def find_docker_compose_files(self):
        """Finds all docker-compose.yml files in the search directory and its subdirectories."""
        compose_files = []
        for root, dirs, files in os.walk(self.search_directory):
            if 'docker-compose.yml' in files:
                compose_files.append(root)
        return compose_files

    def run_docker_compose(self, directory):
        """Runs 'docker compose up -d' in the specified directory."""
        logging.info(f"Running 'docker compose up -d' in {directory}")
        flush_logs()
        try:
            result = os.system(f"docker compose -f {directory}/docker-compose.yml up -d")
            if result == 0:
                logging.info(f"'docker compose up -d' succeeded in {directory}")
            else:
                logging.error(f"Error running 'docker compose up -d' in {directory}")
        except Exception as e:
            logging.error(f"Exception occurred while running 'docker compose up -d' in {directory}: {e}")
        flush_logs()

class DockerHubManager:
    def __init__(self, config):
        self.username = config.get('DOCKER_HUB_USERNAME')
        self.password = config.get('DOCKER_HUB_PASSWORD')
        self.token = None
        if not self.username or not self.password:
            logging.error("Docker Hub credentials are not set in 'config.json'.")
            sys.exit(1)
        self.obtain_token()
        self.image_versions = self.list_docker_images()

    def obtain_token(self):
        """Obtains a JWT token from Docker Hub using username and password."""
        url = "https://hub.docker.com/v2/users/login/"
        payload = {"username": self.username, "password": self.password}
        try:
            response = requests.post(url, json=payload)
            if response.status_code == 200:
                self.token = response.json().get('token')
                if self.token:
                    logging.info("Successfully obtained Docker Hub token.")
                else:
                    logging.error("Token not found in response.")
                    sys.exit(1)
            else:
                logging.error(f"Failed to get token: {response.status_code} - {response.text}")
                sys.exit(1)
        except Exception as e:
            logging.error(f"Exception during token retrieval: {e}")
            sys.exit(1)

    def list_docker_images(self):
        """Lists Docker images and their tags in the Docker Hub account."""
        image_versions = {}
        try:
            base_url = f"https://hub.docker.com/v2/repositories/{self.username}/?page_size=100"
            headers = {'Authorization': f'JWT {self.token}'}
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
    def __init__(self, docker_hub_manager):
        self.docker_hub_manager = docker_hub_manager
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

    def on_message_received(self, msg: VersionMessage):
        logging.info(f"Received message: App '{msg.appname}' is running version '{msg.version_number}'")
        self.process_version_message(msg)
        flush_logs()

    def process_version_message(self, msg):
        """Processes the received version message."""
        try:
            appname = msg.appname
            version_number = msg.version_number

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

        except Exception as e:
            logging.error(f"Error processing message: {e}")
        flush_logs()

    def listen(self):
        """Starts the subscriber to listen to the version channel."""
        self.subscriber.run()

class MainApplication:
    def __init__(self):
        self.search_directory = '/data/firmwares'
        self.docker_manager = DockerComposeManager(self.search_directory)
        self.config = self.load_config()
        self.docker_hub_manager = DockerHubManager(self.config)
        self.version_listener = VersionListener(self.docker_hub_manager)

    def load_config(self):
        """Loads configuration from config.json."""
        try:
            with open('config.json', 'r') as config_file:
                config = json.load(config_file)
            return config
        except FileNotFoundError:
            logging.error("Configuration file 'config.json' not found.")
            sys.exit(1)
        except json.JSONDecodeError as e:
            logging.error(f"Error parsing 'config.json': {e}")
            sys.exit(1)

    def setup_signal_handlers(self):
        """Set up signal handlers for graceful shutdown."""
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

    def signal_handler(self, sig, frame):
        """Handles shutdown signals."""
        logging.info('Shutdown signal received. Exiting...')
        flush_logs()
        sys.exit(0)

    def run(self):
        """Main function to check for docker-compose files and handle version updates."""
        # Start the listener in a separate thread
        listener_thread = threading.Thread(target=self.version_listener.listen, daemon=True)
        listener_thread.start()

        # Check for docker-compose.yml files only once
        logging.info(f"Checking for docker-compose.yml files in {self.search_directory}")
        compose_dirs = self.docker_manager.find_docker_compose_files()
        count = len(compose_dirs)

        if count == 0:
            logging.info("There are no docker-compose.yml files in the folder specified!")
        else:
            logging.info(f"Found {count} docker-compose.yml files.")

            # Run 'docker compose up -d' in each directory
            for dir in compose_dirs:
                if dir not in self.docker_manager.processed_directories:
                    self.docker_manager.run_docker_compose(dir)
                    self.docker_manager.processed_directories.add(dir)

        flush_logs()

        # Keep the container running
        while True:
            logging.info("Task completed. Sleeping for 1 hour.")
            flush_logs()
            time.sleep(3600)

if __name__ == "__main__":
    app = MainApplication()
    app.setup_signal_handlers()
    app.run()
