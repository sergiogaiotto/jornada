#!/usr/bin/env bash
# TLS na borda do Jornada (SDD §10.3) — instalador idempotente para a VPS.
#
# Uso (na VPS, como root):
#   bash /opt/jornada/deploy/tls_setup.sh --verificar   # NÃO muda nada: só diagnostica
#   bash /opt/jornada/deploy/tls_setup.sh --aplicar     # abre ufw, emite o cert, liga
#
# Ordem deliberada: `--verificar` primeiro. Emitir certificado é a única etapa desta
# frente com limite de tentativas do outro lado (Let's Encrypt: 5 falhas por conta/host
# por hora, 50 certificados por domínio por semana). Queimar o limite por causa de uma
# porta fechada deixa o host sem TLS por uma hora — daí o dry-run contra o STAGING
# antes de qualquer emissão real.
#
# O que este script NÃO faz, de propósito:
#   · não mexe em docker-compose.prod.yml (outra frente é dona) — a porta 8050 continua
#     publicada em 0.0.0.0 até alguém aplicar o trecho do relatório;
#   · não remove /etc/nginx/sites-enabled/default nem os sites dos OUTROS projetos que
#     dividem este host (agente_*, vertice-*, tdia-*). Um `rm` ali derrubaria o nginx
#     inteiro, e o nginx inteiro é de todo mundo, não só do Jornada.
set -euo pipefail

HOST_TLS="${JORNADA_TLS_HOST:-vps.falagaiotto.com.br}"
EMAIL_ACME="${JORNADA_ACME_EMAIL:-gaiotto.br@gmail.com}"
RAIZ="${JORNADA_RAIZ:-/opt/jornada}"
WEBROOT=/var/www/certbot
DISPONIVEL=/etc/nginx/sites-available/jornada.conf
HABILITADO=/etc/nginx/sites-enabled/jornada.conf
# Publicar a UI da Langfuse sob TLS é OPCIONAL — e desligado por default. Com PII real
# nos prompts o trace vira dado pessoal (§10.2); o caminho recomendado é túnel SSH, não
# porta pública. `JORNADA_TLS_LANGFUSE=1` liga o server{} da 13443 e abre a porta.
LANGFUSE_PUBLICO="${JORNADA_TLS_LANGFUSE:-0}"

MODO=""
case "${1:-}" in
  --verificar) MODO=verificar ;;
  --aplicar) MODO=aplicar ;;
  *)
    sed -n '2,/^set -euo/p' "$0" | sed '$d'
    exit 0
    ;;
esac

ok() { printf '  \033[32mok\033[0m   %s\n' "$*"; }
aviso() { printf '  \033[33maviso\033[0m %s\n' "$*"; }
falha() {
  printf '  \033[31mFALHA\033[0m %s\n' "$*" >&2
  PROBLEMAS=$((PROBLEMAS + 1))
}
PROBLEMAS=0

echo "== Jornada · TLS ($MODO) · host=$HOST_TLS =="

# --------------------------------------------------------------- 1. pré-condições
command -v nginx >/dev/null || falha "nginx ausente (apt-get install -y nginx)"
command -v certbot >/dev/null || falha "certbot ausente (apt-get install -y certbot python3-certbot-nginx)"
command -v ufw >/dev/null || aviso "ufw ausente — as regras de firewall abaixo não se aplicam"

# O nome PRECISA resolver para o IP público desta máquina, senão o desafio HTTP-01 vai
# bater em outro servidor e falhar com um erro que não menciona DNS.
ip_dns="$(getent hosts "$HOST_TLS" | awk '{print $1; exit}')"
ip_meu="$(curl -fsS --max-time 10 https://api.ipify.org 2>/dev/null || echo '')"
if [ -z "$ip_dns" ]; then
  falha "$HOST_TLS não resolve — sem DNS não há HTTP-01"
elif [ -n "$ip_meu" ] && [ "$ip_dns" != "$ip_meu" ]; then
  falha "$HOST_TLS resolve para $ip_dns, mas o IP público desta máquina é $ip_meu"
else
  ok "$HOST_TLS → $ip_dns (bate com o IP desta máquina)"
fi

# --------------------------------------------------------- 2. o firewall (a descoberta)
# O ufw deste host está ATIVO e não tem regra para 80/443 — é por isso que
# `curl http://vps.falagaiotto.com.br/` dá timeout hoje, apesar de existir um nginx
# escutando a 80 desde sempre. Timeout (e não "connection refused") é a assinatura de
# pacote DESCARTADO por firewall, não de porta sem serviço.
#
# Que o bloqueio é local e não do provedor está PROVADO no log do próprio ufw: há
# milhares de `[UFW BLOCK] ... DPT=80` e `DPT=443` vindos da internet em /var/log/ufw.log.
# O pacote chega na eth0 e morre aqui dentro. Logo, abrir o ufw basta — não é preciso
# negociar porta com operadora nem cair para o desafio DNS-01.
regra_ufw() { # $1=porta — idempotente; `ufw allow` repetido é no-op ("Skipping")
  if ufw status | grep -qE "^${1}/tcp .*ALLOW"; then
    ok "ufw já permite ${1}/tcp"
    return 0
  fi
  if [ "$MODO" = verificar ]; then
    aviso "ufw NÃO permite ${1}/tcp — o --aplicar abriria"
    return 0
  fi
  ufw allow "${1}/tcp" >/dev/null
  ok "ufw: ${1}/tcp liberado"
}
regra_ufw 80
regra_ufw 443
[ "$LANGFUSE_PUBLICO" = 1 ] && regra_ufw 13443

# Abrir a 80 expõe também o `default_server` deste nginx (/var/www/html) para a
# internet. Não é um risco novo do Jornada, mas passa a ser visível — vale saber.
[ -e /etc/nginx/sites-enabled/default ] &&
  aviso "abrir a 80 expõe também o site 'default' (/var/www/html) deste host"

# --------------------------------------------------- 3. webroot do desafio ACME
if [ "$MODO" = aplicar ]; then
  mkdir -p "$WEBROOT/.well-known/acme-challenge"
  chown -R root:root "$WEBROOT"
  chmod -R 755 "$WEBROOT"
fi

# Fase 1: um site só com a :80 (ACME + redirect). O arquivo final referencia
# fullchain.pem, que ainda NÃO existe — habilitá-lo agora faria `nginx -t` falhar e,
# num host compartilhado, um reload recusado deixa TODOS os projetos na configuração
# antiga sem ninguém perceber. Duas fases evitam isso.
escrever_fase1() {
  cat >"$DISPONIVEL" <<CONF
# TEMPORÁRIO — fase 1 do deploy/tls_setup.sh (só o desafio ACME + redirect).
# Substituído por nginx/jornada.conf assim que o certificado existir.
server {
    listen 80;
    listen [::]:80;
    server_name $HOST_TLS;
    location ^~ /.well-known/acme-challenge/ {
        root $WEBROOT;
        default_type "text/plain";
        try_files \$uri =404;
    }
    location / { return 301 https://\$host\$request_uri; }
}
CONF
  ln -sfn "$DISPONIVEL" "$HABILITADO"
}

recarregar_nginx() {
  if ! nginx -t 2>/tmp/nginx-t.log; then
    cat /tmp/nginx-t.log >&2
    falha "nginx -t recusou a configuração — NADA foi recarregado (os outros sites deste host seguem no ar)"
    return 1
  fi
  systemctl reload nginx
  ok "nginx recarregado"
}

# ------------------------------------------------------------------ 4. certificado
CERT_DIR="/etc/letsencrypt/live/$HOST_TLS"
if [ "$MODO" = verificar ]; then
  if [ -d "$CERT_DIR" ]; then
    fim="$(openssl x509 -enddate -noout -in "$CERT_DIR/fullchain.pem" 2>/dev/null | cut -d= -f2)"
    ok "certificado já existe (expira em $fim)"
  else
    aviso "nenhum certificado para $HOST_TLS ainda — o --aplicar emite"
  fi
  echo
  if [ "$PROBLEMAS" -gt 0 ]; then
    echo "VERIFICAÇÃO: $PROBLEMAS problema(s) — resolva antes do --aplicar." >&2
    exit 1
  fi
  echo "VERIFICAÇÃO: pronto para o --aplicar."
  exit 0
fi

escrever_fase1
recarregar_nginx || exit 1

if [ ! -d "$CERT_DIR" ]; then
  # DRY-RUN contra o staging ANTES da emissão real: mesma cadeia (DNS, ufw, webroot,
  # nginx), limite de tentativas generoso, certificado descartável. Se isto falha, a
  # emissão real falharia igual — e queimaria o limite de verdade.
  echo "-- dry-run (staging) --"
  if ! certbot certonly --webroot -w "$WEBROOT" -d "$HOST_TLS" \
    --non-interactive --agree-tos -m "$EMAIL_ACME" --dry-run; then
    falha "dry-run do ACME falhou — NÃO emiti nada. Verifique ufw/DNS acima e o log em /var/log/letsencrypt/"
    exit 1
  fi
  ok "dry-run passou — a cadeia HTTP-01 funciona"

  echo "-- emissão real --"
  # --deploy-hook fica GRAVADO no renewal conf: toda renovação futura recarrega o nginx
  # sozinha. Sem ele, o certbot renova o arquivo e o nginx segue servindo em memória o
  # certificado VELHO até o próximo reload — que pode não vir antes do vencimento.
  certbot certonly --webroot -w "$WEBROOT" -d "$HOST_TLS" \
    --non-interactive --agree-tos -m "$EMAIL_ACME" \
    --deploy-hook "systemctl reload nginx"
  ok "certificado emitido para $HOST_TLS"
else
  ok "certificado já existe — pulando emissão"
fi

# options-ssl-nginx.conf e ssl-dhparams.pem são referenciados pelo nginx/jornada.conf.
# O pacote certbot só os cria quando o plugin nginx roda; com --webroot podem faltar, e
# a falta derruba o `nginx -t` do host inteiro.
[ -f /etc/letsencrypt/options-ssl-nginx.conf ] || {
  cat >/etc/letsencrypt/options-ssl-nginx.conf <<'SSLCONF'
ssl_session_cache shared:le_nginx_SSL:10m;
ssl_session_timeout 1440m;
ssl_session_tickets off;
ssl_protocols TLSv1.2 TLSv1.3;
ssl_prefer_server_ciphers off;
ssl_ciphers "ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:DHE-RSA-AES128-GCM-SHA256:DHE-RSA-AES256-GCM-SHA384";
SSLCONF
  ok "options-ssl-nginx.conf criado (o --webroot não o instala)"
}
[ -f /etc/letsencrypt/ssl-dhparams.pem ] || {
  openssl dhparam -out /etc/letsencrypt/ssl-dhparams.pem 2048 2>/dev/null
  ok "ssl-dhparams.pem gerado"
}

# ------------------------------------------------------- 5. fase 2 · config definitiva
cp "$RAIZ/nginx/jornada.conf" "$DISPONIVEL"
if [ "$LANGFUSE_PUBLICO" != 1 ]; then
  # Remove o server{} da 13443 quando a Langfuse não vai ser publicada. `sed` do
  # marcador até o fim do arquivo: o bloco é o último do jornada.conf de propósito,
  # justamente para poder ser cortado assim.
  sed -i '/^# ---* :13443/,$d' "$DISPONIVEL"
  ok "bloco da Langfuse (13443) NÃO instalado — use túnel SSH (recomendado)"
fi
ln -sfn "$DISPONIVEL" "$HABILITADO"
recarregar_nginx || exit 1

# Marca que o TLS FOI aplicado neste host. É o que permite ao cert_status.sh (que roda
# de cron todo dia, instalado pelo deploy) ficar calado enquanto ninguém aplicou TLS, e
# gritar de verdade se o certificado sumir depois. Sem a marca, o vigia acusaria falha
# todo dia em todo host sem TLS — e alarme diário previsível é o que ensina o time a
# ignorar o canal onde também chegam os alarmes do purge e do backup.
mkdir -p /var/lib/jornada
printf '{"ts":"%s","host":"%s"}\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$HOST_TLS" \
  >/var/lib/jornada/tls-instalado

# --------------------------------------------------------------- 6. vigia do vencimento
# Ver deploy/deploy.sh::instalar_cron_backup e scripts/cert_status.sh — a renovação é do
# certbot.timer (já ativo neste host); o que faltava é ALGUÉM PERCEBER quando ela falha.
if [ -x "$RAIZ/scripts/cert_status.sh" ]; then
  "$RAIZ/scripts/cert_status.sh" || aviso "cert_status.sh já acusa algo — leia acima"
fi

# ------------------------------------------------------------------ 7. prova de vida
echo "-- verificação pós-instalação --"
curl -fsS -o /dev/null -w "  https://$HOST_TLS/            HTTP %{http_code}\n" "https://$HOST_TLS/" ||
  falha "a aplicação não respondeu em https://$HOST_TLS/"
curl -fsS -o /dev/null -w "  http →  redirect             HTTP %{http_code} → %{redirect_url}\n" \
  "http://$HOST_TLS/" || aviso "o redirect da :80 não respondeu"
curl -fsS -o /dev/null -w "  https://$HOST_TLS/healthz     HTTP %{http_code}\n" "https://$HOST_TLS/healthz" ||
  falha "/healthz não respondeu por TLS — o proxy para 8050 não está fechando"

echo
if [ "$PROBLEMAS" -gt 0 ]; then
  echo "TLS: $PROBLEMAS problema(s) — leia acima." >&2
  exit 1
fi
cat <<'FIM'

TLS no ar. FALTA (não é este script que faz — ver relatório da frente):
  1. SESSION_COOKIE_SECURE=true no .env → senão o cookie de sessão continua viajando sem
     a flag Secure e um downgrade para http o entrega em claro. O compose já repassa a
     variável (`SESSION_COOKIE_SECURE: ${SESSION_COOKIE_SECURE:-false}`): o default é
     `false`, então NÃO basta ter TLS — é preciso escrever a linha no .env.
  2. WEB_BASE_URL=https://vps.falagaiotto.com.br no .env → é o que vai DENTRO do link
     mágico de aprovação (api/v1/portoes.py). O compose já define a variável, mas com
     default `http://vps.falagaiotto.com.br:8050`: sem a linha no .env o aprovador
     recebe um link http, em porta que o redirect não cobre (o :80 redireciona, a :8050
     não). Tem de virar https E perder a porta.
  3. fechar a 8050/13000 em 127.0.0.1 no docker-compose.prod.yml;
  4. --base-url do smoke no CI (.github/workflows/ci.yml) para https.
  CORS: nada a fazer — não há CORSMiddleware no backend (conferido: zero ocorrências em
  backend/**.py). A SPA fala com a api na MESMA origem, via o nginx do container `web`
  (frontend/nginx.conf: location /api/ → api:8000). Mudar o esquema para https não cria
  origem nova para ninguém.
Depois de 1 e 2: docker compose -f docker-compose.prod.yml --env-file .env up -d api
FIM
