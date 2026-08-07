#!/usr/bin/env bash
# Purge de retenção (SDD §10.4) — o EXECUTOR que o cron do host chama.
#
# Por que este arquivo existe (F04): até aqui o agendamento do §10.4 era uma linha de
# `curl` dentro de um COMENTÁRIO no docker-compose.prod.yml e no README. Nada instalava
# essa linha, e ela tinha três defeitos próprios: apontava para `127.0.0.1:8000` (o
# serviço `api` NÃO publica porta — só `web` em 8050 e `langfuse` em 13000), usava uma
# variável `JORNADA_DPO_TOKEN` que não existe em lugar nenhum do repositório (e que
# `/etc/cron.d/*` não herdaria do host de qualquer forma: expandiria vazio → 401), e
# mandava o stderr para dentro do log com `2>&1`, de onde ninguém nunca é notificado.
#
# As três correções estão aqui:
#   · HOST/PORTA — `http://127.0.0.1:8050/api/v1` (nginx do serviço `web` faz
#     proxy_pass de /api/ para api:8000; ver frontend/nginx.conf). Tráfego de loopback:
#     o Bearer não sai da máquina.
#   · CREDENCIAL — `JORNADA_PURGE_TOKEN` LIDO DO `.env` do servidor (não do ambiente do
#     cron, que não herda nada), gerado pelo deploy com `openssl rand -hex 32`. O token
#     nunca aparece em `ps`: vai para o curl por `-K -` (stdin), não por argv.
#   · FALHA VISÍVEL — saída normal vai para o log COM CARIMBO DE TEMPO; erro vai para o
#     log E para o stderr (que o cron entrega ao MAILTO/syslog, não a um arquivo), e o
#     script termina com exit code != 0. Silêncio aqui significa sucesso, e só isso.
#
# Modos (§10.4 — DRY-RUN é o default, apagar dado é irreversível):
#   ./purge_retencao.sh              → dry-run: relata o que expirou, não apaga NADA
#   ./purge_retencao.sh --aplicar    → apaga de verdade (é o que o cron roda)
#   ./purge_retencao.sh --status     → "quando foi o último purge?"; silencioso se está
#                                      em dia, ruidoso (stderr + exit) se atrasou
#
# Exit codes (o cron enxerga estes números):
#   0 = ok   1 = execução falhou (curl/HTTP)   2 = configuração ausente
#   3 = --status: nunca rodou, falhou ou está velho demais
set -euo pipefail

RAIZ_PADRAO=/opt/jornada
ENV_FILE="${JORNADA_ENV_FILE:-$RAIZ_PADRAO/.env}"
BASE="${JORNADA_API_BASE:-http://127.0.0.1:8050/api/v1}"
LOG="${JORNADA_PURGE_LOG:-/var/log/jornada-purge.log}"
CARIMBO="${JORNADA_PURGE_STAMP:-/var/lib/jornada/purge-ultimo.json}"
# Janela de tolerância do --status: o purge é diário, então 26h dá folga para atraso do
# cron/reboot sem deixar passar um dia inteiro perdido.
MAX_HORAS="${JORNADA_PURGE_MAX_H:-26}"
TIMEOUT="${JORNADA_PURGE_TIMEOUT_S:-120}"

agora() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# O log é conveniência, não pré-requisito: sem permissão de escrita o script continua
# funcionando e fala pelo stderr (perder o purge porque /var/log é read-only seria
# trocar um modo de falha silenciosa por outro).
if ! { [ -e "$LOG" ] && [ -w "$LOG" ]; } && ! (umask 027 && touch "$LOG") 2>/dev/null; then
  LOG=/dev/null
  SEM_LOG=1
fi

log() { printf '%s %s\n' "$(agora)" "$*" >>"$LOG"; }
erro() {
  log "ERRO: $*"
  # stderr NÃO vai para o log (era o `2>&1` do comentário antigo): é por aqui que o
  # cron notifica o MAILTO.
  printf '%s jornada-purge ERRO: %s\n' "$(agora)" "$*" >&2
  # E SYSLOG, porque o MAILTO depende de um MTA que a VPS enxuta não tem: sem isto o
  # cron registra "No MTA installed, discarding output" e a única notificação de falha
  # do purge é descartada em silêncio — o mesmo desfecho que esta frente veio consertar,
  # um nível acima. `journalctl -t jornada-purge -p err` existe em qualquer host systemd
  # e não depende de ninguém abrir /var/log. Ausência de `logger` não derruba o script.
  command -v logger >/dev/null 2>&1 && logger -t jornada-purge -p daemon.err -- "$*" || true
}

MODO=dry-run
case "${1:-}" in
  --aplicar) MODO=aplicar ;;
  --status) MODO=status ;;
  --dry-run | "") MODO=dry-run ;;
  -h | --help)
    # imprime o cabeçalho de comentários até a primeira linha de código
    sed -n '2,/^set -euo/p' "$0" | sed '$d'
    exit 0
    ;;
  *)
    erro "argumento desconhecido: $1 (use --aplicar, --status ou nada para dry-run)"
    exit 2
    ;;
esac

# ------------------------------------------------------------------ carimbo do último
gravar_carimbo() { # $1=resultado  $2=detalhe
  local dir
  # O carimbo é o registro de EXECUÇÃO, e só `--aplicar` executa. Se o dry-run também
  # carimbasse, um dry-run manual do operador (ou o do fim do deploy) faria o `--status`
  # do dia seguinte dizer "purge em dia" com o cron morto — o mesmo tipo de mentira que
  # o §10.4 já contou uma vez.
  [ "$MODO" = aplicar ] || return 0
  dir="$(dirname "$CARIMBO")"
  mkdir -p "$dir" 2>/dev/null || return 0
  printf '{"ts":"%s","modo":"%s","resultado":"%s","detalhe":"%s"}\n' \
    "$(agora)" "$MODO" "$1" "$2" >"$CARIMBO" 2>/dev/null || true
}

idade_horas() { # ecoa a idade do carimbo em horas inteiras, ou nada se não há carimbo
  [ -r "$CARIMBO" ] || return 1
  local ts epoch_ts epoch_agora
  ts="$(sed -n 's/.*"ts":"\([^"]*\)".*/\1/p' "$CARIMBO")"
  [ -n "$ts" ] || return 1
  epoch_ts="$(date -u -d "$ts" +%s 2>/dev/null)" || return 1
  epoch_agora="$(date -u +%s)"
  echo $(((epoch_agora - epoch_ts) / 3600))
}

resultado_carimbo() {
  [ -r "$CARIMBO" ] || return 1
  sed -n 's/.*"resultado":"\([^"]*\)".*/\1/p' "$CARIMBO"
}

# ------------------------------------------------------------------------- --status
# É a resposta para "e se o cron NÃO rodar?". Um script não consegue relatar a própria
# ausência, então quem relata é este modo, chamado por uma SEGUNDA linha de cron (num
# horário diferente) e pelo fim do deploy. Silencioso quando está em dia — cron que
# fala todo dia vira filtro de e-mail e volta a ser silêncio.
if [ "$MODO" = status ]; then
  idade=""
  if ! idade="$(idade_horas)"; then
    erro "purge de retenção NUNCA rodou (sem $CARIMBO). O §10.4 está sem consumidor."
    exit 3
  fi
  resultado="$(resultado_carimbo || echo desconhecido)"
  if [ "$resultado" != "ok" ]; then
    erro "última execução do purge terminou como '$resultado' (há ${idade}h) — ver $LOG"
    exit 3
  fi
  # Carimbo com data NO FUTURO: a idade sai negativa e passa por qualquer `-gt MAX`, ou
  # seja, o vigia declararia "purge em dia" para SEMPRE. Basta o relógio do host ter
  # andado errado uma vez (VPS sem NTP no boot, restauração de snapshot) ou alguém
  # editar o carimbo à mão. Um vigia que não sabe mentir é o ponto inteiro desta frente.
  if [ "$idade" -lt 0 ]; then
    erro "carimbo de $CARIMBO está no FUTURO (idade ${idade}h) — relógio do host ou
       arquivo adulterado. O vigia não consegue atestar nada; trate como NÃO rodou."
    exit 3
  fi
  if [ "$idade" -gt "$MAX_HORAS" ]; then
    erro "último purge OK foi há ${idade}h (limite ${MAX_HORAS}h) — o cron não está rodando"
    exit 3
  fi
  log "status: último purge OK há ${idade}h (limite ${MAX_HORAS}h)"
  exit 0
fi

# ------------------------------------------------------------------ pré-condições
command -v curl >/dev/null || {
  erro "curl ausente no host — o cron do §10.4 não tem como chamar a API"
  exit 2
}

# O token vem do .env do SERVIDOR (0600, root). Nunca do repositório, nunca do CI, e
# nunca do ambiente do cron — /etc/cron.d/* não herda ambiente do host, que é o motivo
# pelo qual a linha antiga expandia a variável JORNADA_DPO_TOKEN como string vazia.
TOKEN="${JORNADA_PURGE_TOKEN:-}"
if [ -z "$TOKEN" ] && [ -r "$ENV_FILE" ]; then
  TOKEN="$(sed -n 's/^[[:space:]]*JORNADA_PURGE_TOKEN=//p' "$ENV_FILE" | tail -n 1 |
    sed -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'$/\1/" -e 's/[[:space:]]*$//')"
fi
if [ "${#TOKEN}" -lt 32 ]; then
  gravar_carimbo "config" "token ausente ou curto"
  erro "JORNADA_PURGE_TOKEN ausente ou com menos de 32 caracteres em $ENV_FILE.
       Gere com: openssl rand -hex 32 e reinicie a api (docker compose up -d api)."
  exit 2
fi

# Lista de tenants varridos. O default é o tenant único da demo; onboardar um segundo
# telco e esquecer esta variável faz o purge desse tenant NUNCA rodar — e o `--status`
# diria "em dia", porque o primeiro tenant deu ok. Por isso a lista é ecoada no log de
# TODA execução e no carimbo: "quais tenants foram purgados ontem?" tem de ser uma
# pergunta com resposta escrita, não uma dedução sobre o ambiente do cron.
TENANTS="${JORNADA_PURGE_TENANTS:-torre-movel}"
CORPO="$(mktemp)"
trap 'rm -f "$CORPO"' EXIT

# Contexto no topo de cada execução: o próprio log responde "quando foi a última vez"
# sem depender de ninguém abrir a UI de auditoria.
if anterior="$(idade_horas)"; then
  log "início ($MODO) tenants=[$TENANTS] — anterior há ${anterior}h, resultado=$(resultado_carimbo || echo '?')"
else
  log "início ($MODO) tenants=[$TENANTS] — primeira execução registrada neste host"
fi
# if/then e não `[ ... ] && ...`: com `set -e` um teste falso no fim de uma lista `&&`
# derruba o script inteiro (o purge nunca rodaria em todo host com log gravável).
if [ "${SEM_LOG:-0}" = 1 ]; then
  erro "sem permissão de escrita no log ($LOG) — seguindo só pelo stderr"
fi

# ------------------------------------------------------------------------- execução
falhas=0
total_geral=0
for tenant in $(echo "$TENANTS" | tr ',' ' '); do
  url="$BASE/admin/purge"
  if [ "$MODO" = aplicar ]; then
    url="$url?aplicar=true"
  fi
  # `-K -`: o Authorization entra pela stdin do curl, então o token não aparece em
  # `ps aux` para nenhum outro processo do host.
  # `-sS` (e não `-fsS`): sem `-f` o corpo do erro é lido e vai para o log — um 401 ou
  # um 422 do §4.1 precisa chegar ao operador com o `detail` RFC-7807, não como
  # "exit 22" mudo. Quem decide sucesso é o código HTTP, logo abaixo.
  http=000
  if ! http="$(printf 'header = "Authorization: Bearer %s"\n' "$TOKEN" |
    curl -sS -K - -o "$CORPO" -w '%{http_code}' --max-time "$TIMEOUT" \
      -X POST -H "X-Tenant: $tenant" -H 'Accept: application/json' "$url" 2>>"$LOG")"; then
    erro "curl falhou para tenant=$tenant em $url (rede/porta? a API responde em :8050/api/)"
    falhas=$((falhas + 1))
    continue
  fi
  corpo_curto="$(tr -d '\n' <"$CORPO" | cut -c1-500)"
  if [ "$http" != "200" ]; then
    erro "tenant=$tenant HTTP $http — $corpo_curto"
    falhas=$((falhas + 1))
    continue
  fi
  total="$(sed -n 's/.*"total":[[:space:]]*\([0-9]*\).*/\1/p' <<<"$corpo_curto")"
  total="${total:-0}"
  total_geral=$((total_geral + total))
  log "tenant=$tenant HTTP 200 modo=$MODO total=$total :: $corpo_curto"
done

if [ "$falhas" -gt 0 ]; then
  gravar_carimbo "falha" "$falhas tenant(s) falharam"
  log "fim ($MODO): $falhas falha(s) — exit 1"
  exit 1
fi
gravar_carimbo "ok" "total=$total_geral tenants=[$TENANTS]"
log "fim ($MODO): ok, total=$total_geral, tenants=[$TENANTS]"
exit 0
