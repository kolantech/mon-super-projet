from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field


ROOT = Path(__file__).parent
DATABASE_PATH = Path(os.getenv("EDUTOGO_DATABASE", ROOT / "edutogo.db"))
TOKEN_SECRET = os.getenv("EDUTOGO_TOKEN_SECRET", "change-me-in-production")

app = FastAPI(title="EDU-TOGO API", version="0.1.0", description="MVP de plateforme educative configurable pour le Togo.")


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000)
    return f"{salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    salt, expected = stored.split("$", 1)
    actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000).hex()
    return hmac.compare_digest(actual, expected)


def make_token(user_id: int) -> str:
    payload = f"{user_id}:{int(time.time()) + 86_400}"
    signature = hmac.new(TOKEN_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}:{signature}"


def current_user(authorization: Annotated[str | None, Header()] = None) -> sqlite3.Row:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentification requise")
    try:
        user_id, expires, signature = authorization[7:].split(":", 2)
        payload = f"{user_id}:{expires}"
        valid = hmac.compare_digest(signature, hmac.new(TOKEN_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest())
        if not valid or int(expires) < int(time.time()):
            raise ValueError
    except (ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Jeton invalide ou expire") from None
    with connect() as connection:
        user = connection.execute("SELECT * FROM users WHERE id = ?", (int(user_id),)).fetchone()
    if user is None:
        raise HTTPException(status_code=401, detail="Utilisateur introuvable")
    return user


class RegisterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=5, max_length=180)
    password: str = Field(min_length=8, max_length=128)
    role: str = Field(default="student", pattern="^(student|teacher)$")
    grade_id: int | None = None


class LoginRequest(BaseModel):
    email: str
    password: str


class QuizSubmission(BaseModel):
    answers: dict[int, str]


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('student', 'teacher', 'admin')), grade_id INTEGER, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS grades (id INTEGER PRIMARY KEY AUTOINCREMENT, level TEXT NOT NULL, name TEXT NOT NULL, UNIQUE(level, name));
CREATE TABLE IF NOT EXISTS subjects (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS courses (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, description TEXT NOT NULL, grade_id INTEGER NOT NULL REFERENCES grades(id), subject_id INTEGER NOT NULL REFERENCES subjects(id), difficulty TEXT NOT NULL DEFAULT 'Intermediaire', duration_minutes INTEGER NOT NULL DEFAULT 20);
CREATE TABLE IF NOT EXISTS lessons (id INTEGER PRIMARY KEY AUTOINCREMENT, course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE, title TEXT NOT NULL, objectives TEXT NOT NULL, content TEXT NOT NULL, position INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS questions (id INTEGER PRIMARY KEY AUTOINCREMENT, lesson_id INTEGER NOT NULL REFERENCES lessons(id) ON DELETE CASCADE, prompt TEXT NOT NULL, choices TEXT NOT NULL, answer TEXT NOT NULL, explanation TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS progress (user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, lesson_id INTEGER NOT NULL REFERENCES lessons(id) ON DELETE CASCADE, completed INTEGER NOT NULL DEFAULT 0, score INTEGER, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(user_id, lesson_id));
"""


COURSE_CATALOG = (
    {
        "grade": ("Primaire", "CM2"),
        "subject": "Mathematiques",
        "title": "Les nombres decimaux",
        "description": "Lire, comparer et calculer avec les nombres decimaux.",
        "difficulty": "Debutant",
        "duration": 25,
        "lessons": (
            ("Lire un nombre decimal", "Reconnaitre la partie entiere et la partie decimale.", "Un nombre decimal comporte une partie entiere et une partie decimale separees par une virgule.", "Dans 12,45, 12 est la partie entiere et 45 la partie decimale.", "Quelle est la partie entiere de 7,25 ?", "7|25|725", "7", "La partie entiere est situee avant la virgule."),
            ("Comparer des decimaux", "Comparer des nombres decimaux en utilisant leur valeur de position.", "On compare d'abord les parties entieres, puis les dixiemes et les centiemes si necessaire.", "Entre 3,4 et 3,04, 3,4 est le plus grand car 40 centiemes sont superieurs a 4 centiemes.", "Quel nombre est le plus grand ?", "2,5|2,05|2,005", "2,5", "2,5 vaut 2,500 et depasse les deux autres nombres."),
        ),
    },
    {
        "grade": ("Secondaire", "6e"),
        "subject": "Mathematiques",
        "title": "Comprendre les fractions",
        "description": "Representer, comparer et additionner des fractions simples.",
        "difficulty": "Debutant",
        "duration": 25,
        "lessons": (
            ("Les fractions, pas a pas", "Identifier le numerateur et le denominateur; comparer deux fractions.", "Une fraction represente une ou plusieurs parts egales d'un tout. Dans 3/4, 3 est le numerateur et 4 le denominateur.", "Quelle fraction est la plus grande entre 2/5 et 4/5 ?", "2/5|4/5|Elles sont egales", "4/5", "Les denominateurs sont identiques : 4 est superieur a 2."),
            ("Additionner des fractions", "Additionner des fractions de meme denominateur.", "Pour des fractions de meme denominateur, on additionne les numerateurs et on conserve le denominateur.", "2/7 + 3/7 = 5/7.", "Combien font 1/6 + 4/6 ?", "4/6|5/6|5/12", "5/6", "Les numerateurs 1 et 4 donnent 5, avec le denominateur 6."),
        ),
    },
    {
        "grade": ("Secondaire", "5e"),
        "subject": "Mathematiques",
        "title": "Equations du premier degre",
        "description": "Resoudre une equation simple et verifier sa solution.",
        "difficulty": "Intermediaire",
        "duration": 30,
        "lessons": (
            ("Isoler l'inconnue", "Utiliser les operations inverses pour trouver x.", "Dans x + 4 = 9, on soustrait 4 aux deux membres pour obtenir x = 5.", "Quelle est la solution de x + 6 = 10 ?", "2|4|16", "4", "On soustrait 6 aux deux membres : x = 4."),
            ("Verifier une equation", "Remplacer l'inconnue par sa valeur et controler l'egalite.", "Une solution est correcte lorsque les deux membres ont la meme valeur apres remplacement.", "Pour 3x = 12, remplacer x par 4 donne 3 x 4 = 12.", "Quelle valeur verifie 2x = 14 ?", "5|7|12", "7", "2 x 7 = 14."),
        ),
    },
    {
        "grade": ("Secondaire", "5e"),
        "subject": "Francais",
        "title": "Grammaire et phrase simple",
        "description": "Identifier le sujet, le verbe et les complements essentiels.",
        "difficulty": "Debutant",
        "duration": 25,
        "lessons": (
            ("Trouver le verbe", "Identifier le verbe conjugue dans une phrase.", "Le verbe exprime une action ou un etat et varie selon le temps et le sujet.", "Dans 'Les eleves lisent', le verbe conjugue est lisent.", "Quel est le verbe dans 'Afi prepare son devoir' ?", "Afi|prepare|devoir", "prepare", "Prepare indique l'action realisee."),
            ("Accorder le sujet et le verbe", "Accorder correctement le verbe avec son sujet.", "Le verbe s'accorde avec le sujet en personne et en nombre.", "Les enfants jouent, mais l'enfant joue.", "Quelle phrase est correcte ?", "Les fille chante|Les filles chantent|Les filles chante", "Les filles chantent", "Le sujet filles est au pluriel."),
        ),
    },
    {
        "grade": ("Secondaire", "4e"),
        "subject": "Sciences",
        "title": "Les ecosystemes",
        "description": "Comprendre les relations entre les etres vivants et leur milieu.",
        "difficulty": "Intermediaire",
        "duration": 30,
        "lessons": (
            ("Le milieu de vie", "Decrire un ecosysteme et ses composantes.", "Un ecosysteme comprend un milieu physique et les etres vivants qui y interagissent.", "Une mare associe de l'eau, des plantes, des animaux et des micro-organismes.", "Quelle composante appartient au milieu physique d'une mare ?", "Une grenouille|La temperature de l'eau|Une algue", "La temperature de l'eau", "La temperature est un facteur physique."),
            ("Les chaines alimentaires", "Representer le transfert de matiere et d'energie.", "Une chaine alimentaire commence generalement par un producteur puis des consommateurs.", "Herbe -> criquet -> grenouille illustre une chaine alimentaire.", "Quel organisme est producteur ?", "L'herbe|Le criquet|La grenouille", "L'herbe", "Les plantes produisent leur matiere organique."),
        ),
    },
    {
        "grade": ("Secondaire", "3e"),
        "subject": "Histoire-Geographie",
        "title": "Le Togo et ses territoires",
        "description": "Situer le Togo, ses regions et ses principaux espaces de vie.",
        "difficulty": "Debutant",
        "duration": 25,
        "lessons": (
            ("Situer le Togo", "Identifier les pays voisins et le golfe de Guinee.", "Le Togo se situe en Afrique de l'Ouest et possede une facade sur le golfe de Guinee.", "Le territoire togolais s'etire du nord au sud entre plusieurs pays voisins.", "Sur quel golfe s'ouvre le Togo ?", "Le golfe de Guinee|Le golfe du Mexique|Le golfe Persique", "Le golfe de Guinee", "Le Togo possede une facade maritime sur le golfe de Guinee."),
            ("Villes et activites", "Relier les espaces aux activites humaines principales.", "Les villes concentrent des activites administratives, commerciales, industrielles et de services.", "Lome est la capitale et un important centre portuaire et commercial.", "Quelle ville est la capitale du Togo ?", "Kara|Lome|Atakpame", "Lome", "Lome est la capitale du Togo."),
        ),
    },
)


def seed_database() -> None:
    with connect() as connection:
        connection.executescript(SCHEMA)
        for catalog_course in COURSE_CATALOG:
            grade_level, grade_name = catalog_course["grade"]
            connection.execute("INSERT OR IGNORE INTO grades(level, name) VALUES (?, ?)", (grade_level, grade_name))
            grade_id = connection.execute("SELECT id FROM grades WHERE name = ?", (grade_name,)).fetchone()[0]
            connection.execute("INSERT OR IGNORE INTO subjects(name) VALUES (?)", (catalog_course["subject"],))
            subject_id = connection.execute("SELECT id FROM subjects WHERE name = ?", (catalog_course["subject"],)).fetchone()[0]
            course = connection.execute("SELECT id FROM courses WHERE title = ? AND grade_id = ?", (catalog_course["title"], grade_id)).fetchone()
            if course is None:
                cursor = connection.execute(
                    "INSERT INTO courses(title, description, grade_id, subject_id, difficulty, duration_minutes) VALUES (?, ?, ?, ?, ?, ?)",
                    (catalog_course["title"], catalog_course["description"], grade_id, subject_id, catalog_course["difficulty"], catalog_course["duration"]),
                )
                course_id = cursor.lastrowid
            else:
                course_id = course["id"]
            for position, lesson_data in enumerate(catalog_course["lessons"], start=1):
                if len(lesson_data) == 7:
                    lesson_title, objectives, content, question_prompt, choices, answer, explanation = lesson_data
                    content_detail = ""
                else:
                    lesson_title, objectives, content, content_detail, question_prompt, choices, answer, explanation = lesson_data
                lesson = connection.execute("SELECT id FROM lessons WHERE course_id = ? AND title = ?", (course_id, lesson_title)).fetchone()
                if lesson is None:
                    cursor = connection.execute(
                        "INSERT INTO lessons(course_id, title, objectives, content, position) VALUES (?, ?, ?, ?, ?)",
                        (course_id, lesson_title, objectives, f"{content} {content_detail}", position),
                    )
                    lesson_id = cursor.lastrowid
                else:
                    lesson_id = lesson["id"]
                question = connection.execute("SELECT id FROM questions WHERE lesson_id = ? AND prompt = ?", (lesson_id, question_prompt)).fetchone()
                if question is None:
                    connection.execute(
                        "INSERT INTO questions(lesson_id, prompt, choices, answer, explanation) VALUES (?, ?, ?, ?, ?)",
                        (lesson_id, question_prompt, choices, answer, explanation),
                    )


@app.on_event("startup")
def startup() -> None:
    seed_database()


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return """<!doctype html><html lang='fr'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>EDU-TOGO</title><style>:root{font-family:Georgia,serif;color:#17251f;background:#f4f1e8}body{margin:0}header{background:#143d35;color:#fff;padding:20px 7vw}main{max-width:980px;margin:48px auto;padding:0 24px}.hero{display:grid;grid-template-columns:1.3fr .7fr;gap:32px;align-items:center}h1{font-size:clamp(2.6rem,7vw,5.8rem);line-height:.95;margin:0 0 20px}p{font:1.05rem/1.6 system-ui,sans-serif}.panel{background:#e9c46a;padding:28px;border-radius:8px;box-shadow:10px 10px 0 #ee8952}.panel strong{font-size:3rem;display:block}a{color:#143d35;font-weight:700}footer{margin-top:80px;font:14px system-ui,sans-serif;color:#52625a}@media(max-width:700px){.hero{grid-template-columns:1fr}.panel{margin-top:12px}}</style></head><body><header><strong>EDU-TOGO</strong><span> &middot; apprendre, comprendre, reussir</span></header><main><section class='hero'><div><p>PLATEFORME EDUCATIVE</p><h1>Le savoir avance avec toi.</h1><p>Un premier espace pour apprendre les fractions en 5e, pratiquer et mesurer ses progres. L'API est prete pour accueillir les futurs cours, examens et EDU AI.</p><p><a href='/docs'>Explorer l'API interactive &rarr;</a></p></div><div class='panel'><strong>5e</strong><span>Mathematiques<br>Comprendre les fractions<br>Quiz inclus</span></div></section><footer>MVP EDU-TOGO &middot; contenus administrables &middot; base locale SQLite</footer></main></body></html>"""


@app.post("/auth/register", status_code=201)
def register(payload: RegisterRequest):
    with connect() as connection:
        try:
            cursor = connection.execute("INSERT INTO users(name, email, password_hash, role, grade_id) VALUES (?, ?, ?, ?, ?)", (payload.name, payload.email.lower(), hash_password(payload.password), payload.role, payload.grade_id))
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=409, detail="Cette adresse email existe deja") from None
        return {"id": cursor.lastrowid, "name": payload.name, "email": payload.email.lower(), "role": payload.role}


@app.post("/auth/login")
def login(payload: LoginRequest):
    with connect() as connection:
        user = connection.execute("SELECT * FROM users WHERE email = ?", (payload.email.lower(),)).fetchone()
    if user is None or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")
    return {"access_token": make_token(user["id"]), "token_type": "bearer", "user": {"id": user["id"], "name": user["name"], "role": user["role"]}}


@app.get("/me")
def me(user: sqlite3.Row = Depends(current_user)):
    return {"id": user["id"], "name": user["name"], "email": user["email"], "role": user["role"], "grade_id": user["grade_id"]}


@app.get("/catalog")
def catalog(grade_id: int | None = Query(default=None), subject: str | None = None):
    query = "SELECT c.id, c.title, c.description, c.difficulty, c.duration_minutes, g.name AS grade, s.name AS subject FROM courses c JOIN grades g ON g.id = c.grade_id JOIN subjects s ON s.id = c.subject_id WHERE 1=1"
    values: list[object] = []
    if grade_id is not None:
        query += " AND c.grade_id = ?"
        values.append(grade_id)
    if subject:
        query += " AND lower(s.name) LIKE ?"
        values.append(f"%{subject.lower()}%")
    query += " ORDER BY c.title"
    with connect() as connection:
        return [dict(row) for row in connection.execute(query, values).fetchall()]


@app.get("/grades")
def grades():
    with connect() as connection:
        rows = connection.execute("SELECT id, level, name FROM grades ORDER BY level, name").fetchall()
    return [dict(row) for row in rows]


@app.get("/subjects")
def subjects():
    with connect() as connection:
        rows = connection.execute("SELECT id, name FROM subjects ORDER BY name").fetchall()
    return [dict(row) for row in rows]


@app.get("/courses/{course_id}")
def course(course_id: int):
    with connect() as connection:
        result = connection.execute("SELECT c.*, g.name AS grade, s.name AS subject FROM courses c JOIN grades g ON g.id=c.grade_id JOIN subjects s ON s.id=c.subject_id WHERE c.id=?", (course_id,)).fetchone()
        if result is None:
            raise HTTPException(status_code=404, detail="Cours introuvable")
        lessons = connection.execute("SELECT id, title, objectives, position FROM lessons WHERE course_id=? ORDER BY position", (course_id,)).fetchall()
        return {"course": dict(result), "lessons": [dict(lesson) for lesson in lessons]}


@app.get("/lessons/{lesson_id}")
def lesson(lesson_id: int):
    with connect() as connection:
        result = connection.execute("SELECT * FROM lessons WHERE id=?", (lesson_id,)).fetchone()
        questions = connection.execute("SELECT id, prompt, choices FROM questions WHERE lesson_id=?", (lesson_id,)).fetchall()
    if result is None:
        raise HTTPException(status_code=404, detail="Lecon introuvable")
    return {"lesson": dict(result), "questions": [{**dict(question), "choices": question["choices"].split("|")} for question in questions]}


@app.post("/lessons/{lesson_id}/complete")
def complete_lesson(lesson_id: int, user: sqlite3.Row = Depends(current_user)):
    with connect() as connection:
        if connection.execute("SELECT id FROM lessons WHERE id=?", (lesson_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="Lecon introuvable")
        connection.execute("INSERT INTO progress(user_id, lesson_id, completed) VALUES (?, ?, 1) ON CONFLICT(user_id, lesson_id) DO UPDATE SET completed=1, updated_at=CURRENT_TIMESTAMP", (user["id"], lesson_id))
    return {"lesson_id": lesson_id, "completed": True}


@app.post("/lessons/{lesson_id}/quiz")
def submit_quiz(lesson_id: int, payload: QuizSubmission, user: sqlite3.Row = Depends(current_user)):
    with connect() as connection:
        questions = connection.execute("SELECT id, answer, explanation FROM questions WHERE lesson_id=?", (lesson_id,)).fetchall()
        if not questions:
            raise HTTPException(status_code=404, detail="Quiz introuvable")
        correct = sum(payload.answers.get(question["id"]) == question["answer"] for question in questions)
        score = round(correct * 100 / len(questions))
        connection.execute("INSERT INTO progress(user_id, lesson_id, completed, score) VALUES (?, ?, 1, ?) ON CONFLICT(user_id, lesson_id) DO UPDATE SET completed=1, score=excluded.score, updated_at=CURRENT_TIMESTAMP", (user["id"], lesson_id, score))
        corrections = [{"question_id": question["id"], "correct": payload.answers.get(question["id"]) == question["answer"], "explanation": question["explanation"]} for question in questions]
    return {"score": score, "correct": correct, "total": len(questions), "corrections": corrections}


@app.get("/progress")
def progress(user: sqlite3.Row = Depends(current_user)):
    with connect() as connection:
        rows = connection.execute("SELECT p.lesson_id, l.title, c.title AS course, p.completed, p.score FROM progress p JOIN lessons l ON l.id=p.lesson_id JOIN courses c ON c.id=l.course_id WHERE p.user_id=?", (user["id"],)).fetchall()
    return {"items": [dict(row) for row in rows], "completed_lessons": sum(row["completed"] for row in rows)}


@app.get("/health")
def health():
    return {"status": "ok", "service": "edutogo-api"}