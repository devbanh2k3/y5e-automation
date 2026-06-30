# YouTube AI Automation

> Fully automated YouTube channel management powered by AI agents. From trending topic discovery to video upload — zero manual intervention.

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green.svg)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-blue.svg)](https://www.postgresql.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## Overview

YouTube AI Automation is a multi-agent pipeline that autonomously creates, renders, and publishes YouTube videos. Each step — topic generation, research, fact-checking, scriptwriting, image sourcing, music selection, video rendering, thumbnail creation, and upload — is handled by a specialised AI agent.

### Key Features

- **10+ specialised AI agents** working in concert
- **Fully async** Python 3.12 with `asyncio`, `httpx`, `asyncpg`
- **Remotion-powered** video rendering (React/TypeScript)
- **YouTube Data API v3** integration with resumable uploads
- **Automated analytics** with feedback loops (low CTR → new thumbnail)
- **Telegram notifications** at every pipeline stage
- **n8n workflow automation** for scheduling and triggers
- **RESTful API** for external integrations

---

## Architecture

```mermaid
graph TB
    subgraph "API Layer"
        API["FastAPI Server<br/>:8000"]
    end

    subgraph "Orchestration"
        PIPE["Pipeline Orchestrator"]
        QUEUE["Redis Queue"]
    end

    subgraph "AI Agents"
        TA["Topic Agent"]
        RA["Research Agent"]
        FCA["Fact-Check Agent"]
        SA["Script Agent"]
        IA["Image Agent"]
        MA["Music Agent"]
        VA["Video Agent"]
        SHA["Shorts Agent"]
        THA["Thumbnail Agent"]
        UA["Upload Agent"]
        AA["Analytics Agent"]
    end

    subgraph "External Services"
        AI["OpenAI / GPT-4o"]
        YT["YouTube Data API v3"]
        TG["Telegram Bot API"]
    end

    subgraph "Infrastructure"
        DB["PostgreSQL 16"]
        RD["Redis 7"]
        RE["Remotion Engine<br/>(Node.js)"]
    end

    API --> QUEUE --> PIPE
    PIPE --> TA --> RA --> FCA --> SA
    SA --> IA & MA
    IA & MA --> VA --> SHA --> THA --> UA
    PIPE --> AA

    TA & RA & FCA & SA & IA & THA --> AI
    UA & AA --> YT
    PIPE --> TG
    TA & RA & SA & UA & AA --> DB
    QUEUE --> RD
    VA & SHA --> RE
```

---

## Pipeline Flow

```mermaid
sequenceDiagram
    participant User
    participant API
    participant Pipeline
    participant Agents
    participant YouTube

    User->>API: POST /api/pipeline/start
    API->>Pipeline: Enqueue job
    Pipeline->>Agents: 1. TopicAgent.run()
    Pipeline->>Agents: 2. ResearchAgent.run()
    Pipeline->>Agents: 3. FactCheckAgent.run()
    Note over Pipeline: Abort if >50% facts rejected
    Pipeline->>Agents: 4. ScriptAgent.run()
    par Parallel
        Pipeline->>Agents: 5. ImageAgent.run()
        Pipeline->>Agents: 6. MusicAgent.run()
    end
    Pipeline->>Agents: 7. VideoAgent.run()
    Pipeline->>Agents: 7b. ShortsAgent.run()
    Pipeline->>Agents: 8. ThumbnailAgent.run()
    Pipeline->>Agents: 9. UploadAgent.run()
    Agents->>YouTube: Resumable Upload
    YouTube-->>Agents: youtube_id
    Pipeline-->>User: ✅ Telegram notification
```

---

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| **Python** | 3.12+ | Backend runtime |
| **Node.js** | 18+ | Remotion video engine |
| **Docker** | 24+ | PostgreSQL, Redis, n8n |
| **Docker Compose** | v2+ | Service orchestration |
| **FFmpeg** | 6+ | Video processing |

---

## Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/your-org/youtube-ai-automation.git
cd youtube-ai-automation
```

### 2. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` and fill in your API keys:

```env
# Required
PRIMARY_API_KEY=sk-your-openai-key
YOUTUBE_API_KEY=AIzaSy-your-youtube-api-key
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHI...
TELEGRAM_CHAT_ID=your-chat-id

# Optional (for AI fallback)
FALLBACK_API_KEY=sk-your-fallback-key
```

### 3. Start Infrastructure

```bash
docker-compose up -d
```

This starts:
- **PostgreSQL 16** on port `5432` (auto-runs schema migration)
- **Redis 7** on port `6379`
- **n8n** on port `5678`
- **API server** on port `8000`
- **Pipeline worker** consuming Redis jobs
- **Telegram bot** for remote production commands
- **Production worker** for Telegram-created video tasks

### 4. Install Video Engine

```bash
cd video_engine
npm install
cd ..
```

### 5. Install Python Dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Native Full HD Renderer

The optional host-native runner keeps the existing 1920x1080 landscape
template while adding resumable chunk rendering and VideoToolbox/NVENC with
automatic `libx264` fallback.

```bash
python3 scripts/native_render_runner.py --check
```

Keep `NATIVE_RENDER_ENABLED=false` until the machine-specific benchmark and
visual smoke pass. See `docs/production-server-setup-full.md` for macOS and
Windows NVIDIA setup.

### 6. Set Up YouTube OAuth

To upload videos, you need OAuth2 credentials:

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project and enable the **YouTube Data API v3**
3. Create OAuth 2.0 credentials (Desktop application)
4. Download the credentials and run the auth setup
5. Save the resulting `youtube_token.json` to `./output/youtube_token.json`

The token file should contain:
```json
{
  "access_token": "ya29.xxx",
  "refresh_token": "1//xxx",
  "client_id": "xxx.apps.googleusercontent.com",
  "client_secret": "xxx",
  "expires_at": 1234567890
}
```

### 7. Run the Pipeline

**Via CLI:**
```bash
python -m agents.pipeline science vi
```

**Via API:**
```bash
curl -X POST http://localhost:8000/api/pipeline/start \
  -H "Content-Type: application/json" \
  -d '{"category": "science", "language": "vi", "count": 1}'
```

## Production Foundation Services

The API and worker run as separate services.

- `api` accepts requests and enqueues jobs.
- `worker` consumes Redis jobs and runs the pipeline.
- `n8n` should be used for scheduling, webhooks, and notifications, not for core pipeline logic.

Start all services:

```bash
docker compose up -d
```

Start a pipeline job:

```bash
curl -X POST http://localhost:8000/api/pipeline/start \
  -H "Content-Type: application/json" \
  -d '{"category": "science", "language": "vi", "count": 1}'
```

Check job status:

```bash
curl http://localhost:8000/api/jobs/<job_id>
```

## Production Control Plane

Use `/api/health` for lightweight liveness and `/api/ready` before schedulers start work.

```bash
curl http://localhost:8000/api/ready
```

Job operations:

```bash
curl http://localhost:8000/api/jobs
curl http://localhost:8000/api/jobs/<job_id>
curl -X POST http://localhost:8000/api/jobs/<job_id>/retry
curl http://localhost:8000/api/queues
```

### Smoke Mode

Use smoke mode before production runs to validate API, Redis, worker, and pipeline wiring without paid AI calls, heavy rendering, or YouTube upload.

```bash
curl -X POST http://localhost:8000/api/pipeline/start \
  -H "Content-Type: application/json" \
  -d '{"category": "Science", "language": "vi", "count": 1, "mode": "smoke"}'
```

Then inspect the result summary:

```bash
curl http://localhost:8000/api/jobs/<job_id>
```

### Local Render Mode

Use local render mode to validate the Python-to-video contract and produce a real Remotion MP4 without publishing to YouTube. Run `npm install` in `video_engine/` before using this mode on a fresh machine.

```bash
curl -X POST http://localhost:8000/api/pipeline/start \
  -H "Content-Type: application/json" \
  -d '{"category": "Science", "language": "vi", "count": 1, "mode": "local_render"}'
```

Inspect the job result:

```bash
curl http://localhost:8000/api/jobs/<job_id>
```

The `result_summary` includes `file_path`, `duration_sec`, `topic_id`, `video_id`, and `fallback_used`. The rendered MP4 is written under `output/topics/<topic_id>/final_video.mp4` by default.

For the celebrity MVP content path, use:

```bash
curl -X POST http://localhost:8000/api/pipeline/start \
  -H "Content-Type: application/json" \
  -d '{"category": "Celebrity", "language": "vi", "count": 1, "mode": "local_render"}'
```

This path uses `ContentAgent` and `content_contract_v2` to produce data-comparison celebrity scenes, voiceover text, thumbnail prompt, YouTube title, description, and tags before rendering. It keeps the existing timeline video template and changes only the content fed into that template.

Celebrity local renders use the strict `RealImageAgent` path before Remotion rendering. The agent accepts only verified real images from Wikimedia/Wikipedia-style sources with source URL, image URL, license, attribution, and person-name metadata checks. The existing timeline video template is not changed; verified images only replace each card's `imagePath`. If required images are missing or unverified, the celebrity render path must not silently render a production-looking MP4 with placeholders.

The image gate also performs deterministic identity and content checks. Loose token matches are not enough: a result for `John Jay` must not pass for `Jay-Z`, non-photo media such as PDFs, books, logos, and fan art are rejected, and group photos are marked for review instead of being used in strict renders.

### Review Gate

Celebrity local renders create a pending review artifact before any upload step is allowed.

```bash
curl http://localhost:8000/api/reviews
curl http://localhost:8000/api/reviews/<review_id>
```

Approve or reject a pending review:

```bash
curl -X POST http://localhost:8000/api/reviews/<review_id>/approve \
  -H "Content-Type: application/json" \
  -d '{"notes": "ready to upload"}'

curl -X POST http://localhost:8000/api/reviews/<review_id>/reject \
  -H "Content-Type: application/json" \
  -d '{"notes": "rewrite hook and thumbnail"}'
```

Review artifacts are stored under `output/reviews/` by default.

For production, set:

```env
APP_ENV=production
PRIMARY_API_KEY=...
YOUTUBE_API_KEY=...
DATABASE_URL=...
REDIS_URL=...
```

---

## API Endpoints

### System

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | Lightweight service health |
| `GET` | `/api/ready` | Dependency readiness for DB, Redis, storage, and production config |
| `GET` | `/api/stats` | System-wide statistics (topics, videos, costs) |
| `GET` | `/api/jobs` | List recent queue jobs |
| `GET` | `/api/jobs/{job_id}` | Get queue job status and retry metadata |
| `POST` | `/api/jobs/{job_id}/retry` | Requeue a failed job |
| `GET` | `/api/queues` | Queue lengths and recent job status counts |

### Pipeline

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/pipeline/start` | Queue a new pipeline run |
| `GET` | `/api/pipeline/status/{topic_id}` | Get pipeline status for a topic |

#### Start Pipeline Request

```json
{
  "category": "science",
  "language": "vi",
  "count": 1
}
```

#### Start Pipeline Response

```json
{
  "job_id": "pipeline:abc123",
  "message": "Pipeline queued for category 'science' (1 topics)."
}
```

### Channels

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/channels/analyze` | Register and analyze a YouTube channel |
| `GET` | `/api/channels` | List all reference channels |

---

## Configuration Reference

All configuration is via environment variables (or `.env` file):

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql://ytbot:ytbot@localhost:5432/youtube_automation` | PostgreSQL connection string |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection string |
| `PRIMARY_API_BASE` | `https://api.openai.com/v1` | Primary AI endpoint URL |
| `PRIMARY_API_KEY` | — | Primary AI API key |
| `PRIMARY_MODEL` | `gpt-4o` | Primary AI model name |
| `FALLBACK_API_BASE` | `https://api.openai.com/v1` | Fallback AI endpoint URL |
| `FALLBACK_API_KEY` | — | Fallback AI API key |
| `FALLBACK_MODEL` | `gpt-4o-mini` | Fallback AI model name |
| `TELEGRAM_BOT_TOKEN` | — | Telegram bot token |
| `TELEGRAM_CHAT_ID` | — | Telegram chat/group ID for legacy notifications |
| `PUBLIC_BASE_URL` | `http://localhost:8000` | Public API URL used by Telegram review buttons |
| `YOUTUBE_API_KEY` | — | YouTube Data API v3 key |
| `STORAGE_PATH` | `./output` | Local storage directory |
| `LOG_LEVEL` | `INFO` | Logging level |

---

## Telegram Remote Production Control

Telegram remote control uses a whitelist in Postgres, not daily quotas. Each
`/create` command creates a batch and splits it into one task per video. The
worker claims tasks with fair round-robin scheduling by Telegram user, so two
users creating 10 videos each are interleaved instead of one user blocking the
other.

Allow users:

```bash
python3 scripts/telegram_user_admin.py allow 123456789 --username alice --role producer
python3 scripts/telegram_user_admin.py allow 987654321 --username bob --role producer
```

Find the correct chat id after sending `/start` to the bot:

```bash
python3 scripts/telegram_chat_id.py --timeout 10
```

Run the Telegram polling bot locally when not using Docker:

```bash
python3 scripts/telegram_remote_bot.py
```

The bot remembers the latest chat id for each whitelisted user when they send a
command. Production completion/failure notifications are sent back to that chat;
`TELEGRAM_CHAT_ID` is used as a fallback when no per-user chat id is known.
When a video is ready, the bot sends inline buttons for opening the MP4,
opening the Review UI, approving, or rejecting with common reasons. Set
`PUBLIC_BASE_URL` to a URL reachable from the device where you open Telegram;
`http://localhost:8000` is enough only on the same machine.

Process one fair-scheduled production task:

```bash
python3 scripts/process_production_task.py --once
```

Run the production worker continuously when not using Docker:

```bash
python3 scripts/process_production_task.py --loop --idle-sleep 10
```

Supported Telegram commands in v1:

```text
/start
/help
/create <count> [category] [language] [layout] [--duration seconds]
/status
/batches
```

Example:

```text
/create 1 celebrity en flag_hero --duration 90
```

V1 deliberately keeps YouTube upload out of Telegram. The remote flow is:
Telegram create -> fair task queue -> render -> pending review -> Review UI or
Telegram status.

For an existing database, apply the production-control migration first:

```bash
python3 scripts/apply_db_migrations.py
```

Or apply individual SQL files manually:

```bash
psql "$DATABASE_URL" -f db/migrations/2026-06-28-telegram-remote-production.sql
psql "$DATABASE_URL" -f db/migrations/2026-06-28-telegram-chat-routing.sql
```

---

## Project Structure

```
youtube_ai_automation/
├── agents/                     # AI agent implementations
│   ├── __init__.py
│   ├── base_agent.py           # Abstract base class for all agents
│   ├── topic_agent.py          # Trending topic discovery & scoring
│   ├── research_agent.py       # Web research & data collection
│   ├── fact_check_agent.py     # Cross-source fact verification
│   ├── script_agent.py         # Narration script generation
│   ├── image_agent.py          # Image sourcing & generation
│   ├── music_agent.py          # Background music selection
│   ├── video_agent.py          # Remotion video rendering
│   ├── shorts_agent.py         # Short-form clip generation
│   ├── thumbnail_agent.py      # Custom thumbnail creation
│   ├── upload_agent.py         # YouTube upload with SEO metadata
│   ├── analytics_agent.py      # Performance tracking & feedback
│   └── pipeline.py             # Full pipeline orchestrator
│
├── api/                        # FastAPI HTTP server
│   ├── __init__.py
│   ├── main.py                 # App setup, lifespan, core routes
│   └── routes/                 # Additional route modules
│
├── core/                       # Shared infrastructure
│   ├── __init__.py
│   ├── ai_client.py            # Unified AI client (primary + fallback)
│   ├── config.py               # Pydantic settings from env vars
│   ├── cost_tracker.py         # API usage & cost monitoring
│   ├── database.py             # Async PostgreSQL connection pool
│   ├── notifier.py             # Telegram notification helpers
│   ├── queue.py                # Redis job queue
│   ├── retry.py                # Async retry with exponential backoff
│   └── storage.py              # File storage manager
│
├── db/
│   └── schema.sql              # Full PostgreSQL schema (12 tables)
│
├── video_engine/               # Remotion video renderer
│   ├── package.json
│   ├── remotion.config.ts
│   └── src/                    # React components for video
│
├── n8n/                        # n8n workflow definitions
├── tests/                      # Test suite
├── assets/                     # Static assets
│
├── .env.example                # Environment variable template
├── docker-compose.yml          # Infrastructure services
├── Dockerfile                  # Python app container
├── requirements.txt            # Python dependencies
└── README.md                   # This file
```

---

## Database Schema

The PostgreSQL schema consists of 12 tables:

| Table | Purpose |
|-------|---------|
| `reference_channels` | YouTube channels analysed for strategy |
| `reference_videos` | Individual videos from reference channels |
| `topics` | Generated video topics with scores |
| `research_data` | Research data items per topic |
| `facts` | Fact-checked claims with verification status |
| `scripts` | Generated narration scripts |
| `assets` | Images, audio, and other media files |
| `videos` | Rendered video files and YouTube IDs |
| `shorts` | Short-form clips derived from videos |
| `analytics` | YouTube performance metrics over time |
| `api_usage` | AI API token consumption tracking |
| `pipeline_logs` | Per-step pipeline execution logs |

---

## Agent Details

### Upload Agent (`upload_agent.py`)

Handles the final publishing step:
- **OAuth2 token management** with automatic refresh
- **Resumable uploads** via YouTube Data API v3 (chunked, retry-safe)
- **AI-generated SEO metadata** (title, description, tags, category)
- **Chapter timestamps** auto-calculated from script sections
- **Thumbnail upload** for custom click-worthy images
- **Database updates** and Telegram success notifications

### Analytics Agent (`analytics_agent.py`)

Automated performance monitoring:
- **Batch stats collection** from YouTube (views, likes, comments)
- **Feedback rules**: low CTR → flag for thumbnail regeneration
- **Retention alerts**: low avg. watch time → improve intro hooks
- **Daily reports** sent via Telegram with best/worst performers
- Designed for future YouTube Analytics API integration (CTR, retention)

### Pipeline Orchestrator (`pipeline.py`)

Coordinates all 10+ agents:
- **Sequential execution** with dependency management
- **Parallel steps** for independent operations (images + music)
- **Per-step error handling** with detailed logging
- **Telegram notifications** at start, completion, and failure
- **CLI interface**: `python -m agents.pipeline <category> <language>`

---

## Scheduling with n8n

The n8n instance at `http://localhost:5678` can be configured to:

1. **Daily pipeline runs** — trigger `POST /api/pipeline/start` on a cron schedule
2. **Analytics collection** — run analytics agent daily at midnight
3. **Webhook triggers** — start pipelines from external events

Default n8n credentials: `admin` / `changeme`

## Multi-Channel YouTube Publishing

Each authorized Telegram user can connect multiple YouTube channels. Channel ownership is enforced in PostgreSQL, and the user must select a destination with `/channels` before every `/create` command. Approving a review queues a background resumable upload with the approved metadata and Public visibility.

### Google OAuth Setup

1. Enable YouTube Data API v3 in a Google Cloud project.
2. Configure an External OAuth consent screen and add test users while the app remains in Testing.
3. Create a Web application OAuth client.
4. In Cloudflare Dashboard, create a remotely managed tunnel named `youtube-automation-production`.
5. Publish `studio.veo3depzai.io.vn` to the Docker origin `http://api:8000`.
6. Copy only the tunnel token (`eyJ...`) into `.env`; never commit it.
7. Register this exact redirect URI in Google Cloud: `https://studio.veo3depzai.io.vn/api/youtube/oauth/callback`.
8. Generate the encryption key:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Set these values in `.env`:

```dotenv
YOUTUBE_UPLOAD_ENABLED=false
YOUTUBE_OAUTH_CLIENT_ID=...
YOUTUBE_OAUTH_CLIENT_SECRET=...
YOUTUBE_TOKEN_ENCRYPTION_KEY=...
PUBLIC_BASE_URL=https://studio.veo3depzai.io.vn
CLOUDFLARE_TUNNEL_TOKEN=eyJ...
```

Rebuild and start the services:

```bash
docker compose build db-migrate
docker compose up -d db-migrate api cloudflared telegram-bot production-worker youtube-upload-worker
./scripts/verify_named_tunnel.sh
docker compose logs -f youtube-upload-worker
```

Use `/channels` in Telegram, tap **Add channel**, complete Google consent, then select the channel before creating a batch. Keep `YOUTUBE_UPLOAD_ENABLED=false` until a disposable Private operator smoke confirms the exact destination channel. The approved production behavior is Public; enable it only after that check.

The Named Tunnel reconnects to the same hostname after Docker or server restarts. Cloudflare owns the DNS route; the application only requires the stable URL and tunnel token.

The upload worker streams MP4 chunks directly from the shared output volume. n8n receives no OAuth token and does not transfer video binaries.

---

## Development

### Running Tests

```bash
pytest tests/ -v
```

### Running the API Locally

```bash
uvicorn api.main:app --reload --port 8000
```

### Running a Single Agent

```python
import asyncio
from agents.upload_agent import UploadAgent

async def main():
    agent = UploadAgent()
    result = await agent.run(video_id=42)
    print(result)

asyncio.run(main())
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `YouTube token file not found` | Run OAuth2 setup and save `youtube_token.json` to `./output/` |
| `YouTube API quota exceeded` | Wait 24h or request quota increase in Google Cloud Console |
| `Database connection refused` | Ensure `docker-compose up -d` is running |
| `Remotion render fails` | Run `cd video_engine && npm install` and ensure FFmpeg is installed |
| `Telegram notifications not sending` | Verify `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env` |

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
