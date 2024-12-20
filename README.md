# pytestcontainers

`pytestcontainers` is a Python library that makes it easy to use Docker containers in your pytest tests. It provides a context manager and decorators to manage the lifecycle of Docker containers during testing.

## Installation

To install `pytestcontainers`, use `poetry`:

```sh
poetry add pytestcontainers
```

## Usage

### Basic Usage

You can use the @using_containers decorator to run a Docker container during your test:

```python
import pytest
from pytestcontainers import using_containers, wait_for_tcp_port
import requests

@using_containers({
    "image": "lipanski/docker-static-website:latest",
    "ports": {"2000": 3000}
})
def test_basic():
    wait_for_tcp_port(port=2000)
    response = requests.get("http://localhost:2000")
    assert response.status_code == 404
```

## Use the same containers across multiple tests

You may use pytest fixtures :

```python
import pytest
from pytestcontainers import using_containers

@pytest.fixture(scope="module") # Possible values for scope are: function, class, module, package or session
def mystack():
    with using_containers({
        "image": "alpine:latest",
        "name": "mycontainer",
        "command": "tail -f /dev/null", # to keep it alive
    }) as stack:
        yield stack 

def test_itworks(mystack):
    exit_code, output = mystack.exec("mycontainer", "echo Hello, world!")
    assert exit_code == 0
    assert output == b"Hello, world!\n"

...

```

This example shows how to separate the declaration of the stack, and its use in various tests. 

### Asynchronous Tests

`pytestcontainers` also supports asynchronous tests with the @using_containers decorator:


```python
import pytest
from pytestcontainers import using_containers, async_wait_for
import asyncpg

@pytest.mark.asyncio
@using_containers(
    {
        "image": "postgres:17-alpine",
        "name": "postgres",
        "ports": {"5432/tcp": 5432},
        "environment": {
            "POSTGRES_USER": "postgresuser",
            "POSTGRES_PASSWORD": "postgrespassword",
            "POSTGRES_DB": "postgresdb",
        },
    }
)
async def test_async():
    async def connect() -> asyncpg.Connection:
        return await asyncpg.connect(
            user="postgresuser",
            password="postgrespassword",
            database="postgresdb",
            host="localhost",
            port=5432,
        )
    conn = await async_wait_for(connect, timeout=10)
    assert conn.is_closed() is False
    await conn.close()
```

In the above example, the `@using_containers` decorator is used to run a PostgreSQL container during the test. The `async_wait_for` function is used to wait for the PostgreSQL server to be ready before running the test. Then we check that we can open a connection using the asyncpg library.

### using compose files / inline compose
* You may describe the stack in a compose file. In this case the library does not interact with docker API directly, but runs the compose command instead.


```python
@using_containers(compose_file="docker-compose.yml", compose_env={"PORT": "21356"})
def test_using_compose(stack):
    wait_for_tcp_port(free_tcp_port)
```

* The content of a compose file may be passed directly, in this case a temporary yaml file is created before running the stack :

```python
@using_containers(
    inline_compose={
        "services": {
            "web": {
                "image": "nginx:latest",
                "ports": [f"{free_tcp_port}:80"],
            },
        },
    }
)
def test_check_inline_compose_works(stack: using_containers):
    wait_for_tcp_port(free_tcp_port)
```

## API

* `using_containers`

A context manager and decorator for running Docker containers during tests.

### Parameters

- `definition` (std, dict, tuple, or `ContainerDefinition`): The container definition(s)

* `wait_for_tcp_port`

Wait for a TCP port to be open on a host.

### Parameters

- `host` (str): The host to check. Default is "localhost".
- `port` (int): The port to check. Default is 0.
- `timeout` (int): The timeout in seconds. Default is 10.
- `poll_interval` (float): The polling interval in seconds. Default is 0.1.

* `async_wait_for_port`

Asynchronously wait for a TCP port to be open on a host.

### Parameters

- `host` (str): The host to check. Default is "localhost".
- `port` (int): The port to check. Default is 0.
- `timeout` (int): The timeout in seconds. Default is 10.
- `poll_interval` (float): The polling interval in seconds. Default is 0.1.

## License

This project is licensed under the MIT License.