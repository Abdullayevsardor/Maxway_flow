FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Tizim kutubxonalari (psycopg2 uchun)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Yuklamalar uchun papka (Railway Volume shu yerга ulanadi)
RUN mkdir -p static/uploads/requests

EXPOSE 8000

CMD ["sh", "-c", "python init_db.py && gunicorn main:app -k uvicorn.workers.UvicornWorker -w 4 -b 0.0.0.0:${PORT:-8000} --timeout 120 --access-logfile -"]
