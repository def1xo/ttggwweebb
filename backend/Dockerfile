FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# system deps for psycopg/builder
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev gcc curl && \
    rm -rf /var/lib/apt/lists/*

# copy dependency list first for better cache
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# copy app
COPY . .

# create uploads dir and non-root user
RUN mkdir -p /app/uploads \
 && useradd -m appuser \
 && chown -R appuser:appuser /app/uploads

# NOTE: keep container running as root so bind-mounted /app/uploads from host
# remains writable across different host UID/GID setups (otherwise payment proof
# and manual image uploads fail with PermissionError).
# USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
