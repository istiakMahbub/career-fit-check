FROM python:3.11-slim

WORKDIR /app

# Install Chrome + chromedriver for Selenium fallback scraping
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium chromium-driver \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

# Initialise the SQLite database on first start
RUN python -c "from db.database import init_db; init_db()"

EXPOSE 8000

CMD ["gunicorn", "main:app", \
     "--workers", "2", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:8000", \
     "--timeout", "120"]
