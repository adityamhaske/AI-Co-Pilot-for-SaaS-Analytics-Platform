"""Liveness and readiness.

Probes and load balancers act on the status code, not the body. `/ready` returned 200
with `"status": "degraded"` when the database was down, so an instance that could not
serve a single query stayed in rotation — the one thing readiness exists to prevent.
"""

import pytest
from sqlalchemy.exc import OperationalError


class _UnreachableEngine:
    """Stands in for an engine whose database has gone away."""

    def connect(self):
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))


@pytest.fixture
def database_down(monkeypatch):
    monkeypatch.setattr("app.main.engine", _UnreachableEngine())


def test_ready_is_200_when_the_database_answers(client):
    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "ok"}


def test_ready_is_503_when_the_database_is_unreachable(client, database_down):
    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "database": "unreachable"}


def test_ready_does_not_leak_the_database_error(client, database_down):
    # The exception text can carry hostnames, ports and driver detail. It is logged,
    # never returned: /ready is unauthenticated.
    assert "connection refused" not in client.get("/ready").text


def test_health_stays_200_when_the_database_is_unreachable(client, database_down):
    # Liveness must not depend on the database, or a blip makes the orchestrator
    # restart a healthy process instead of draining it.
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
