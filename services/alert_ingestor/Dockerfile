FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY common/ common/
COPY services/alert_ingestor/ services/alert_ingestor/

ENV PYTHONPATH=/app

CMD ["python", "-m", "services.alert_ingestor.main"]
