
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY api.py ./
COPY models ./models
COPY routers ./routers
COPY services ./services
COPY static ./static
COPY utilities ./utilities
COPY billing ./billing


CMD ["sh", "-c", "uvicorn api:app --host 0.0.0.0 --port ${PORT:-8000}"]
  