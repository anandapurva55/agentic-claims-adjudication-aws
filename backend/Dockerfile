# Build from the repository root: docker build -f backend/Dockerfile -t claims-adjudication-api .
FROM python:3.12-slim AS base
# The image installs exactly what uv.lock pins (runtime packages only, no dev tools) into /srv/.venv, so what runs here is what was tested.
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy PATH="/srv/.venv/bin:$PATH"
WORKDIR /srv

COPY --from=ghcr.io/astral-sh/uv:0.13.8 /uv /bin/uv
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev --no-install-project --no-cache

COPY backend/app backend/app
COPY data/rules.json data/policies.json data/lessons_seed.json data/
COPY data/claims data/claims
COPY data/schedules data/schedules
COPY data/bda data/bda
COPY redteam/attacks.json redteam/attacks.json
COPY redteam/reports/latest.json redteam/reports/latest.json

RUN useradd --create-home --uid 10001 app && mkdir -p data/runtime && chown -R app /srv
USER app
ENV PYTHONPATH=/srv/backend CLAIMS_DATA_DIR=/srv/data
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health').status==200 else 1)"
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
