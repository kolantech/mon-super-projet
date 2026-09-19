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
        assert any(course["title"] == "Comprendre les fractions" for course in catalog.json())
        assert len(catalog.json()) >= 6
        assert {subject["name"] for subject in client.get("/subjects").json()} >= {"Mathematiques", "Francais", "Sciences"}
        grade_names = {grade["name"] for grade in client.get("/grades").json()}
        assert {"CM1", "CM2", "6e", "5e", "Licence 1", "Licence 2", "Licence 3"} <= grade_names


def test_student_pages_render_courses_and_lessons():
    with TestClient(app) as client:
        home = client.get("/")
        assert home.status_code == 200
        assert "Tous les cours" in home.text
        course = next(course for course in client.get("/catalog").json() if course["title"] == "Comprendre les fractions")
        lesson_page = client.get(f"/learn/{course['id']}")
        assert lesson_page.status_code == 200
        assert "Les fractions" in lesson_page.text
        assert "Valider mes reponses" in lesson_page.text
        assert "/quiz.js" in lesson_page.text


def test_class_selector_filters_courses():
    with TestClient(app) as client:
        university = client.get("/?grade=Licence+1")
        assert university.status_code == 200
        assert "Algorithmique et structures de donnees" in university.text
        assert "Comprendre les fractions" not in university.text


def test_student_can_complete_lesson_and_submit_quiz():
    with TestClient(app) as client:
        registration = client.post("/auth/register", json={"name": "Afi Mensah", "email": "afi@example.com", "password": "secret123"})
        assert registration.status_code == 201
        login = client.post("/auth/login", json={"email": "afi@example.com", "password": "secret123"})
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        course = next(course for course in client.get("/catalog").json() if course["title"] == "Comprendre les fractions")
        lesson = client.get(f"/courses/{course['id']}").json()["lessons"][0]
        lesson = client.get(f"/lessons/{lesson['id']}").json()
        question_id = lesson["questions"][0]["id"]
        result = client.post(f"/lessons/{lesson['lesson']['id']}/quiz", headers=headers, json={"answers": {str(question_id): "4/5"}})
        assert result.status_code == 200
        assert result.json()["score"] == 100
        assert client.get("/progress", headers=headers).json()["completed_lessons"] == 1