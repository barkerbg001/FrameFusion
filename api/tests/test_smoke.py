from app.main import app
from fastapi.testclient import TestClient


def test_openapi_schema() -> None:
    client = TestClient(app)
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["title"] == "FastAPI"
