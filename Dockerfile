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

# Single worker is intentional: the background scheduler (auto-generate,
# signal-close, market-data collector) and in-memory rate limiter both
# assume one process. Running -w >1 duplicates the scheduler jobs and
# splits rate-limit state per worker. To scale beyond one worker, first
# set REDIS_URL (makes the rate limiter shared) and move the scheduler to
# a single dedicated process/service instead of running inside every worker.
CMD ["gunicorn", "--worker-class", "eventlet", "-w", "1", "--bind", "0.0.0.0:8000", "wsgi:app"]
