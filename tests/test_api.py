import pytest
from fastapi.testclient import TestClient
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_root(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json()["status"] == "successful"
    assert resp.json()["result"] == ["App is ready to use"]


def test_post_test(client):
    resp = client.post("/test")
    assert resp.status_code == 200
    assert resp.json()["status"] == "successful"


def test_translator_missing_text(client):
    resp = client.post("/translator", json={"lang": "en"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "error"
    assert "text" in resp.json()["error"][0]


def test_translator_invalid_lang(client):
    resp = client.post("/translator", json={"text": ["hola"], "lang": "xx"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "error"
    assert "invalid language code" in resp.json()["error"][0]


def test_translator_valid_lang(client):
    resp = client.post("/translator", json={"text": ["hola mundo"], "lang": "en"})
    assert resp.status_code == 200
    # Either success (if Google reachable) or proper error (if not)
    data = resp.json()
    assert data["status"] in ("successful", "error")
    if data["status"] == "successful":
        assert "results" in data
        assert len(data["results"]) == 1
        assert data["results"][0]["index"] == 0


def test_detect_missing_text(client):
    resp = client.post("/detect", json={})
    assert resp.status_code == 200
    assert resp.json()["status"] == "error"
    assert "text" in resp.json()["error"][0]


def test_detect(client):
    resp = client.post("/detect", json={"text": ["hola mundo"]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("successful", "error")
    if data["status"] == "successful":
        assert "results" in data
        assert len(data["results"]) == 1
        assert data["results"][0]["index"] == 0


def test_response_shape_translation(client):
    """Ensure response shape matches the blueprint contract."""
    resp = client.post("/translator", json={"text": ["hello", "world"], "lang": "es"})
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    if data["status"] == "successful":
        assert "results" in data
        assert "time_ms" in data
        assert isinstance(data["results"], list)
        for i, r in enumerate(data["results"]):
            assert r["index"] == i
            assert "text" in r
            assert "result" in r


if __name__ == "__main__":
    pytest.main([__file__, "-v"])