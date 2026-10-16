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

The default installation serves the scraping API without PostgreSQL, Redis, Firebase, or API credentials. Leave `ENABLE_DATABASE`, `ENABLE_CACHE`, `ENABLE_ID_MAPPING`, and `ENABLE_LIVE_PUSH` disabled. `/health` is public and returns `{"status":"ok"}` after the application starts. Machine match timestamps are converted to UTC. `TIMEZONE` only interprets rendered date and clock strings without machine timestamps or offsets; it is a source timezone, so do not set it to a calendar's display timezone. Its default is `America/New_York`. Check a known match from the deployed service against VLR before changing that fallback for the service's outbound location.

Render's free web service sleeps after 15 minutes without inbound traffic. The next request can take about a minute while it starts. A scheduled calendar fetch should allow for that cold start. The service stores no required local state. A paid web instance can remove the idle sleep without adding a database.

The Dockerfile uses the same production dependency set and one Uvicorn worker. It listens on `PORT`, defaulting to `8000`, and starts the installed environment directly instead of resolving dependencies during startup. Optional database, push, and agent features require their corresponding extras and configuration as described in the README.

Render provisions resources only when the Blueprint or service is created in the dashboard. After the initial setup, a commit that reaches `dbless` triggers deployment. A direct manual push can trigger Render before CI finishes, so use reviewed pull requests or the tested upstream integration workflow for changes that should be validated first.

## Enable upstream synchronisation

In the fork's GitHub settings:

1. Set the default branch to `dbless`.
2. Enable GitHub Actions for the fork if they are disabled.
3. Under **Actions → General → Workflow permissions**, allow GitHub Actions to create pull requests. The sync workflow requests repository contents and pull-request write access only in its preparation and promotion jobs.
4. Run **Actions → Sync upstream → Run workflow**, selecting `dbless`, to verify the initial setup.

The workflow runs every six hours and can also be started manually. It uses the repository's built-in `GITHUB_TOKEN`, with no personal access token or Render credential.

The update proceeds in this order:

1. Advance `master` to the upstream commit with a fast-forward-only reference update. If local commits make that impossible, stop and leave both branches intact.
2. Merge upstream into `sync/upstream`, and open or reuse its pull request into `dbless`.
3. Merge the current `dbless` commit into that integration branch. Conflicts stop the workflow and leave the pull request for manual resolution.
4. Run the reusable CI workflow against the exact integration commit. It checks the production installation without optional dependencies, the offline suite in base and all-extras environments, and the production container build.
5. After the checks pass, advance `dbless` to that exact tested commit using another fast-forward-only reference update. GitHub recognises the integrated pull request as merged when its head enters the default branch.

The separate CI call is deliberate: GitHub suppresses push-triggered workflows created with `GITHUB_TOKEN`, while bot-created pull-request runs can require manual approval. The sync workflow calls the same CI directly and waits for it before promotion, without depending on those additional runs.

Candidate code runs only in jobs with read-only repository access and no inherited secrets. The write-enabled jobs call GitHub's reference, merge, and pull-request APIs without checking out or executing candidate code. If the pull request changes after validation, promotion stops. If `dbless` gains commits that are absent from the candidate, the fast-forward update fails instead of overwriting them. Repository rules can also reject promotion; the tested pull request remains available for manual handling. No step force-pushes, rebases, or resets a branch.

The workflow advances `sync/upstream` through ordinary merges and recreates it if GitHub deletes it after a completed pull request. To resolve a conflict, merge the current `master` and `dbless` histories into that branch without rewriting it, then rerun **Sync upstream**. Failed tests require a fix on `dbless` or the integration branch before rerunning. GitHub can disable scheduled workflows after repository inactivity, so check the Actions page if automatic updates stop.

## Optional Redis deployments

The default service does not cache responses in Redis. If a separate deployment enables Redis caching, run **CI → Run workflow** with **compare-cached-schemas** enabled and **base-ref** set to that deployment's current commit before deploying it. A changed cached schema requires purging that deployment's application cache. This check is opt-in because a stateless Render deployment has no cache to purge.
