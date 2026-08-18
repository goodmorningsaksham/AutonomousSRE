FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir redis fastapi uvicorn prometheus-client opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp opentelemetry-instrumentation-fastapi structlog
COPY services/ services/
ENV PYTHONPATH=/app
CMD ["python", "-m", "services.demo.inventory.main"]
