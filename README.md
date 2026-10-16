# VLR.gg Scraper

An unofficial FastAPI-based scraper for [vlr.gg](https://www.vlr.gg), providing Valorant esports data in a machine-readable JSON format.

The `dbless` branch runs as a stateless scraping API. Its default installation needs no PostgreSQL, Redis service, Firebase credentials, or environment variables. It fetches VLR data on request and retains no scraped history or subscriptions. Database-backed features remain available through optional dependencies and explicit configuration.

## Features

- **Comprehensive Data**: Scrapes events, matches, teams, players, rankings, standings, and news from vlr.gg
- **RESTful API**: FastAPI-powered endpoints with automatic OpenAPI documentation
- **Caching**: Redis-based caching for improved performance
- **Live match updates**: Optional APNs Live Activities and direct FCM messages for matches that are running
- **Background Jobs**: Cron jobs for periodic data updates
- **Async Support**: Asynchronous HTTP requests for efficient scraping

## Documentation

The running server documents every endpoint at `/docs` (Swagger UI), `/redoc`, and
`/openapi.json`. The guides in `docs/` cover the rest:

- [API Reference](docs/api.md): authentication, live match updates, and errors
- [Architecture](docs/architecture.md): components, data flow, and deployment
- [Caching](docs/caching.md): Redis caching
- [Background Jobs](docs/cron.md): cron schedules
- [News Media](docs/news-media.md): news article content and media
- [Standings](docs/standings.md): VCT standings
- [Testing](docs/testing.md): test layout and commands
- [Render and upstream updates](docs/render.md): database-free deployment and fork maintenance

## Quick Start

### Prerequisites

- Python 3.14+
- [uv](https://astral.sh/uv) for dependency management

### Installation

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone and install dependencies
git clone <repo-url>
cd vlrgg-scraper
uv sync --frozen
```

### Development

```bash
# Run development server with auto-reload
uv run fastapi dev

# Access API docs at http://localhost:8000/docs
# Access API at http://localhost:8000/api/v1/
```

### Testing

```bash
uv run pytest -m "not live_golden and not live_health"
```

Live checks against vlr.gg and more commands are in [docs/testing.md](docs/testing.md).

## Configuration

Environment variables (see `app/core/config.py`):

- `API_KEYS`: Optional JSON object mapping client names to bearer tokens. When empty, scraping endpoints are public. `/health` remains public.
- `REDIS_HOST`: Redis server host when a Redis-backed feature is enabled (default `localhost`)
- `REDIS_PASSWORD`: Optional Redis password
- `ENABLE_CACHE`: Cache VLR responses in Redis and run the cache crons (default `false`)
- `ENABLE_ID_MAPPING`: Resolve team and event IDs in match lists through Redis; requires `ENABLE_CACHE` (default `false`). Favorites and player ingestion also require `ENABLE_DATABASE`.
- `ENABLE_DATABASE`: Enable PostgreSQL startup, migrations, stored rankings, and database-backed features (default `false`). Install `uv sync --frozen --extra database` and set `DATABASE_URL` first.
- `ENABLE_LIVE_PUSH`: Enable live-push jobs and client endpoints (default `false`). Requires `uv sync --frozen --extra push`, `ENABLE_DATABASE`, and `API_KEYS`.
- `APNS_CREDENTIALS_FILE`: Path to the APNs credential JSON file
- `DATABASE_URL`: PostgreSQL connection URL, required only with `ENABLE_DATABASE=true`, using the `postgresql+asyncpg://` scheme
- `INTERNAL_API_KEY`: Optional key exposing internal cache endpoints when ID mapping is enabled
- `TIMEZONE`: Source timezone for rendered dates without an explicit offset or machine timestamp (default `America/New_York`). Machine timestamps are interpreted independently of the host's location.
- `GOOGLE_APPLICATION_CREDENTIALS`: Path to Firebase credentials (for notifications)

PostgreSQL initialization and Alembic migrations run only with `ENABLE_DATABASE=true`. The default API omits favorites, client tokens, live push, and database-backed `/api/v2/rankings` routes. Enabling Redis caching alone does not ingest PostgreSQL history. See [docs/postgres.md](docs/postgres.md) for optional database setup and backups.

The optional question-answering endpoint requires `uv sync --frozen --extra agent` and `LLM_API_KEY`. It can query the stateless scraper without a database. Its optional rate limiter requires Redis.

## Deployment

### Docker

```bash
# Build image
docker build -t vlrgg-scraper .

# Run container
docker run -p 8000:8000 vlrgg-scraper
```

### Production

```bash
# First install: sync dependencies, install and start the systemd user service
./scripts/install-systemd-user.sh

# Later deploys: pull and restart; purge the app cache first if a cached schema changed
./scripts/deploy.sh
```

See [Architecture: Deployment](docs/architecture.md#deployment) for how the service runs.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make changes with tests
4. Submit a pull request

## License

This project is for educational purposes only. Respect vlr.gg's terms of service and rate limits.

## Contact

For questions or issues: [me@akhilnarang.dev](mailto:me@akhilnarang.dev)
