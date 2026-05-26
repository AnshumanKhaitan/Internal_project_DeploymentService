# Anti Gravity Deployments

Internal deployment platform (FastAPI + Next.js).

## Run locally (no Docker for the app)

**Requirements:** Node 20+, Python 3.11+, Docker daemon (only for building/running uploaded apps — not for running this UI).

```bash
chmod +x scripts/dev.sh

# Both services
./scripts/dev.sh

# Or separate terminals:
./scripts/dev.sh backend   # http://localhost:8000
./scripts/dev.sh frontend  # http://localhost:3000
```

1. Open **http://localhost:3000**
2. API docs: **http://localhost:8000/docs**

### First-time setup

```bash
# Backend
cd backend
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env

# Frontend
cd frontend
npm ci
cp .env.local.example .env.local
```

### Environment

| Variable | Default | Notes |
|----------|---------|--------|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Frontend → backend (`.env.local`) |
| `UPLOAD_DIR` | `backend/data/uploads` | Extracted ZIP workspaces |
| `DATABASE_URL` | *(unset)* | Uses SQLite `backend/anti_gravity.db`; set for Postgres |

### Docker Compose (optional)

To run the packaged stack in containers instead:

```bash
docker compose up -d
```

Use either local dev **or** Compose — not both on the same ports.
