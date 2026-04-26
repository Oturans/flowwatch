# FlowWatch

**Real-time observability for no-code AI workflows.**

Monitor your n8n and Make workflow executions, get instant alerts on failures, and track success rates — all in one place.

## Features

- 🔌 **Webhook Ingestion** — Receive events from n8n, Make, and custom sources
- 📊 **Dashboard** — Real-time stats and event history
- 🔔 **Slack Alerts** — Instant notifications on workflow failures
- 🔄 **Auto-Retry** — Configurable retry with exponential backoff
- 📈 **SSE Streaming** — Live updates without polling

## Architecture

```
┌─────────────────────────────────────────────────────┐
│   n8n / Make  ──── Webhooks ────►  FastAPI API       │
│                                             │        │
│                                      ┌─────┴─────┐  │
│                                      ▼           ▼  │
│                                 PostgreSQL    Redis │
│                                      │           │  │
│                                      └─────┬─────┘  │
│                                            │        │
│                                      ┌─────┴─────┐  │
│                                      ▼           ▼  │
│                                  Celery      Next.js│
│                                 (retry)    Dashboard │
└─────────────────────────────────────────────────────┘
```

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Git

### 1. Clone the repository

```bash
git clone https://github.com/Oturans/flowwatch.git
cd flowwatch
```

### 2. Start the stack

```bash
docker-compose up -d
```

### 3. Access the dashboard

- **Dashboard**: http://localhost:3000
- **API Docs**: http://localhost:8000/docs

## Configuration

### Environment Variables

Create `api/.env` for local development:

```env
DATABASE_URL=postgresql+asyncpg://flowwatch:pw@localhost:5432/flowwatch
DATABASE_URL_SYNC=postgresql+psycopg2://flowwatch:pw@localhost:5432/flowwatch
REDIS_URL=redis://localhost:6379/0
REDIS_BROKER=redis://localhost:6379/0
REDIS_RESULT_BACKEND=redis://localhost:6379/1
REDIS_RATE_LIMIT_DB=2
REDIS_PUBSUB_DB=3
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
```

### Adding a Webhook Source

```bash
curl -X POST http://localhost:8000/api/sources \
  -H "Content-Type: application/json" \
  -d '{
    "id": "my-n8n-workflow",
    "name": "User Onboarding",
    "signing_secret": "your-secret-here",
    "platform": "n8n",
    "alert_config": {
      "slack_webhook_url": "https://hooks.slack.com/..."
    }
  }'
```

### Sending Webhook Events

Point your n8n/Make webhook to:
```
POST http://localhost:8000/api/webhook/{source_id}
```

With JSON payload:
```json
{
  "workflow_id": "user-onboarding-v2",
  "run_id": "run-12345",
  "event_type": "completed",
  "status": "success",
  "payload": {"user_id": 123, "email": "user@example.com"},
  "duration_ms": 1500
}
```

## Development

### Local Setup

```bash
# API
cd api
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Worker (separate terminal)
celery -A app.celery_app worker -l info -c 4

# Dashboard
cd dashboard
npm install
npm run dev
```

### Running Tests

```bash
cd api
pytest tests/ -v
```

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend API | FastAPI (Python 3.12) |
| Database | PostgreSQL 16 |
| Cache/Queue | Redis 7 |
| Background Jobs | Celery |
| Frontend | Next.js 14 (App Router) |
| State Management | TanStack Query v5 |
| Styling | Tailwind CSS |

## Project Structure

```
flowwatch/
├── api/                    # FastAPI backend
│   ├── app/
│   │   ├── main.py        # FastAPI app entry
│   │   ├── celery_app.py # Celery configuration
│   │   ├── config.py      # Settings
│   │   ├── database.py   # DB connection
│   │   ├── models/       # SQLAlchemy models
│   │   ├── routes/       # API endpoints
│   │   ├── schemas/      # Pydantic schemas
│   │   └── tasks/        # Celery tasks
│   ├── alembic/          # Database migrations
│   ├── tests/            # pytest tests
│   └── requirements.txt
├── dashboard/             # Next.js frontend
│   ├── app/              # App Router pages
│   ├── components/       # React components
│   ├── lib/              # Utilities & API client
│   └── package.json
├── docker-compose.yml
└── README.md
```

## License

MIT © Oturans