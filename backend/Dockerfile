# syntax=docker/dockerfile:1
# ---------------------------------------------------------------------------
# MealConnect API / worker image
#   docker build -t mealconnect-api ./backend
# One image, two roles: the API (default CMD) and the worker (`python -m app.worker`).
# ---------------------------------------------------------------------------

# ---- Stage 1: install dependencies into a virtualenv ------------------------
FROM python:3.13-slim AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
# Copy only requirements first: this layer is cached until requirements change,
# so editing application code does not reinstall every package.
COPY requirements.txt .
RUN pip install -r requirements.txt

# ---- Stage 2: small runtime image ------------------------------------------
FROM python:3.13-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    ENVIRONMENT=production \
    LOG_JSON=true

# Run as an unprivileged user: a compromised process cannot modify the image or root files.
RUN groupadd --system app && useradd --system --gid app --home /app app
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app alembic.ini ./
COPY --chown=app:app alembic ./alembic
COPY --chown=app:app app ./app
USER app

EXPOSE 8000
# Docker marks the container unhealthy if the API stops answering.
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=2).status == 200 else 1)"

# --proxy-headers: trust X-Forwarded-Proto from Nginx so generated URLs use https.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--proxy-headers", "--forwarded-allow-ips", "*", "--no-access-log"]
