# Architecture EDU-TOGO

## Décision d'architecture

Le MVP démarre comme un monolithe modulaire FastAPI avec SQLite. Cette forme réduit le coût cognitif et permet de valider le parcours pédagogique. En production, la même séparation de domaines évolue vers PostgreSQL, Redis, stockage objet compatible S3, pgvector et des workers Celery.

Le programme scolaire reste une donnée administrable : aucune classe, matière ou série ne doit être codée dans l'interface. Les contenus portent leur niveau, leur version de programme, leur année scolaire, leur source et leur état éditorial.

## Couches cible

```text
Web PWA / Flutter mobile
          |
      API FastAPI
          |
  Auth / pédagogie / examens / progression / administration
       |             |                 |
 PostgreSQL       Redis          stockage objet
       |             |
   pgvector     workers asynchrones
          |
   EDU AI Gateway -> fournisseurs interchangeables
```

## Domaine pédagogique

```text
Pays -> Système éducatif -> Niveau -> Classe -> Matière
     -> Programme/version -> Chapitre -> Leçon
     -> Exercice/Question -> Quiz/Evaluation -> Résultat
```

Le supérieur ajoute `Etablissement -> Faculté -> Département -> Filière -> Niveau -> Semestre -> UE` au-dessus de la même branche de contenu. La formation technique ajoute `Filière -> Spécialité -> Module -> Compétence`.

## Modèle relationnel MVP et extension

```text
users(id, role, name, email, password_hash, grade_id)
grades(id, level, name)
subjects(id, name)
courses(id, grade_id, subject_id, title, status, source_id, program_version_id)
lessons(id, course_id, title, objectives, content, position)
questions(id, lesson_id, prompt, choices, answer, explanation)
progress(user_id, lesson_id, completed, score, updated_at)

schools(id, tenant_id, name) -> classes -> enrollments -> users
curricula(id, grade_id, school_year, version, status)
chapters(id, course_id, title, position)
exercises(id, lesson_id, difficulty, statement, correction)
quizzes(id, lesson_id, time_limit)
submissions(id, quiz_id, user_id, score, submitted_at)
documents(id, source_type, license, storage_key, validation_status)
ai_conversations(id, user_id, mode, context_scope)
ai_messages(id, conversation_id, role, content, citations)
reports(id, reporter_id, resource_type, resource_id, category, status)
audit_logs(id, actor_id, action, resource_type, resource_id, created_at)
```

Les données mineurs doivent être minimisées, isolées par tenant et soumises aux règles de consentement, conservation, export et suppression applicables.

## Rôles et permissions

| Rôle | Capacités principales |
| --- | --- |
| Super Admin | tenants, sécurité, rôles, paramètres globaux |
| Admin pédagogique | niveaux, programmes, contenus, validation |
| Modérateur | signalements, messages, sanctions, appels |
| Directeur | données de son établissement et statistiques agrégées |
| Enseignant | cours, exercices, quiz, devoirs et élèves autorisés |
| Auteur/Relecteur | brouillons et revue éditoriale selon permission |
| Parent | enfants explicitement autorisés, progression et alertes |
| Élève/Étudiant | contenus autorisés, travaux, résultats et notes propres |
| Support | tickets sans accès aux secrets ni données non nécessaires |

Toutes les permissions sont vérifiées côté API avec RBAC et filtrage `tenant_id`; masquer un bouton ne constitue pas un contrôle d'accès.

## EDU AI + RAG

```text
Documents validés -> extraction/OCR -> nettoyage -> chunks
                  -> embeddings -> pgvector
Question + contexte apprenant -> retrieval filtré niveau/tenant/source
                  -> garde-fous -> modèle fournisseur -> réponse + citations
```

La passerelle IA expose une interface commune (`answer`, `explain`, `generate_exercise`, `grade_answer`). Les instructions système, le contexte récupéré et la question utilisateur restent séparés. Un document récupéré est une source, jamais une instruction. Une réponse sans source fiable doit le dire explicitement et peut être signalée.

Modes MVP à venir : `expliquer`, `réviser`, `examinateur`, `correcteur`, `générateur`, `coach`. Chaque mode doit être évalué sur exactitude, niveau scolaire, citations, sécurité et coût avant activation.

## Phases de développement

1. **MVP livré** : authentification, catalogue, leçon, quiz, correction, progression, page web et OpenAPI.
2. **CMS/RBAC** : workflow brouillon → revue → validation → publication, administration des programmes et établissements.
3. **Examens et bibliothèque** : sujets, durée, corrections, droits, filtres et certificats.
4. **EDU AI** : ingestion documentaire, RAG, citations, limites, signalement et suite d'évaluation.
5. **Protection et multi-tenant** : parents, consentements, modération, audit, isolation d'établissement.
6. **Offline et mobile** : PWA, cache, synchronisation différée puis client Flutter.
7. **Production** : PostgreSQL, Redis, stockage objet, observabilité, sauvegardes chiffrées, CI/CD et tests de charge.

## Critères de sortie MVP

Un élève peut s'inscrire, consulter une matière et une leçon, répondre au quiz, voir une correction, puis retrouver son score dans sa progression. Les tests automatisés couvrent ce parcours et l'API publie son contrat OpenAPI à `/docs`.