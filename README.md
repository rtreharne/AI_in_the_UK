# AI in the UK Workshop Timer

Live workshop control app for:
- student join and group/sector allocation
- timed section progression
- pitch-round timing and cues
- voting + feedback collection
- award reveal with confetti/audio

Built with Django and designed to run in Docker Compose.

## What This App Does

- Loads workshop sections from [`session_overview.md`](session_overview.md) and sectors from [`sectors.md`](sectors.md) via `seed_workshop_data`.
- Assigns students to balanced groups and mapped sectors.
- Provides facilitator controls (`Start`, `Pause`, `Back`, `Next`, `Join`, `Reset`, etc.).
- Shows timing/status on a shared display.
- Runs vote flow during **Vote and Feedback** and shows results in **Award**.
- Plays configured audio cues (`gong`, `edith`, `drumroll`, `kool`).

## Main URLs

- Display page: `http://localhost:8007/`
- Student join page: `http://localhost:8007/join`
- Student vote page: `http://localhost:8007/vote`
- Django admin: `http://localhost:8007/admin/`

## Quick Start (Docker Compose)

1. Start the app:

```bash
docker compose up --build
```

2. Open `http://localhost:8007/`.
3. Unlock facilitator controls with PIN (`WORKSHOP_CONTROL_PIN`, default `1234` in `docker-compose.yml`).

Notes:
- `docker-compose.yml` runs `migrate` and `seed_workshop_data` on startup.
- The project directory is mounted into the container (`.:/app`), so files are shared between host and container.

## Local (Without Docker)

1. Create and activate a Python environment.
2. Install deps:

```bash
pip install -r requirements.txt
```

3. Run migrations and seed data:

```bash
python manage.py migrate
python manage.py seed_workshop_data
```

4. Start server:

```bash
python manage.py runserver
```

## Tests

Run:

```bash
python manage.py test
```

## Database Backup and Restore

Use Django fixtures for portable backups across machines.

### Backup (Docker Compose, PowerShell)

Use PowerShell backticks for continuation (not `\`):

```powershell
docker compose exec web python manage.py dumpdata `
  workshop.WorkshopSection `
  workshop.Sector `
  workshop.WorkshopSettings `
  workshop.WorkshopRun `
  workshop.StudentAssignment `
  workshop.WorkshopVote `
  --indent 2 `
| Out-File -Encoding utf8 workshop_backup.json
```

### Backup (Docker Compose, bash/zsh)

```bash
docker compose exec web python manage.py dumpdata \
  workshop.WorkshopSection \
  workshop.Sector \
  workshop.WorkshopSettings \
  workshop.WorkshopRun \
  workshop.StudentAssignment \
  workshop.WorkshopVote \
  --indent 2 > workshop_backup.json
```

### Restore (Docker Compose)

If `workshop_backup.json` is in the project root on host, it is visible inside container at `/app/workshop_backup.json`.

```bash
docker compose exec web python manage.py migrate
docker compose exec web python manage.py loaddata /app/workshop_backup.json
```

If you want to replace existing DB contents first:

```bash
docker compose exec web python manage.py flush --no-input
docker compose exec web python manage.py migrate
docker compose exec web python manage.py loaddata /app/workshop_backup.json
```

### Backup/Restore (Local Python)

Backup:

```bash
python manage.py dumpdata \
  workshop.WorkshopSection \
  workshop.Sector \
  workshop.WorkshopSettings \
  workshop.WorkshopRun \
  workshop.StudentAssignment \
  workshop.WorkshopVote \
  --indent 2 > workshop_backup.json
```

Restore:

```bash
python manage.py migrate
python manage.py loaddata workshop_backup.json
```

## Environment Variables

Common settings:
- `WORKSHOP_CONTROL_PIN`: facilitator unlock PIN
- `DJANGO_DEBUG`: `1` or `0`
- `DJANGO_ALLOWED_HOSTS`: comma-separated host list
- `SQLITE_PATH`: SQLite DB file path
- `TZ`: timezone (default `Europe/London`)

## Operational Notes

- `Reset Run` clears assignments and votes.
- Vote options are limited to sectors that actually had assigned group members in the current run.
- Award reveal sequence: drumroll -> winner reveal fade-in -> confetti + kool music (max 30s).
