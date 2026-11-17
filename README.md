# Police Statement Management System

A web application for recording, signing and managing statements taken at police
stations, with role-based access, tamper-evident statements and a full audit trail.

## Features

- **Roles:** Super Administrator, Station Commander, Investigator, Front Desk, Auditor/Prosecutor
- **People registry:** complainants, victims, witnesses and suspects, with duplicate-ID protection
- **Cases:** automatic case numbers (`STATIONCODE-YEAR-00001`), assignment, status workflow and an investigation diary
- **Statements:**
  - Caution for suspects; language and interpreter details
  - On-screen signatures for the person, officer, interpreter and independent witness
  - **Locked permanently once signed**, with a SHA-256 integrity check; corrections are made through *additional statements*
- **Print / PDF** in a formal A4 statement layout
- **Attachments:** documents, photos and audio/video, fingerprinted, never deletable, downloadable only by authorised users
- **Audit log** of every login, view, search, edit, sign, print and download; nobody can edit or delete it
- **Security:**
  - Account lockout after repeated failed logins
  - 30-minute idle logout
  - HTTPS enforced in production
  - Database triggers block tampering on PostgreSQL

## Who can do what

| Action | Super Admin | Commander | Investigator | Front Desk | Auditor |
|---|---|---|---|---|---|
| Manage users, stations, unlock accounts, view audit log | ✔ | | | | |
| See cases at own station | | all | assigned/own | all | forwarded/closed only |
| Open cases, register people, take statements | | ✔ | ✔ | ✔ | |
| Assign investigators | | ✔ | | | |
| Change status / close cases | | ✔ (all) | to "investigation"/"forwarded" | | |
| Print statements | | ✔ | ✔ | ✔ | ✔ |

The Super Administrator **cannot** read case content. This is deliberate.

## Local development

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -r requirements.txt
copy .env.example .env            # then set DEBUG=True and a SECRET_KEY
python manage.py migrate
python manage.py seed_demo --password "Choose-A-Demo-Pass"   # demo station + one user per role
python manage.py runserver
```

Open http://127.0.0.1:8000. The demo usernames are `admin`, `commander`, `investigator`, `frontdesk` and `auditor`.

Run the tests with `python manage.py test`.

## Production deployment (summary)

1. Install **PostgreSQL** and create a database and user. Set `DB_ENGINE=postgres` and the `DB_*` values in `.env`.
2. Set `DEBUG=False`, a long random `SECRET_KEY`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, and a `MEDIA_ROOT` outside the application folder.
3. Prepare the application:
   ```bash
   pip install -r requirements.txt
   python manage.py migrate
   python manage.py collectstatic --noinput
   python manage.py check --deploy
   python manage.py create_superadmin <username>
   ```
4. Run the app server:
   - Windows: `waitress-serve --listen=127.0.0.1:8000 config.wsgi:application`
   - Linux: `gunicorn`
5. Put the app server behind **IIS or nginx with HTTPS** (an internal CA certificate is fine). The proxy must send `X-Forwarded-Proto`.
6. Log in at `/system-admin/` as the Super Administrator. Create the stations, then create officer accounts.
7. **Backups:** take a nightly `pg_dump` and copy the `MEDIA_ROOT` folder. Store copies off-site, and test a restore regularly.

## Statement lifecycle

1. Open a case.
2. Add the person (search the registry first).
3. Choose **Take statement** and save a **draft**.
4. **Read over & sign**: capture the signatures and confirm.
5. The statement is **locked**, and its SHA-256 hash is stored.
6. Any later correction is made as an **Additional statement** linked to the original.

The statement page re-checks the hash every time it is opened. If the record has been altered outside the system, the page shows **INTEGRITY CHECK FAILED**.
