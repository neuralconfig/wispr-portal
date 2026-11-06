# WISPr external captive portal (SmartZone / RUCKUS One). See README.md for the env vars.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8080

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && groupadd --system --gid 10001 portal \
 && useradd --system --uid 10001 --gid portal --home-dir /nonexistent --shell /usr/sbin/nologin portal

COPY --chown=root:root server.py gunicorn.conf.py ./
COPY --chown=root:root wispr/ ./wispr/
COPY --chown=root:root templates/ ./templates/
COPY --chown=root:root static/ ./static/
COPY --chown=root:root content/ ./content/

# Code is root-owned and read-only for the runtime user.
USER 10001:10001

EXPOSE 8080 8443

CMD ["gunicorn", "--config", "gunicorn.conf.py", "server:app"]
