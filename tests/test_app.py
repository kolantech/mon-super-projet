import os
import tempfile

test_database = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
test_database.close()
os.environ["EDUTOGO_DATABASE"] = test_database.name

from fastapi.testclient import TestClient

from app import app, seed_database


def setup_module():
    seed_database()


def test_health_and_catalog():
    with TestClient(app) as client:
        assert client.get("/health").json()["status"] == "ok"
        catalog = client.get("/catalog")
        assert catalog.status_code == 200
        assert catalog.json()[0]["title"] == "Comprendre les fractions"


def test_student_can_complete_lesson_and_submit_quiz():
    with TestClient(app) as client:
        registration = client.post("/auth/register", json={"name": "Afi Mensah", "email": "afi@example.com", "password": "secret123"})
        assert registration.status_code == 201
        login = client.post("/auth/login", json={"email": "afi@example.com", "password": "secret123"})
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        lesson = client.get("/lessons/1").json()
        question_id = lesson["questions"][0]["id"]
        result = client.post(f"/lessons/{lesson['lesson']['id']}/quiz", headers=headers, json={"answers": {str(question_id): "4/5"}})
        assert result.status_code == 200
        assert result.json()["score"] == 100
        assert client.get("/progress", headers=headers).json()["completed_lessons"] == 1