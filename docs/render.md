# Render deployment and upstream updates

`master` mirrors `akhilnarang/vlrgg-scraper:master`. Keep deployment changes on `dbless`, and make `dbless` the fork's default branch. Render deploys `dbless` so an upstream mirror update cannot replace the stateless application.

## Create the web service

Create a Render Blueprint from this fork and select `render.yaml` on `dbless`, or create a Python web service with these settings:

| Setting | Value |
| --- | --- |
| Branch | `dbless` |
| Python | `PYTHON_VERSION=3.14.7` |
| uv | `UV_VERSION=0.12.5` |
| Build command | `uv sync --frozen --no-dev` |
| Start command | `.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1` |
| Health check | `/health` |
| Auto-deploy | On commit |

The default installation serves the scraping API without PostgreSQL, Redis, Firebase, or API credentials. Leave `ENABLE_DATABASE`, `ENABLE_CACHE`, `ENABLE_ID_MAPPING`, and `ENABLE_LIVE_PUSH` disabled. `/health` is public and returns `{"status":"ok"}` after the application starts. Match starts are converted to UTC. Keep `DETECT_SOURCE_TIMEZONE=true` so the service detects the zone VLR renders for its outbound location. One representative detail request calibrates rendered-only lists, and all endpoints share that observation for the HTTP client's lifetime. Machine timestamps need no calibration. If VLR provides no usable source-zone evidence, the affected request fails instead of returning guessed timestamps.

For a verified manual source zone, set `DETECT_SOURCE_TIMEZONE=false` and `TIMEZONE` to its IANA name, such as `Asia/Singapore`. `TIMEZONE` describes VLR's rendered source clock rather than a calendar subscriber's display zone. With detection disabled, the default is `America/New_York`. Compare a known list match with its detail start after deployment before relying on a manual override.

The shared HTTP client spaces VLR request starts by `VLR_REQUEST_INTERVAL_SECONDS`, which defaults to one second. Concurrent requests to different API endpoints use the same pacing within the single worker. Additional worker processes or service instances each have their own pacing. This courtesy setting does not establish a permitted VLR request rate.

Render's free web service sleeps after 15 minutes without inbound traffic. The next request can take about a minute while it starts. A scheduled calendar fetch should allow for that cold start. The service stores no required local state. A paid web instance can remove the idle sleep without adding a database.

The Dockerfile uses the same production dependency set and one Uvicorn worker. It listens on `PORT`, defaulting to `8000`, and starts the installed environment directly instead of resolving dependencies during startup. Optional database, push, and agent features require their corresponding extras and configuration as described in the README.

Render provisions resources only when the Blueprint or service is created in the dashboard. After the initial setup, a commit that reaches `dbless` triggers deployment. A direct manual push triggers Render, so validate changes before pushing them.

## Upstream synchronisation

Fork maintenance runs centrally outside this repository. It integrates upstream into `dbless`, verifies the scraper and calendar together, updates the upstream mirror, and checks the Render deployments after publication.

## Optional Redis deployments

The default service does not cache responses in Redis. Before updating a separate deployment that enables Redis caching, compare its cached models with the deployed version and purge that deployment's application cache if the schema changed. See [Caching](caching.md) for the affected keys.
