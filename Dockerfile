FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY birkin/ birkin/
COPY skills/ skills/
COPY memory/ memory/

RUN pip install --no-cache-dir .

EXPOSE 8321

CMD ["uvicorn", "birkin.gateway.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8321"]
