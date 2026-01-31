# Browser Agent Backend

A FastAPI service that scrapes user complaints from various sources using [Stagehand](https://docs.stagehand.dev/) by Browserbase.

## Setup

1. Install dependencies with uv:

```bash
cd backend
uv sync
```

2. Set environment variables (create a `.env` file in the backend folder):

```bash
# backend/.env
BROWSERBASE_API_KEY=your-browserbase-api-key
BROWSERBASE_PROJECT_ID=your-browserbase-project-id
MODEL_API_KEY=sk-your-openai-api-key
```

3. Run the server:

```bash
uv run uvicorn main:app --reload
```

## API Usage

### Scrape Complaints

```bash
curl -X POST http://localhost:8000/scrape \
  -H "Content-Type: application/json" \
  -d '{
    "product_name": "joplin",
    "subreddit": "joplinapp",
    "max_posts": 20,
    "sort_by": "new"
  }'
```

**Request Body:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `product_name` | string | required | Name of the product to search for |
| `subreddit` | string | required | Subreddit to scrape (without r/ prefix) |
| `max_posts` | int | 20 | Maximum posts to scrape (1-100) |
| `sort_by` | string | "new" | Sort order: "new", "hot", or "top" |

**Response:**

```json
[
  {
    "id": "a1b2c3d4e5f6g7h8",
    "text": "Sync keeps failing with Dropbox...",
    "source": "reddit",
    "url": "https://reddit.com/r/joplinapp/comments/abc123",
    "timestamp": "2026-01-31T10:30:00Z",
    "title": "Sync keeps failing with Dropbox",
    "author": "frustrated_user"
  }
]
```

### Health Check

```bash
curl http://localhost:8000/health
```

## Adding New Sources

To add support for new sources (GitHub, Discourse, etc.), implement the `BaseScraper` protocol:

```python
from backend.scrapers.base import BaseScraper
from backend.models import Complaint, ScrapeConfig

class GitHubScraper(BaseScraper):
    @property
    def source_name(self) -> str:
        return "github"

    async def scrape(self, config: ScrapeConfig) -> list[Complaint]:
        # Implementation here
        ...
```

