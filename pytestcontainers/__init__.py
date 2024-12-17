"""
a Python module designed to simplify the use of Docker containers in pytest 
tests. It provides a context manager and decorators to manage the lifecycle
of Docker containers during testing. This allows developers to easily set up
and tear down Docker containers as part of their test suite, ensuring that 
tests run in a consistent and isolated environment. The library supports
both synchronous and asynchronous tests, making it versatile for various 
testing scenarios.
"""

__author__ = "Julien Rialland"
__version__ = "0.1.0"

import os
import asyncio
import logging
import socket
import time
import shutil
import subprocess
import inspect
import tempfile
import yaml
import docker  # type: ignore
from docker.models.containers import Container  # type: ignore

from dataclasses import dataclass
from typing import Callable, TypeVar


# ------------------------------------------------------------------------------
@dataclass
class ImageBuild:
    """
    Image build definition
    """

    context: str | None = None
    dockerfile: str | None = None
    tag: str | None = None
    buildargs: dict | None = None

    @staticmethod
    def from_dict(data: dict):
        if not data:
            return None
        return ImageBuild(
            context=data.get("context"),
            dockerfile=data.get("dockerfile"),
            tag=data.get("tag"),
            buildargs=data.get("buildargs"),
        )


# ------------------------------------------------------------------------------
@dataclass
class ContainerDefinition:
    """
    Container definition
    """

    image: str | None = None
    name: str | None = None
    ports: dict | None = None
    environment: dict | None = None
    volumes: dict | None = None
    build: ImageBuild | None = None
    working_dir: str | None = None
    user: str | int | None = None
    command: str | list[str] | None = None

    @staticmethod
    def from_dict(data: dict):
        return ContainerDefinition(
            image=data.get("image"),
            name=data.get("name"),
            ports=data.get("ports"),
            environment=data.get("environment"),
            volumes=data.get("volumes"),
            build=ImageBuild.from_dict(data.get("build")),  # type: ignore
            working_dir=data.get("working_dir"),
            user=data.get("user"),
            command=data.get("command"),
        )


# ------------------------------------------------------------------------------
class using_containers:
    """
    Context manager for running containers during tests.
    ```python
    @using_containers({
        "image": "lipanski/docker-static-website:latest",
        "ports": {"3000": 2000}
    })
    def test_basic():
        wait_for_port(port=2000)
        response = requests.get("http://localhost:2000")
        assert response.status_code == 404
    ```
    """

    def read_definitions(self, definition):
        if isinstance(definition, str):
            yield ContainerDefinition(image=definition)
        elif isinstance(definition, dict):
            yield ContainerDefinition.from_dict(definition)
        elif isinstance(definition, list) or isinstance(definition, tuple):
            for item in definition:
                yield from self.read_definitions(item)
        elif isinstance(definition, ContainerDefinition):
            yield definition
        else:
            raise ValueError(f"Invalid definition: '{definition}'")

    def __init__(self, *args, **kwargs):

        self.logger = logging.getLogger(__name__)
        self.definitions = list(self.read_definitions(args))
        self.client = docker.from_env()
        self.docker_command = kwargs.get("docker_command", shutil.which("docker"))
        self.compose_files = kwargs.get("compose_files", [])

        self._live_containers: dict[str, Container] = {}  # type: ignore
        self._cleanup_fns = []

        # check if docker is available, otherwise fallback to podman
        if self.docker_command is None:
            self.docker_command = shutil.which(
                "podman"
            )  # fallback to podman if docker is not available

        # accept a single definition as a keyword argument
        if "compose_file" in kwargs:
            self.compose_files.append(kwargs["compose_file"])

        # accept inline compose files as a keyword argument (string or dict)
        if "inline_compose" in kwargs:
            # create a temporary directory to store the inline compose file
            temp_dir = tempfile.mkdtemp()
            compose_file = os.path.join(temp_dir, "docker-compose.yml")

            with open(compose_file, "w") as f:
                if isinstance(kwargs["inline_compose"], str):
                    f.write(kwargs["inline_compose"])
                else:
                    # try to convert the object into yaml and write it to the file
                    yaml.dump(kwargs["inline_compose"], f)

            self.compose_files.append(compose_file)
            self._cleanup_fns.append(lambda: shutil.rmtree(temp_dir))

        # accept a dictionary of environment variables to pass to the compose command
        self.compose_env = kwargs.get("compose_env", {})

        # accept a flag to build images before starting compose
        self.compose_build = kwargs.get(
            "compose_build", True
        )  # build images before starting compose

        # if there are compose files do some extra checks
        if self.compose_files:

            assert (
                self.docker_command
            ), "docker_command not found. an installation of docker or podman is required to use compose files"

            # check that the compose files exist
            for compose_file in self.compose_files:
                assert os.path.isfile(
                    compose_file
                ), f"compose file not found: {compose_file}"

    def __del__(self):
        for fn in self._cleanup_fns:
            fn()

    def _start_containers(self):
        self._live_containers.clear()

        for definition in self.definitions:

            if definition.build:

                self.logger.info(f"Building image {definition.build.context}")

                self.client.images.build(
                    path=definition.build.context,
                    dockerfile=definition.build.dockerfile,
                    tag=definition.build.tag,
                    buildargs=definition.build.buildargs,
                )

            elif definition.image:

                self.logger.info(f"Pulling image {definition.image}")

                self.client.images.pull(definition.image)
            else:
                raise ValueError("Invalid definition: missing image or build")

            image = definition.image or definition.build.tag

            self.logger.info(f"Creating container {definition.name}")

            # for some reason, port definitions are reversed, so fix it
            ports = (
                {str(v): str(k) for k, v in definition.ports.items()}
                if definition.ports
                else None
            )

            container = self.client.containers.create(
                image,
                detach=True,
                auto_remove=True,
                name=definition.name,
                ports=ports,
                environment=definition.environment,
                volumes=definition.volumes,
                working_dir=definition.working_dir,
                user=definition.user,
                command=definition.command,
            )

            self._live_containers[container.name] = container

        # start all containers
        for container in self._live_containers.values():
            self.logger.info(f"Starting container {container.id}")
            container.start()

    def _stop_containers(self):
        # Stop and remove all containers that were created
        for container in self._live_containers.values():
            self.logger.info(f"Stopping container {container.id}")
            container.stop()
            self.logger.info(f"Removing container {container.id}")
            container.remove()

    def _start_compose(self):
        env = os.environ.copy()
        env.update(self.compose_env)
        # pre-build images if specified
        if self.compose_build:
            for compose_file in self.compose_files:
                self.logger.info(f"Building images for file {compose_file}")
                subprocess.check_output(
                    [
                        self.docker_command,
                        "compose",
                        "-f",
                        os.path.basename(compose_file),
                        "build",
                    ],
                    cwd=os.path.dirname(compose_file),
                    env=env,
                )

        for compose_file in self.compose_files:
            self.logger.info(f"Starting docker-compose with file {compose_file}")
            subprocess.check_output(
                [
                    self.docker_command,
                    "compose",
                    "-f",
                    os.path.basename(compose_file),
                    "up",
                    "-d",
                ],
                env=env,
                cwd=os.path.dirname(compose_file),
            )

    def _stop_compose(self):
        for compose_file in self.compose_files:
            self.logger.info(f"Stopping docker-compose with file {compose_file}")
            subprocess.check_output(
                [
                    self.docker_command,
                    "compose",
                    "-f",
                    os.path.basename(compose_file),
                    "down",
                ],
                cwd=os.path.dirname(compose_file),
            )

    def __enter__(self) -> "using_containers":
        self._start_containers()
        self._start_compose()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._stop_compose()
        self._stop_containers()

    def __call__(self, func):
        expects_param = len(inspect.signature(func).parameters) == 1
        if asyncio.iscoroutinefunction(func):

            async def async_wrapper(*args, **kwargs):
                with self:
                    if expects_param:
                        return await func(self)
                    else:
                        return await func(*args, **kwargs)

            return async_wrapper

        else:

            def wrapper(*args, **kwargs):
                with self:
                    if expects_param:
                        return func(self)
                    else:
                        return func(*args, **kwargs)

            return wrapper

    def exec(self, container: str, command: str | list[str], **kwargs) -> tuple:
        """
        Execute a command in a running container and return the output
        """
        container = self.client.containers.get(container)
        return container.exec_run(command, **kwargs)

    def run(self, image, command: str | list[str], **kwargs):
        return self.client.containers.run(image, command, **kwargs)


T = TypeVar("T")


# ------------------------------------------------------------------------------
def wait_for(
    condition: Callable[[], T], timeout=10, poll_interval=0.1, name="condition"
) -> T:
    """Wait for a condition to be true by polling a callable that returns a boolean"""
    start = time.time()
    while time.time() - start < timeout:
        try:
            if result := condition():
                return result
        except Exception:
            pass
        time.sleep(poll_interval)
    raise TimeoutError(
        f"condition '{name or str(condition)}' not met after {timeout} seconds"
    )


# ------------------------------------------------------------------------------
async def async_wait_for(
    condition: Callable[[], T],
    timeout=10,
    poll_interval=0.1,
    name="condition",
) -> T:
    """Wait for a condition to be true by polling a callable that returns a boolean"""
    start = time.time()
    while time.time() - start < timeout:
        if asyncio.iscoroutinefunction(condition):
            try:
                if result := await condition():
                    return result
            except Exception:
                pass
        else:
            try:
                if result := condition():
                    return result
            except Exception:
                pass
        await asyncio.sleep(poll_interval)
    raise TimeoutError(
        f"condition '{name or str(condition)}' not met after {timeout} seconds"
    )


# ------------------------------------------------------------------------------
def _make_tcp_condition(host, port) -> Callable[[], bool]:
    assert host, "Host must be specified"
    assert port > 0, "Port must be greater than 0"

    def condition():
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        try:
            sock.connect((host, port))
            sock.close()
            return True
        except ConnectionRefusedError:
            return False

    return condition


# ------------------------------------------------------------------------------
def wait_for_tcp_port(
    port: int = 0, host="localhost", timeout=10, poll_interval=0.1
) -> bool:
    """Wait for a port to be open on a host"""
    return wait_for(
        _make_tcp_condition(host, port), timeout, poll_interval, f"tcp {host}:{port}"
    )


# ------------------------------------------------------------------------------
async def async_wait_for_tcp_port(
    port: int = 0, host="localhost", timeout=10, poll_interval=0.1
) -> bool:
    """Wait for a port to be open on a host"""
    return await async_wait_for(
        _make_tcp_condition(host, port), timeout, poll_interval, f"tcp {host}:{port}"
    )


# ------------------------------------------------------------------------------
def get_free_tcp_port(host="localhost") -> int:
    """
    Get a free TCP port
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


__all__ = [
    "using_containers",
    "wait_for",
    "async_wait_for",
    "wait_for_tcp_port",
    "async_wait_for_tcp_port",
    "get_free_tcp_port",
]
