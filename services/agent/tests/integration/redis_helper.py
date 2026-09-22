"""Real Redis for integration tests — Testcontainers only (unlike PostgreSQL, this repo has no
established `TEST_REDIS_URL`-inside-compose convention to mirror, so there is only the one path).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest

from tests.integration.database import docker_available

requires_docker = pytest.mark.skipif(
    not docker_available(), reason="Docker is required for a real Redis"
)


@contextmanager
def provision_redis() -> Iterator[str]:
    from testcontainers.redis import RedisContainer

    with RedisContainer() as container:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(6379)
        yield f"redis://{host}:{port}/0"
