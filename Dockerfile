FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc g++ libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV FLASK_ENV=production
ENV PORT=8000

EXPOSE 8000

# Wire up the readiness endpoint that already exists in app/api/v1/system.py.
# Uses /ready rather than /health so an unusable dependency (DB or Redis down)
# marks the container unhealthy instead of it reporting "up" while unable to
# serve. curl isn't installed in the slim image, so this uses stdlib urllib.
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/system/ready', timeout=5).status==200 else 1)"

# Default stays -w 1 so a plain `docker run` of this image alone behaves as
# before: with no separate worker container, this process must own the
# scheduler and the market-data stream itself (RUN_SCHEDULER defaults to 1).
#
# To scale the web tier horizontally, run the split topology instead — see
# docker-compose.yml, which starts one `worker` service (RUN_SCHEDULER=1,
# worker.py) plus a web service with RUN_SCHEDULER=0 and as many gunicorn
# workers as you like. That split, together with REDIS_URL (shared rate
# limiter + cache) and SOCKETIO_MESSAGE_QUEUE (cross-process Socket.IO
# fan-out), is what makes -w >1 safe; without it, every worker would run a
# duplicate copy of every background job.
ENV GUNICORN_WORKERS=1
CMD ["sh", "-c", "gunicorn --worker-class eventlet -w ${GUNICORN_WORKERS} --bind 0.0.0.0:8000 wsgi:app"]
