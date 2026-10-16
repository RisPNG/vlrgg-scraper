FROM        python:3.14.7-slim
COPY        --from=ghcr.io/astral-sh/uv:0.12.5 /uv /bin/uv
RUN         groupadd -g 999 vlrscraper && useradd -m -r -u 999 -g vlrscraper vlrscraper
RUN         mkdir /app && chown vlrscraper:vlrscraper /app
COPY        . /app
WORKDIR     /app
USER        vlrscraper
RUN         uv sync --frozen --no-cache --no-dev
ARG         GIT_SHA
ENV         GIT_SHA=${GIT_SHA}
EXPOSE      8000
ENV         PORT=8000
CMD         ["sh", "-c", "exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port \"$PORT\" --workers 1"]

