from pytestcontainers import using_containers, get_free_tcp_port, wait_for_tcp_port
import os

# locate the compose file
compose_file = os.path.join(os.path.dirname(__file__), "compose-example.yml")

# get a free tcp port
free_tcp_port = get_free_tcp_port()


# ------------------------------------------------------------------------------
@using_containers(compose_file=compose_file, compose_env={"PORT": str(free_tcp_port)})
def test_check_compose_works(stack: using_containers):
    wait_for_tcp_port(free_tcp_port)


# ------------------------------------------------------------------------------
@using_containers(
    stack_name="inline_compose_test",    
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
