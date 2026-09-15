# Local infra

```bash
cd infra
docker compose up --build
```

Поднимаются:

- `server` — Ktor без Telegram, http://127.0.0.1:8080/health , Swagger UI http://127.0.0.1:8080/swagger
- `ai-service-stub` — мок clip/session API, http://127.0.0.1:8090/health

Telegram-бот работает только через webhook (TLS + `TELEGRAM_WEBHOOK_URL` на VPS).

Реальный ai-service (STT → LLM → TTS), порт на хосте 8091:

```bash
# в infra/.env
AI_SERVICE_BASE_URL=http://ai-service:8090
GROQ_API_KEY=...
OPENAI_API_KEY=...
# OpenRouter key in OPENAI_API_KEY
docker compose --profile llm up --build
```

Остановка: `Ctrl+C` или `docker compose down`.

На VPS Redis поднимает job **AI service → Deploy** (`infra/redis/deploy-remote.sh`): контейнер создаётся, если его ещё нет, и не сносится вместе с ai-service.
