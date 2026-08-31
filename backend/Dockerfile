FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV ENVIRONMENT=staging \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# Apply migrations, then serve. In staging/prod ENVIRONMENT != "dev", so the
# app does NOT fall back to create_all -- Alembic is the only schema path.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
