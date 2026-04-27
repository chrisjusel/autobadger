FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AUTOBEDGE_HOST=0.0.0.0 \
    AUTOBEDGE_PORT=10100 \
    AUTOBEDGE_DATA_DIR=/app/data \
    AUTOBEDGE_TIMEZONE=Europe/Rome

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY autobedge ./autobedge

RUN mkdir -p /app/data

EXPOSE 10100

CMD ["python", "-m", "autobedge.app"]
