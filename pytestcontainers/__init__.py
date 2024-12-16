"""
a Python module designed to simplify the use of Docker containers in pytest 
tests. It provides a context manager and decorators to manage the lifecycle
of Docker containers during testing. This allows developers to easily set up
and tear down Docker containers as part of their test suite, ensuring that 
tests run in a consistent and isolated environment. The library supports
both synchronous and asynchronous tests, making it versatile for various 
testing scenarios.
"""

import docker  # type: ignore
from docker.models.containers import Container  # type: ignore
import asyncio
import logging
import socket
import time
from dataclasses import dataclass

from typing import Callable, Awaitable, TypeVar


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

    def __init__(self, *args):
        self.logger = logging.getLogger(__name__)
        self.definitions = list(self.read_definitions(args))
        self.containers: set[Container] = set()  # type: ignore

    def __enter__(self):
        self.containers.clear()
        client = docker.from_env()

        for definition in self.definitions:

            if definition.build:

                self.logger.info(f"Building image {definition.build.context}")

                client.images.build(
                    path=definition.build.context,
                    dockerfile=definition.build.dockerfile,
                    tag=definition.build.tag,
                    buildargs=definition.build.buildargs,
                )

            elif definition.image:

                self.logger.info(f"Pulling image {definition.image}")

                client.images.pull(definition.image)
            else:
                raise ValueError("Invalid definition: missing image or build")

            image = definition.image or definition.build.tag

            self.logger.info(f"Creating container {definition.name}")

            container = client.containers.create(
                image,
                detach=True,
                auto_remove=True,
                name=definition.name,
                ports=definition.ports,
                environment=definition.environment,
                volumes=definition.volumes,
                working_dir=definition.working_dir,
                user=definition.user,
                command=definition.command,
            )

            self.containers.add(container)

        # start all containers
        for container in self.containers:
            self.logger.info(f"Starting container {container.id}")
            container.start()

    def __exit__(self, exc_type, exc_val, exc_tb):

        # Stop and remove all containers that were created
        for container in self.containers:
            self.logger.info(f"Stopping container {container.id}")
            container.stop()
            self.logger.info(f"Removing container {container.id}")
            container.remove()

    def __call__(self, func):

        if asyncio.iscoroutinefunction(func):

            async def async_wrapper(*args, **kwargs):
                with self:
                    return await func(*args, **kwargs)

            return async_wrapper

        else:

            def wrapper(*args, **kwargs):
                with self:
                    return func(*args, **kwargs)

            return wrapper


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
    host="localhost", port: int = 0, timeout=10, poll_interval=0.1
) -> bool:
    """Wait for a port to be open on a host"""
    return wait_for(
        _make_tcp_condition(host, port), timeout, poll_interval, f"tcp {host}:{port}"
    )


# ------------------------------------------------------------------------------
async def async_wait_for_tcp_port(
    host="localhost", port: int = 0, timeout=10, poll_interval=0.1
) -> bool:
    """Wait for a port to be open on a host"""
    return await async_wait_for(
        _make_tcp_condition(host, port), timeout, poll_interval, f"tcp {host}:{port}"
    )
