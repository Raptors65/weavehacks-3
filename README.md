# Beacon

**Turn user feedback into actionable code changes, automatically.**

Beacon scrapes user signals from Reddit (and other sources), clusters similar feedback into topics, and uses AI to identify actionable items like bugs, feature requests, and UX issues. These get turned into tasks for an autonomous coding agent to resolve.

## How It Works

```
Signal → Topic → Task → Code Fix
```

1. **Scrape** - Collect user feedback from Reddit, forums, GitHub issues
2. **Deduplicate** - Hash-based deduplication to avoid processing duplicates
3. **Cluster** - Group similar signals into topics using semantic embeddings
4. **Classify** - LLM identifies actionable topics (bugs, features, UX) → becomes a Task
5. **Resolve** - Coding agent works on prioritized tasks

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Reddit    │────▶│   Ingest    │────▶│   Cluster   │────▶│  Classify   │
│   Scraper   │     │  (dedupe)   │     │  (embed)    │     │   (LLM)     │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
                                                                   │
                                                                   ▼
                                                            ┌─────────────┐
                                                            │   Coding    │
                                                            │   Agent     │
                                                            └─────────────┘
```

## Quick Start

```bash
# Start Redis
docker compose up -d

# Install dependencies
cd backend
uv sync

# Run the server
uv run uvicorn main:app --reload
```

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `POST /scrape` | Scrape signals from Reddit |
| `POST /scrape/web` | Scrape any URL using Browserbase |
| `POST /ingest` | Ingest signals (dedupe + queue for embedding) |
| `GET /topics` | List clustered topics |
| `GET /topics/{id}` | Get a specific topic |

## Useful Commands for Development

- Flush Redis: `docker exec -it weavehacks-redis redis-cli FLUSHALL`
- Ingest + scrape:
```bash
curl -s -X POST "http://localhost:8000/ingest" \
  -H "Content-Type: application/json" \
  -d "$(curl -s -X POST "http://localhost:8000/scrape" \
    -H "Content-Type: application/json" \
    -d '{"product_name": "joplin", "subreddit": "joplinapp", "max_posts": 5}')" | jq
```
- Topics (clustered signals): `curl http://localhost:8000/topics | jq`
- Tasks (classified actionable topics): `curl http://localhost:8000/tasks | jq`
- Create GitHub issue: `curl -X POST http://localhost:8000/tasks/{task_id}/create-issue | jq`
- Run fix agent: `curl -X POST http://localhost:8000/tasks/{task_id}/fix | jq`
