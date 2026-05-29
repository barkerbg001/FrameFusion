def test_health_returns_ok(client):
    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert "uploads" in payload["paths"]
    assert "output" in payload["paths"]
