FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY common/ common/
COPY database/ database/
COPY agents/ agents/
COPY policies/ policies/
COPY workflows/ workflows/
COPY services/ services/
ENV PYTHONPATH=/app
CMD ["python", "-m", "services.outbox_publisher.main"]
