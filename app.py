from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from html import escape
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

COURSE_CATALOG = COURSE_CATALOG + (
    {
        "grade": ("Primaire", "CM1"),
        "subject": "Francais",
        "title": "Lire et comprendre un texte",
        "description": "Lire un recit court, trouver les informations et raconter l'essentiel.",
        "difficulty": "Debutant",
        "duration": 20,
        "lessons": (
            ("Les personnages et le lieu", "Identifier qui agit et ou se deroule l'histoire.", "Un recit repond souvent aux questions qui, ou et quand.", "Les personnages sont les acteurs de l'histoire et le lieu indique ou elle se passe.", "Quelle information indique le lieu ?", "Le decor|Le personnage|Le titre", "Le decor", "Le decor decrit le lieu de l'histoire."),
            ("Resumer un recit", "Reformuler les evenements principaux dans l'ordre.", "Un bon resume garde les actions essentielles et respecte leur chronologie.", "On peut utiliser d'abord, ensuite et enfin pour organiser les evenements.", "Que doit garder un resume ?", "Tous les details|Les actions essentielles|Les mots difficiles", "Les actions essentielles", "Un resume conserve l'essentiel."),
        ),
    },
    {
        "grade": ("Primaire", "CM1"),
        "subject": "Sciences",
        "title": "Le corps humain et la sante",
        "description": "Decouvrir les fonctions du corps et les habitudes favorables a la sante.",
        "difficulty": "Debutant",
        "duration": 20,
        "lessons": (
            ("Les besoins du corps", "Relier alimentation, eau, sommeil et activite physique.", "Le corps a besoin d'une alimentation variee, d'eau, de sommeil et de mouvement.", "Ces besoins permettent de grandir, apprendre et rester en bonne sante.", "Quel besoin aide a recuperer pendant la nuit ?", "Le sommeil|Le bruit|La poussiere", "Le sommeil", "Le sommeil permet au corps de recuperer."),
            ("Hygiene et prevention", "Adopter des gestes simples pour limiter les maladies.", "Se laver les mains et proteger les aliments limitent la transmission de microbes.", "La prevention agit avant que la maladie apparaisse.", "Quel geste limite les microbes ?", "Se laver les mains|Partager une bouteille|Oublier de cuisiner", "Se laver les mains", "Le lavage des mains retire beaucoup de microbes."),
        ),
    },
    {
        "grade": ("Primaire", "CM2"),
        "subject": "Culture numerique",
        "title": "Premiers pas avec le numerique",
        "description": "Utiliser un appareil, proteger ses donnees et rechercher une information.",
        "difficulty": "Debutant",
        "duration": 20,
        "lessons": (
            ("Materiel et fichiers", "Distinguer appareil, application et fichier.", "Un appareil execute des applications qui permettent de creer ou lire des fichiers.", "Un texte enregistre est un fichier, tandis qu'un traitement de texte est une application.", "Qu'est-ce qui contient un texte enregistre ?", "Un fichier|Un clavier|Une prise", "Un fichier", "Le fichier contient les donnees enregistrees."),
            ("Securite en ligne", "Reconnaitre un mot de passe et une information personnelle.", "Un mot de passe doit rester secret et une information personnelle ne doit pas etre partagee sans accord.", "Demander conseil a un adulte est un bon reflexe face a un message inconnu.", "Que faut-il garder secret ?", "Son mot de passe|Le titre d'un livre|Une couleur", "Son mot de passe", "Un mot de passe protege un compte."),
        ),
    },
    {
        "grade": ("Secondaire", "4e"),
        "subject": "Anglais",
        "title": "Communiquer en anglais",
        "description": "Se presenter, poser des questions et parler de ses activites quotidiennes.",
        "difficulty": "Debutant",
        "duration": 25,
        "lessons": (
            ("Se presenter", "Utiliser les expressions de base pour parler de soi.", "My name is permet de dire son nom et I am permet de donner une information sur soi.", "Une presentation peut inclure le nom, l'age et la ville.", "Comment dire 'Je m'appelle Afi' ?", "My name is Afi|I name Afi|Me is Afi", "My name is Afi", "My name is introduit son nom."),
            ("Parler de ses habitudes", "Utiliser le present simple dans une phrase courte.", "Le present simple decrit une habitude : I study, you play, she reads.", "Avec he, she et it, le verbe prend souvent un s.", "Quelle phrase est correcte ?", "She play football|She plays football|She playing football", "She plays football", "Le verbe prend s avec she."),
        ),
    },
    {
        "grade": ("Secondaire", "3e"),
        "subject": "Physique-Chimie",
        "title": "Matiere et electricite",
        "description": "Observer les etats de la matiere et comprendre un circuit simple.",
        "difficulty": "Intermediaire",
        "duration": 30,
        "lessons": (
            ("Les etats de la matiere", "Relier solide, liquide et gaz a leurs proprietes.", "Un solide garde sa forme, un liquide prend la forme du recipient et un gaz occupe l'espace disponible.", "La temperature peut provoquer un changement d'etat.", "Quel etat prend la forme du recipient ?", "Solide|Liquide|Bois", "Liquide", "Un liquide prend la forme du recipient."),
            ("Le circuit electrique", "Identifier les elements indispensables d'un circuit ferme.", "Un circuit simple contient une source, des conducteurs et un recepteur relies en boucle fermee.", "Une boucle ouverte empeche le courant de circuler.", "Quand la lampe peut-elle s'allumer ?", "Circuit ferme|Circuit casse|Pile absente", "Circuit ferme", "La boucle fermee permet la circulation du courant."),
        ),
    },
    {
        "grade": ("Secondaire", "3e"),
        "subject": "Informatique",
        "title": "Algorithmique et programmation",
        "description": "Decomposer un probleme, ecrire un algorithme et tester un programme.",
        "difficulty": "Intermediaire",
        "duration": 30,
        "lessons": (
            ("Decrire une procedure", "Ordonner des instructions pour obtenir un resultat.", "Un algorithme est une suite finie d'instructions precises qui resout un probleme.", "Les instructions doivent etre assez claires pour etre executees dans le bon ordre.", "Que contient un algorithme ?", "Des instructions ordonnees|Des couleurs seulement|Un dessin sans regle", "Des instructions ordonnees", "L'ordre des instructions produit le resultat attendu."),
            ("Conditions et repetitions", "Utiliser si et repeter dans une solution.", "Une condition choisit une action et une repetition execute plusieurs fois une meme action.", "Ces structures rendent les programmes plus courts et adaptables.", "Quelle structure repete une action ?", "Boucle|Titre|Commentaire", "Boucle", "Une boucle repete une action."),
        ),
    },
    {
        "grade": ("Universite", "Licence 1"),
        "subject": "Informatique",
        "title": "Algorithmique et structures de donnees",
        "description": "Analyser un probleme, choisir une structure et estimer la complexite.",
        "difficulty": "Intermediaire",
        "duration": 45,
        "lessons": (
            ("Complexite algorithmique", "Comparer le cout d'algorithmes avec la notation O.", "La complexite decrit l'evolution du temps ou de la memoire quand la taille des donnees augmente.", "Une recherche lineaire parcourt au plus n elements et est souvent notee O(n).", "Quelle complexite correspond a une recherche lineaire simple ?", "O(1)|O(n)|O(n2)", "O(n)", "Le nombre d'operations augmente avec n."),
            ("Listes et piles", "Choisir une structure selon les operations necessaires.", "Une pile suit la regle dernier entre, premier sorti, tandis qu'une liste permet un parcours ordonne.", "Les structures de donnees rendent les operations explicites et testables.", "Quelle regle suit une pile ?", "Premier entre, premier sorti|Dernier entre, premier sorti|Aleatoire", "Dernier entre, premier sorti", "Une pile suit LIFO."),
        ),
    },
    {
        "grade": ("Universite", "Licence 1"),
        "subject": "Mathematiques",
        "title": "Algebre lineaire pour debutants",
        "description": "Manipuler vecteurs, matrices et systemes lineaires simples.",
        "difficulty": "Intermediaire",
        "duration": 45,
        "lessons": (
            ("Vecteurs et operations", "Additionner des vecteurs et reconnaitre une combinaison lineaire.", "Un vecteur est un objet qui peut etre represente par une liste de composantes.", "L'addition se fait composante par composante.", "Comment additionner deux vecteurs ?", "Composante par composante|En divisant toujours|En supprimant les composantes", "Composante par composante", "Chaque coordonnee est additionnee avec celle de meme rang."),
            ("Systemes lineaires", "Interpretrer une equation matricielle simple.", "Un systeme lineaire rassemble plusieurs equations dont les inconnues doivent satisfaire toutes les equations.", "La methode d'elimination transforme le systeme sans changer ses solutions.", "Que cherche-t-on dans un systeme lineaire ?", "Les valeurs des inconnues|Une couleur|Un fichier", "Les valeurs des inconnues", "La solution donne les valeurs qui verifient toutes les equations."),
        ),
    },
    {
        "grade": ("Universite", "Licence 2"),
        "subject": "Bases de donnees",
        "title": "Conception des bases de donnees",
        "description": "Modeliser des donnees, ecrire des requetes et proteger leur coherence.",
        "difficulty": "Intermediaire",
        "duration": 45,
        "lessons": (
            ("Modele relationnel", "Passer des besoins metier aux tables et relations.", "Une table regroupe des lignes de meme nature et une cle identifie chaque ligne.", "Les relations relient les donnees sans repeter inutilement les informations.", "Quel element identifie une ligne ?", "Une cle primaire|Une couleur|Une image", "Une cle primaire", "La cle primaire identifie chaque enregistrement."),
            ("Requetes SQL", "Lire et filtrer des donnees avec SELECT et WHERE.", "SELECT choisit les colonnes et WHERE filtre les lignes qui respectent une condition.", "Une requete claire exprime le besoin sans modifier les donnees par accident.", "Quelle clause filtre les lignes ?", "WHERE|FROM|SELECT", "WHERE", "WHERE ajoute une condition de filtrage."),
        ),
    },
    {
        "grade": ("Universite", "Licence 3"),
        "subject": "Developpement web",
        "title": "Applications web et API",
        "description": "Construire une API, valider des donnees et servir une interface web.",
        "difficulty": "Avance",
        "duration": 50,
        "lessons": (
            ("Concevoir une API", "Definir des routes, des representations et des codes HTTP.", "Une API expose des ressources par des routes et utilise des methodes HTTP adaptees.", "GET lit une ressource, POST en cree une et les reponses indiquent le resultat.", "Quelle methode cree generalement une ressource ?", "GET|POST|TRACE", "POST", "POST est utilise pour creer une ressource."),
            ("Valider et securiser", "Valider les entrees et separer les secrets du code.", "Une API doit valider les donnees recues, limiter les acces et garder les secrets dans l'environnement.", "La validation reduit les erreurs et les risques d'injection.", "Ou placer un secret de production ?", "Dans le code public|Dans une variable d'environnement|Dans une URL partagee", "Dans une variable d'environnement", "Les secrets ne doivent pas etre inscrits dans le code."),
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
def home(grade: str | None = Query(default=None)) -> str:
    with connect() as connection:
        query = """
            SELECT c.id, c.title, c.description, c.difficulty, c.duration_minutes,
                   g.name AS grade, s.name AS subject, COUNT(l.id) AS lesson_count
            FROM courses c
            JOIN grades g ON g.id = c.grade_id
            JOIN subjects s ON s.id = c.subject_id
            LEFT JOIN lessons l ON l.course_id = c.id
            WHERE 1 = 1
        """
        values: list[str] = []
        if grade:
            query += " AND g.name = ?"
            values.append(grade)
        query += " GROUP BY c.id ORDER BY c.title"
        courses = connection.execute(query, values).fetchall()
    cards = "".join(
        f"<article class='course' data-grade='{escape(row['grade'])}'><div class='course-top'><span class='tag'>{escape(row['grade'])}</span><span class='tag quiet'>{escape(row['subject'])}</span></div>"
        f"<h3>{escape(row['title'])}</h3><p>{escape(row['description'])}</p><div class='course-meta'>{row['lesson_count']} lecons &middot; {row['duration_minutes']} min</div>"
        f"<a class='button' href='/learn/{row['id']}'>Commencer le cours</a></article>"
        for row in courses
    )
    class_options = "".join(
        f"<option value='{escape(class_name)}' {'selected' if grade == class_name else ''}>{escape(class_name)}</option>"
        for class_name in ("CP1", "CP2", "CE1", "CE2", "CM1", "CM2", "6e", "5e", "4e", "3e", "Licence 1", "Licence 2", "Licence 3")
    )
    empty_state = "<div class='empty'>Aucun cours n'est encore publie pour cette classe. Le catalogue sera enrichi prochainement.</div>" if not courses else ""
    page = f"""<!doctype html><html lang='fr'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>EDU-TOGO | Mes cours</title><style>:root{{font-family:system-ui,sans-serif;color:#173b35;background:#f7f4ec}}*{{box-sizing:border-box}}body{{margin:0}}header{{background:#173b35;color:#fff;padding:20px max(24px,7vw);display:flex;justify-content:space-between;align-items:center}}header strong{{font-family:Georgia,serif;font-size:1.3rem}}header a{{color:#f5d66b;text-decoration:none;font-weight:700}}main{{max-width:1180px;margin:auto;padding:48px 24px 80px}}.hero{{display:grid;grid-template-columns:1.2fr .8fr;gap:32px;align-items:end;margin-bottom:32px}}.eyebrow{{color:#d86b3b;font-weight:800;letter-spacing:.12em;font-size:.75rem}}h1{{font:clamp(2.8rem,7vw,5.8rem)/.92 Georgia,serif;margin:12px 0 18px;max-width:700px}}h2{{font:2rem Georgia,serif;margin:0 0 18px}}h3{{font:1.35rem Georgia,serif;margin:14px 0 8px}}p{{line-height:1.6;color:#52625a}}.intro{{font-size:1.12rem;max-width:650px}}.stats{{background:#e9c46a;padding:28px;border-radius:8px;box-shadow:10px 10px 0 #ee8952}}.stats strong{{display:block;font:3.5rem Georgia,serif}}.chooser{{display:flex;align-items:center;gap:14px;background:#fff;border:1px solid #d8ddd3;border-radius:8px;padding:14px 18px;margin-bottom:26px}}.chooser label{{font-weight:800}}select{{font:inherit;border:1px solid #b7c3b8;border-radius:6px;padding:9px 38px 9px 12px;background:#fff;color:#173b35;min-width:210px}}.courses{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:18px}}.course{{background:#fff;border:1px solid #d8ddd3;padding:22px;border-radius:8px;display:flex;flex-direction:column;min-height:270px;box-shadow:0 8px 18px #173b3510}}.course-top{{display:flex;gap:7px;flex-wrap:wrap}}.tag{{background:#173b35;color:#fff;border-radius:999px;padding:5px 10px;font-size:.75rem;font-weight:800}}.tag.quiet{{background:#e5efe7;color:#173b35}}.course p{{margin:0 0 14px}}.course-meta{{margin-top:auto;color:#7a877d;font-size:.85rem}}.button{{display:inline-block;background:#d86b3b;color:#fff;text-decoration:none;text-align:center;padding:11px 14px;border-radius:6px;font-weight:800;margin-top:16px}}.empty{{background:#fff;border:1px dashed #b7c3b8;padding:28px;border-radius:8px;color:#52625a}}footer{{margin-top:55px;color:#7a877d;font-size:.9rem}}@media(max-width:720px){{.hero{{grid-template-columns:1fr}}.chooser{{align-items:flex-start;flex-direction:column}}select{{width:100%}}}}</style></head><body><header><strong>EDU-TOGO</strong><a href='/docs'>API &amp; docs</a></header><main><section class='hero'><div><div class='eyebrow'>ESPACE ELEVE</div><h1>Choisis ton prochain cours.</h1><p class='intro'>Selectionne ta classe pour retrouver les cours, les lecons et les quiz adaptes a ton niveau.</p></div><div class='stats'><strong>{len(courses)}</strong><span>cours disponibles pour cette selection</span></div></section><form class='chooser' method='get' action='/'><label for='grade'>Ma classe</label><select id='grade' name='grade' onchange='this.form.submit()'><option value=''>Toutes les classes</option>{class_options}</select></form><section><h2>{escape(grade) if grade else 'Tous les cours'}</h2>{empty_state}<div class='courses'>{cards}</div></section><footer>EDU-TOGO &middot; apprendre, comprendre, reussir</footer></main></body></html>"""
    return page


@app.get("/learn/{course_id}", response_class=HTMLResponse)
def learn(course_id: int) -> str:
    with connect() as connection:
        course = connection.execute("""
            SELECT c.*, g.name AS grade, s.name AS subject
            FROM courses c JOIN grades g ON g.id = c.grade_id JOIN subjects s ON s.id = c.subject_id
            WHERE c.id = ?
        """, (course_id,)).fetchone()
        lessons = connection.execute("SELECT id, title, objectives, content, position FROM lessons WHERE course_id = ? ORDER BY position", (course_id,)).fetchall()
        questions = {}
        for lesson in lessons:
            questions[lesson["id"]] = connection.execute("SELECT id, prompt, choices FROM questions WHERE lesson_id = ? ORDER BY id", (lesson["id"],)).fetchall()
    if course is None:
        raise HTTPException(status_code=404, detail="Cours introuvable")
    lesson_blocks = []
    for lesson in lessons:
        question_blocks = []
        for question in questions[lesson["id"]]:
            options = "".join(f"<label><input type='radio' name='q-{question['id']}' value='{escape(choice)}' required> {escape(choice)}</label>" for choice in question["choices"].split("|"))
            question_blocks.append(f"<div class='question'><strong>{escape(question['prompt'])}</strong>{options}</div>")
        lesson_blocks.append(f"<article class='lesson'><span class='lesson-number'>LECON {lesson['position']:02d}</span><h2>{escape(lesson['title'])}</h2><p class='objective'><strong>Objectif :</strong> {escape(lesson['objectives'])}</p><div class='content'>{escape(lesson['content'])}</div><form class='quiz' data-lesson='{lesson['id']}'>{''.join(question_blocks)}<button type='submit'>Valider mes reponses</button><output></output></form></article>")
    lesson_blocks = [
        block.replace("<form class='quiz'", "<form onsubmit='return false' class='quiz'").replace(
            "<output></output>", "<output>Connecte-toi dans /docs pour enregistrer ton score.</output>"
        )
        for block in lesson_blocks
    ]
    return f"""<!doctype html><html lang='fr'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>{escape(course['title'])} | EDU-TOGO</title><style>:root{{font-family:system-ui,sans-serif;color:#173b35;background:#f7f4ec}}*{{box-sizing:border-box}}body{{margin:0}}header{{background:#173b35;color:#fff;padding:20px max(24px,7vw);display:flex;justify-content:space-between}}header a{{color:#f5d66b;text-decoration:none;font-weight:700}}main{{max-width:900px;margin:auto;padding:42px 24px 80px}}.back{{color:#d86b3b;font-weight:800;text-decoration:none}}.tag{{display:inline-block;background:#e5efe7;border-radius:999px;padding:6px 12px;margin-top:25px;font-size:.8rem;font-weight:800}}h1{{font:clamp(2.4rem,6vw,4.5rem)/.95 Georgia,serif;margin:14px 0}}.lead{{font-size:1.12rem;line-height:1.6;color:#52625a}}.lesson{{background:#fff;border:1px solid #d8ddd3;border-radius:8px;padding:28px;margin:22px 0;box-shadow:0 8px 18px #173b3510}}.lesson-number{{color:#d86b3b;font-size:.75rem;font-weight:900;letter-spacing:.12em}}.lesson h2{{font:2rem Georgia,serif;margin:10px 0}}.objective{{background:#f5d66b33;padding:14px;border-left:4px solid #e9c46a}}.content{{font:1.08rem/1.8 Georgia,serif;white-space:pre-line}}.quiz{{border-top:1px solid #e2e6df;margin-top:24px;padding-top:20px}}.question{{margin:14px 0}}label{{display:block;padding:9px 0;color:#52625a}}button{{background:#d86b3b;color:#fff;border:0;border-radius:6px;padding:11px 14px;font-weight:800;cursor:pointer}}output{{display:block;margin-top:14px;font-weight:800}}@media(max-width:600px){{.lesson{{padding:20px}}}}</style></head><body><header><strong>EDU-TOGO</strong><a href='/'>Tous les cours</a></header><main><a class='back' href='/'>&larr; Retour au catalogue</a><span class='tag'>{escape(course['grade'])} &middot; {escape(course['subject'])}</span><h1>{escape(course['title'])}</h1><p class='lead'>{escape(course['description'])}</p>{''.join(lesson_blocks)}</main><script>document.querySelectorAll('.quiz').forEach(function(form){{form.addEventListener('submit',async function(event){{event.preventDefault();const token=localStorage.getItem('edutogo_token');const output=form.querySelector('output');if(!token){{output.textContent='Connecte-toi dans /docs pour enregistrer ton score.';return}}const answers={{}};form.querySelectorAll('input:checked').forEach(function(input){{answers[input.name.slice(2)]=input.value}});const response=await fetch('/lessons/'+form.dataset.lesson+'/quiz',{{method:'POST',headers:{{'Content-Type':'application/json','Authorization':'Bearer '+token}},body:JSON.stringify({{answers:answers}})}});const result=await response.json();output.textContent=response.ok?'Score : '+result.score+'% ('+result.correct+'/'+result.total+')':'Erreur : '+(result.detail||'reponse impossible')}})}})}});</script></body></html>"""


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