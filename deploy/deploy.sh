#!/usr/bin/env bash
# Deploy do Jornada na VPS (porta 8050) a partir do GitHub.
# Uso local:  bash deploy/deploy.sh [usuario@host]
# Uso na VPS: curl -fsSL https://raw.githubusercontent.com/sergiogaiotto/jornada/main/deploy/deploy.sh | bash -s -- --local
set -euo pipefail

remote_main() {
  HOST="${1:-root@vps.falagaiotto.com.br}"
  KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519_jornada}"
  ssh -i "$KEY" -o StrictHostKeyChecking=accept-new "$HOST" \
    "curl -fsSL https://raw.githubusercontent.com/sergiogaiotto/jornada/main/deploy/deploy.sh | bash -s -- --local"
  echo "OK → http://vps.falagaiotto.com.br:8050"
}

local_main() {
  command -v docker >/dev/null || { echo "docker ausente na VPS"; exit 1; }
  mkdir -p /opt && cd /opt
  if [ ! -d jornada/.git ]; then
    git clone https://github.com/sergiogaiotto/jornada.git
  fi
  cd jornada
  git fetch origin && git reset --hard origin/main
  if [ ! -f .env ]; then
    echo "APP_SECRET=$(openssl rand -hex 32)" > .env
    chmod 600 .env
  fi
  docker compose -f docker-compose.prod.yml --env-file .env up -d --build
  docker compose -f docker-compose.prod.yml ps
  sleep 3
  curl -fsS -o /dev/null -w "smoke local (web): HTTP %{http_code}\n" http://localhost:8050/ || true
}

if [ "${1:-}" = "--local" ]; then local_main; else remote_main "$@"; fi
