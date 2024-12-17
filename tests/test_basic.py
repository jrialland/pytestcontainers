import pytest
from pytestcontainers import using_containers, wait_for_tcp_port, async_wait_for
import requests
import os

test_index_html = os.path.join(os.path.dirname(__file__), "test_index.html")

# ------------------------------------------------------------------------------
@using_containers(
    {
        "image": "lipanski/docker-static-website:latest",
        "ports": {"2000": 3000},
        "volumes": [f"{test_index_html}:/home/static/index.html:ro"],
    }
)
def test_basic():
    wait_for_tcp_port(port=2000)
    response = requests.get("http://localhost:2000/index.html")
    assert response.status_code == 200
    assert "Can you read ?" in response.text


# ------------------------------------------------------------------------------
@pytest.mark.asyncio
@using_containers(
    {
        "image": "postgres:17-alpine",
        "name": "postgres",
        "ports": {"5432": 5432},
        "environment": {
            "POSTGRES_USER": "postgresuser",
            "POSTGRES_PASSWORD": "postgrespassword",
            "POSTGRES_DB": "postgresdb",
        },
    }
)
async def test_async():

    import asyncpg

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
