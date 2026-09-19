# EDU-TOGO

MVP de plateforme éducative web et API pour le contexte togolais.

## Parcours disponible

- inscription et connexion élève/enseignant ;
- catalogue configurable par niveau et matière ;
- parcours primaire (CM1-CM2), secondaire (6e a 3e) et universitaire (Licences 1 a 3) ;
- cours de demonstration en mathematiques, francais, sciences, anglais, histoire-geographie, physique-chimie, informatique, bases de donnees et developpement web ;
- cours, leçons et objectifs pédagogiques ;
- quiz avec correction détaillée ;
- progression personnelle ;
- documentation OpenAPI via `/docs` ;
- page web responsive d'accueil via `/`.

Le contenu de démonstration est créé au démarrage dans SQLite. Le programme n'est pas codé en dur dans l'interface : niveaux, matières, cours, leçons et questions sont des entités persistées et pourront être administrés dans la prochaine phase.

## Démarrage

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
uvicorn app:app --reload
```

Ouvrir `http://127.0.0.1:8000/` ou `http://127.0.0.1:8000/docs`.

## API pedagogique

- `GET /grades` liste les niveaux disponibles ;
- `GET /subjects` liste les matieres disponibles ;
- `GET /catalog` accepte `grade_id` et `subject` pour filtrer les cours ;
- `GET /courses/{course_id}` retourne les lecons d'un cours ;
- `GET /lessons/{lesson_id}` retourne le contenu et les questions ;
- `POST /lessons/{lesson_id}/quiz` corrige un quiz et enregistre le score ;
- `GET /progress` retourne la progression de l'utilisateur connecte.

## Architecture cible par phases

1. MVP actuel : contenu, authentification, quiz et progression.
2. CMS et RBAC : administration pédagogique, enseignants, validation et modération.
3. Prépa examens : sujets, chronomètre, résultats et bibliothèque.
4. EDU AI : abstraction fournisseur, RAG sur documents validés, citations et évaluation.
5. Multi-tenant : établissements, parents, consentements et règles de confidentialité mineurs.
6. Offline/mobile : PWA, synchronisation différée puis client Flutter partageant cette API.
7. Production : PostgreSQL, Redis, stockage objet, tâches asynchrones, observabilité et CI/CD.

## Choix techniques

FastAPI est retenu pour une API Python typée et documentée automatiquement. SQLite garde le démarrage local simple ; PostgreSQL + pgvector, Redis et un stockage objet sont les cibles de production. Le secret de jeton doit être défini par `EDUTOGO_TOKEN_SECRET` avant tout déploiement.