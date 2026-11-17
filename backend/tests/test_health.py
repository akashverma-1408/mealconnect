"""Health endpoints and the global error format."""


def test_liveness(client):
    res = client.get("/api/v1/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_readiness_checks_database_and_redis(client):
    res = client.get("/api/v1/health/ready")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "checks": {"database": "ok", "redis": "ok"}}


def test_every_response_has_request_id_header(client):
    res = client.get("/api/v1/health")
    assert len(res.headers["x-request-id"]) == 32


def test_incoming_request_id_is_reused(client):
    res = client.get("/api/v1/health", headers={"X-Request-ID": "trace-abc-123"})
    assert res.headers["x-request-id"] == "trace-abc-123"


def test_unknown_route_uses_standard_error_format(client):
    res = client.get("/api/v1/does-not-exist")
    assert res.status_code == 404
    error = res.json()["error"]
    assert error["code"] == "NOT_FOUND"
    assert error["request_id"] == res.headers["x-request-id"]


def test_wrong_method_returns_405(client):
    res = client.delete("/api/v1/health")
    assert res.status_code == 405
    assert res.json()["error"]["code"] == "METHOD_NOT_ALLOWED"
