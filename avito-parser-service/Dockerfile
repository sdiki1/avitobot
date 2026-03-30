FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/parser_avito:/app

WORKDIR /app

COPY avito-parser-service/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r /app/requirements.txt

COPY avito-parser-service/app /app/app
COPY parser_avito /app/parser_avito

CMD ["python", "-m", "app.main"]
