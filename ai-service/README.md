# ai-service

Python FastAPI service that turns a Telegram voice clip into a spoken English reply:

`STT (Groq) → LLM (OpenRouter / OpenAI models) → TTS (OpenRouter)`

Clip contract matches the stub:

- `POST /v1/sessions` → 201 `{ sessionId, greeting.text }`
- `GET /v1/sessions/{sessionId}/greeting/audio`
- `POST /v1/clips` (202) → poll `GET /v1/clips/{jobId}` → `GET /v1/clips/{jobId}/audio`

## Local run

```bash
cd ai-service
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
export GROQ_API_KEY=...
export OPENAI_API_KEY=...
# OpenRouter, default in the app: OPENAI_BASE_URL=https://openrouter.ai/api/v1
uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8090
```

For the Ktor server on the host, keep `AI_SERVICE_BASE_URL=http://127.0.0.1:8090`.

```bash
pytest
```

## Docker

Default compose still uses the echo stub on port 8090.

Real service:

```bash
cd infra
# infra/.env
AI_SERVICE_BASE_URL=http://ai-service:8090
GROQ_API_KEY=...
OPENAI_API_KEY=...
docker compose --profile llm up --build
```

Host port for the real service is **8091**.
