#!/usr/bin/env bash
set -euo pipefail

APP=/opt/ai-service
: "${GROQ_API_KEY:?}"
: "${OPENAI_API_KEY:?}"

OPENAI_BASE_URL="${OPENAI_BASE_URL:-https://openrouter.ai/api/v1}"
LLM_MODEL="${LLM_MODEL:-openai/gpt-4o-mini}"
TTS_MODEL="${TTS_MODEL:-hexgrad/kokoro-82m}"
TTS_VOICE="${TTS_VOICE:-af_heart}"
TTS_RESPONSE_FORMAT="${TTS_RESPONSE_FORMAT:-mp3}"

umask 077
{
  printf 'GROQ_API_KEY=%s\n' "$GROQ_API_KEY"
  printf 'OPENAI_API_KEY=%s\n' "$OPENAI_API_KEY"
  printf 'OPENAI_BASE_URL=%s\n' "$OPENAI_BASE_URL"
  printf 'LLM_MODEL=%s\n' "$LLM_MODEL"
  printf 'TTS_MODEL=%s\n' "$TTS_MODEL"
  printf 'TTS_VOICE=%s\n' "$TTS_VOICE"
  printf 'TTS_RESPONSE_FORMAT=%s\n' "$TTS_RESPONSE_FORMAT"
} > "$APP/.env"
chmod 600 "$APP/.env"

cd "$APP"
BUILD=$(mktemp -d)
cp "$APP/Dockerfile" "$APP/requirements.txt" "$BUILD/"
cp -R "$APP/app" "$BUILD/app"
docker build -t ai-service:local "$BUILD"
rm -rf "$BUILD"
docker rm -f ai-service >/dev/null 2>&1 || true
docker run -d --name ai-service --restart unless-stopped \
  -p 127.0.0.1:8090:8090 \
  --env-file "$APP/.env" \
  ai-service:local
