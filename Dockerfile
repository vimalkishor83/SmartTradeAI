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

CMD ["gunicorn", "--worker-class", "eventlet", "-w", "1", "--bind", "0.0.0.0:8000", "wsgi:app"]
