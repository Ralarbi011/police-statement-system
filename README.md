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

## Project setup (local development)

These steps set up a copy of the system on your own computer for development, testing or training. For a live server, see [Production deployment](#production-deployment-summary).

### Prerequisites

| Requirement | Version | Check with |
|---|---|---|
| Python | 3.12 or 3.13 | `python --version` |
| Git | any recent | `git --version` |
| A modern browser | Chrome, Edge or Firefox | |

PostgreSQL is **not** needed for local development; the system uses a SQLite file automatically.

### 1. Get the code

```bash
git clone https://github.com/Ralarbi011/police-statement-system.git
cd police-statement-system
```

### 2. Create and activate a virtual environment

**Windows (PowerShell):**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```
If PowerShell says *"running scripts is disabled"*, run this once, then activate again:
```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

**Linux / macOS:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

You should now see `(.venv)` at the start of the terminal prompt. Activate the environment again every time you open a new terminal.

### 3. Install the dependencies

```bash
pip install -r requirements.txt
```

### 4. Create the `.env` configuration file

Generate a secret key:
```bash
python -c "import secrets; print(secrets.token_urlsafe(50))"
```

Create a file named `.env` in the project folder (next to `manage.py`) containing:
```ini
DEBUG=True
SECRET_KEY=paste-the-generated-key-here
ALLOWED_HOSTS=localhost,127.0.0.1
```

`.env` is ignored by git. Never commit it. (`.env.example` lists every available setting; it is set up for production, so don't copy it unchanged for local use.)

### 5. Create the database

```bash
python manage.py migrate
```

### 6. Create demo accounts (optional, development only)

```bash
python manage.py seed_demo --password "Choose-A-Demo-Pass"
```

This creates a **Demo Police Station** and one account per role, all with the password you chose. It refuses to run when `DEBUG` is off.

| Username | Role |
|---|---|
| `admin` | Super Administrator |
| `commander` | Station Commander |
| `investigator` | Investigator |
| `frontdesk` | Front Desk / Charge Office |
| `auditor` | Auditor / Prosecutor (read-only) |

To create your own Super Administrator instead, run `python manage.py create_superadmin <username>`.

### 7. Run the development server

```bash
python manage.py runserver
```

| Who | Sign in at |
|---|---|
| Officers (Commander, Investigator, Front Desk, Auditor) | http://127.0.0.1:8000/accounts/login/ |
| Super Administrator | http://127.0.0.1:8000/system-admin/ |

Press **Ctrl + C** in the terminal to stop the server. If port 8000 is busy, use `python manage.py runserver 8001`.

### 8. Run the tests

```bash
python manage.py test           # all 21 tests
python manage.py test -v 2      # with the name of each test
python manage.py check          # Django configuration check
```

### Common setup problems

| Problem | Solution |
|---|---|
| `ImproperlyConfigured: Environment variable SECRET_KEY is required` | `.env` is missing or not in the project folder, or `DEBUG` is not `True`. Repeat step 4. |
| `No module named 'django'` | The virtual environment is not active. Repeat the activate command in step 2. |
| Officer login says *"…correct username and password for a staff account"* | You are on the administrator page. Officers sign in at `/accounts/login/`. |
| *"Account temporarily locked"* | Too many failed sign-ins. Run `python manage.py axes_reset`. |
| *"CSRF verification failed"* | The page was left open while signing in/out in another tab. Refresh (F5) and try again. |
| You want to start again with an empty database | Stop the server, then run `python manage.py flush`, followed by step 6. |

### Project structure

```
accounts/    users, roles, stations, sign-in, management commands
records/     people, cases, statements, attachments, access rules, officer screens, tests
audit/       append-only audit log and sign-in logging
config/      settings and URL configuration
templates/   HTML pages
static/      CSS, JavaScript (signature pad) and locally hosted Bootstrap
```

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
