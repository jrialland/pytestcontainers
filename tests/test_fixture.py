import pytest
from pytestcontainers import using_containers

@pytest.fixture(scope="module") # Possible values for scope are: function, class, module, package or session
def stack():
    with using_containers({
        "image": "alpine:latest",
        "name": "mycontainer",
        "command": "tail -f /dev/null",
    }) as stack:
        yield stack 

def test_itworks(stack):
    exit_code, output = stack.exec("mycontainer", "echo Hello, world!")
    assert exit_code == 0
    assert output == b"Hello, world!\n"