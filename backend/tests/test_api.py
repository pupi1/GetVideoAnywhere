from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ai_summary() -> None:
    response = client.post("/ai/summarize", json={"text": "This is a test transcript text for summary."})
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert "summary" in payload["data"]


def test_create_batch_download_invalid_url() -> None:
    response = client.post(
        "/download/batch",
        json={"urls": ["https://example.com/video1", "not-an-url"], "format_id": "best"},
    )
    assert response.status_code == 422
