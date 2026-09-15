#!/usr/bin/env bash
set -euo pipefail

NETWORK=speaking-coach
docker network create "$NETWORK" >/dev/null 2>&1 || true
docker volume create speaking-coach-redis >/dev/null 2>&1 || true

if docker inspect redis >/dev/null 2>&1; then
  docker start redis >/dev/null
  docker network connect "$NETWORK" redis >/dev/null 2>&1 || true
  echo "redis already present; left running."
  exit 0
fi

docker run -d --name redis --restart unless-stopped \
  --network "$NETWORK" \
  -p 127.0.0.1:6379:6379 \
  -v speaking-coach-redis:/data \
  redis:7-alpine \
  redis-server --save 60 1 --loglevel warning
