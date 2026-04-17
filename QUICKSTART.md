# Birkin — Quick Start (Docker)

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose v2+
- An API key for at least one LLM provider (Anthropic, OpenAI, etc.)

## 1. Clone the repository

```bash
git clone https://github.com/your-org/birkin.git
cd birkin
```

## 2. Create your `.env` file

```bash
cp .env.example .env   # or create manually
```

Add your provider API keys:

```
ANTHROPIC_API_KEY=sk-ant-...
# OPENAI_API_KEY=sk-...
```

## 3. Start Birkin

```bash
docker compose up -d
```

This builds the image on first run and starts the server.

## 4. Open the UI

Navigate to [http://localhost:8321](http://localhost:8321) in your browser.

## Useful commands

```bash
docker compose logs -f        # Stream logs
docker compose down            # Stop
docker compose up -d --build   # Rebuild after code changes
```

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Port 8321 already in use | Change the host port in `docker-compose.yml`: `"9000:8321"` |
| Missing API key errors | Verify `.env` contains valid keys and restart: `docker compose restart` |
| Permission denied on volumes | On Linux, ensure your user is in the `docker` group |
| Stale image after code change | Rebuild: `docker compose up -d --build` |
