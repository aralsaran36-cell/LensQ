from backend.services.model_service import model_service


def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["model_loaded"] is True
    assert body["app"] == "LensQ"


def test_health_degraded_when_model_not_loaded(client):
    model_service.unload()
    body = client.get("/health").json()
    assert body["status"] == "degraded"
    assert body["model_loaded"] is False


def test_responses_are_not_cached(client):
    assert client.get("/health").headers["cache-control"] == "no-store"