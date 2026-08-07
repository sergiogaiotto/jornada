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

# ---------------------------------------------------------------- §10.4 · retenção
# O agendamento do purge é cron do HOST (decisão do CHANGELOG: um scheduler na
# aplicação traria worker/lease/retry/fuso e um novo modo de falha silenciosa). O que
# faltava — e é o que estas funções resolvem — é que a linha do cron existia SÓ como
# comentário no compose e no README: nada a instalava, e o `grep` por `cron` em
# Dockerfile/CI/deploy não dava um hit sequer. Controle documentado e não instalado é
# pior que controle ausente, porque a auditoria o dá por existente.
CRON_FILE=/etc/cron.d/jornada-purge
FUSO_CRON="${JORNADA_CRON_TZ:-America/Sao_Paulo}"

garantir_env() { # $1=chave $2=valor — idempotente: não sobrescreve o que já existe
  [ -f .env ] || : >.env
  # NEWLINE FINAL antes de acrescentar. O `.env` da VPS é editado à mão (é assim que
  # JORNADA_ROOT_EMAIL/SENHA entram), e um editor que não deixa newline no fim faz o
  # `>>` COLAR a chave nova no fim da linha anterior:
  #   APP_SECRET=abcJORNADA_PURGE_TOKEN=0b69…
  # O estrago é duplo e silencioso: o APP_SECRET vira outro valor (toda sessão viva
  # morre no próximo `up`) e o token fica ilegível para o `sed` do executor — o cron
  # das 03:15 passa a sair 2 toda madrugada. Pior: o `grep` abaixo continua não achando
  # a chave, então CADA deploy acrescenta mais uma. `$(tail -c 1)` é vazio quando o
  # último byte é `\n` (a substituição de comando come o newline) — é o teste barato.
  if [ -s .env ] && [ -n "$(tail -c 1 .env)" ]; then
    printf '\n' >>.env
    echo "  .env: newline final ausente — corrigido antes de acrescentar $1"
  fi
  if ! grep -q "^${1}=" .env 2>/dev/null; then
    printf '%s=%s\n' "$1" "$2" >>.env
    echo "  .env: $1 gerado (valor fica SÓ no servidor)"
  fi
}

instalar_cron_purge() {
  # 1) Credencial de MÁQUINA. O cron não tem usuário nem sessão: autentica com um token
  #    de serviço aceito só pela rota do purge (backend/api/v1/admin.py::ator_do_purge).
  #    Gerado aqui, como o APP_SECRET já era — o repositório conhece o NOME da variável,
  #    nunca o valor.
  garantir_env JORNADA_PURGE_TOKEN "$(openssl rand -hex 32)"
  chmod 600 .env

  # 2) O executor precisa ser executável mesmo que o bit tenha se perdido no caminho.
  chmod +x scripts/purge_retencao.sh

  mkdir -p /var/lib/jornada
  touch /var/log/jornada-purge.log
  chmod 640 /var/log/jornada-purge.log

  # 3) A linha do cron. Diferenças para o comentário que existia antes:
  #    · CRON_TZ explícito — a objeção "cron não resolve fuso" registrada no CHANGELOG
  #      vale para o cron IMPLÍCITO (UTC do host); declarado, resolve;
  #    · MAILTO — cron entrega o stderr do job a alguém. O script só escreve em stderr
  #      quando FALHA, então isto notifica sem virar ruído diário;
  #    · sem `2>&1` no fim: mandar o stderr para dentro do arquivo era o que garantia
  #      que ninguém jamais soubesse de uma falha;
  #    · a 2ª linha é o vigia: pergunta "quando foi o último purge?" e grita se a
  #      resposta for "nunca" ou "faz mais de 26h" — é como se descobre que o cron
  #      parou sem depender do cron que parou.
  cat >"$CRON_FILE" <<CRON
# /etc/cron.d/jornada-purge — INSTALADO por deploy/deploy.sh (SDD §10.4). Não editar à mão:
# o próximo deploy sobrescreve. Executor: /opt/jornada/scripts/purge_retencao.sh
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
CRON_TZ=$FUSO_CRON
MAILTO=${JORNADA_CRON_MAILTO:-root}

15 3 * * * root /opt/jornada/scripts/purge_retencao.sh --aplicar
30 9 * * * root /opt/jornada/scripts/purge_retencao.sh --status
CRON
  chmod 644 "$CRON_FILE"
  chown root:root "$CRON_FILE" 2>/dev/null || true
  echo "  cron instalado: $CRON_FILE (TZ=$FUSO_CRON)"

  # 4) Rotação: o log é a prova de que o purge roda. Sem rotação ele cresce até encher
  #    o disco e derrubar o resto — falha de retenção por causa do log da retenção.
  if [ -d /etc/logrotate.d ]; then
    cat >/etc/logrotate.d/jornada-purge <<'ROT'
/var/log/jornada-purge.log {
  weekly
  rotate 12
  compress
  missingok
  notifempty
  create 640 root root
}
ROT
  fi
}

# ------------------------------------------------------------ §10.2 · backup e restauração
# Mesmo padrão do cron do purge, pelo mesmo motivo: INSTALADO, não documentado. A onda
# anterior provou que um controle descrito no README e ausente do host é contado como
# existente pela auditoria e não protege nada.
#
# Três agendamentos, três perguntas diferentes:
#   · o backup diário                     — "existe uma cópia de ontem?"
#   · o `--status` (em outro horário)     — "o cron do backup ainda está vivo?"
#   · o teste de RESTAURAÇÃO semanal      — "essa cópia volta?"
# O terceiro é o que separa backup de teatro. Os dois primeiros passariam felizes por
# meses com arquivos que não restauram.
CRON_BACKUP=/etc/cron.d/jornada-backup
BACKUP_DIR="${JORNADA_BACKUP_DIR:-/var/backups/jornada}"

instalar_cron_backup() {
  # 1) Chave da cifra. O dump é PII de telco em claro (§10.2) e vai para o disco de uma
  #    VPS que hospeda outros seis projetos. Gerada aqui como o APP_SECRET e o
  #    JORNADA_PURGE_TOKEN: o repositório conhece o NOME, nunca o valor.
  local passphrase_nova=0
  grep -q '^JORNADA_BACKUP_PASSPHRASE=' .env 2>/dev/null || passphrase_nova=1
  garantir_env JORNADA_BACKUP_PASSPHRASE "$(openssl rand -hex 32)"
  chmod 600 .env
  if [ "$passphrase_nova" = 1 ]; then
    # Avisar ALTO e uma vez só. Uma passphrase que existe apenas no host que ela protege
    # não sobrevive ao desastre contra o qual o backup foi feito: perdido o disco,
    # perde-se a chave junto e as cópias remotas viram lixo cifrado.
    echo "  ###############################################################"
    echo "  # JORNADA_BACKUP_PASSPHRASE foi GERADA agora no .env.         #"
    echo "  # COPIE-A PARA FORA DESTA VPS (cofre/gerenciador de senhas)   #"
    echo "  # AGORA. Sem ela, todo backup cifrado é irrecuperável — e ela #"
    echo "  # mora no mesmo disco que o backup deveria sobreviver.        #"
    echo "  #   grep '^JORNADA_BACKUP_PASSPHRASE=' /opt/jornada/.env      #"
    echo "  ###############################################################"
  fi

  chmod +x scripts/backup_bancos.sh scripts/restaura_teste.sh scripts/cert_status.sh 2>/dev/null || true

  mkdir -p "$BACKUP_DIR" /var/lib/jornada
  chmod 700 "$BACKUP_DIR" # dump de PII: nem group, nem others
  touch /var/log/jornada-backup.log /var/log/jornada-restore-teste.log
  chmod 640 /var/log/jornada-backup.log /var/log/jornada-restore-teste.log

  # Horários: backup às 02:20 (antes do purge das 03:15 — a cópia do dia registra o
  # estado ANTES da destruição por retenção, senão o backup mais novo já vem sem o que
  # o purge apagou e um erro de política se torna irreversível em 24h). Teste de
  # restauração aos domingos 04:10, depois de a cópia da madrugada existir. Vigias às
  # 09:40/09:50, em horário de gente acordada e SEPARADOS do job que vigiam.
  cat >"$CRON_BACKUP" <<CRON
# /etc/cron.d/jornada-backup — INSTALADO por deploy/deploy.sh (SDD §10.2). Não editar à
# mão: o próximo deploy sobrescreve.
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
CRON_TZ=$FUSO_CRON
MAILTO=${JORNADA_CRON_MAILTO:-root}

20 2 * * * root /opt/jornada/scripts/backup_bancos.sh
10 4 * * 0 root /opt/jornada/scripts/restaura_teste.sh
40 9 * * * root /opt/jornada/scripts/backup_bancos.sh --status
50 9 * * * root /opt/jornada/scripts/restaura_teste.sh --status
15 9 * * * root /opt/jornada/scripts/cert_status.sh
CRON
  chmod 644 "$CRON_BACKUP"
  chown root:root "$CRON_BACKUP" 2>/dev/null || true
  echo "  cron instalado: $CRON_BACKUP (backup 02:20, restauração dom 04:10, vigias 09:40/09:50, cert 09:15)"

  if [ -d /etc/logrotate.d ]; then
    cat >/etc/logrotate.d/jornada-backup <<'ROT'
/var/log/jornada-backup.log /var/log/jornada-restore-teste.log {
  weekly
  rotate 12
  compress
  missingok
  notifempty
  create 640 root root
}
ROT
  fi
}

verificar_cron_ativo() {
  # /etc/cron.d só significa alguma coisa se existir um daemon de cron rodando. Sem esta
  # checagem o deploy escreveria o arquivo, imprimiria sucesso, e o purge nunca rodaria —
  # o mesmo desfecho de antes, só que com mais arquivos.
  if pgrep -x cron >/dev/null 2>&1 || pgrep -x crond >/dev/null 2>&1; then
    return 0
  fi
  if command -v systemctl >/dev/null 2>&1; then
    systemctl enable --now cron >/dev/null 2>&1 || systemctl enable --now crond >/dev/null 2>&1 || true
    if systemctl is-active --quiet cron || systemctl is-active --quiet crond; then
      echo "  daemon de cron estava parado — reativado"
      return 0
    fi
  fi
  return 1
}

verificar_canal_de_alerta() {
  # O `MAILTO` do cron só entrega o stderr do job se existir um MTA no host. Numa VPS
  # enxuta (Debian slim, que é o caso) NÃO existe: o cron registra "No MTA installed,
  # discarding output" e a notificação de falha do purge morre ali. Sem esta checagem os
  # "três caminhos de falha visível" (exit code, stderr→MAILTO, vigia das 09:30) colapsam
  # num só — e esse um está entupido. Não falha o deploy: o executor também manda toda
  # falha para o syslog (`logger -t jornada-purge`), que existe em qualquer host systemd.
  if command -v sendmail >/dev/null 2>&1 || command -v mail >/dev/null 2>&1; then
    echo "  alerta: MTA presente — o MAILTO do cron entrega as falhas do purge"
    return 0
  fi
  echo "AVISO §10.4: nenhum MTA neste host — o MAILTO de $CRON_FILE será DESCARTADO." >&2
  echo "             O canal que resta é o syslog. Veja as falhas com:" >&2
  echo "               journalctl -t jornada-purge -p err --since '-7d'" >&2
  echo "             Para receber por e-mail: apt-get install -y bsd-mailx postfix." >&2
}

esperar_api() {
  # O smoke do §10.4 falha o deploy — logo ele NÃO pode falhar por corrida. `sleep 3`
  # depois de um `up --build` não cobre migração + startup: o dry-run bateria em
  # connection refused, o deploy sairia 1 e, na terceira vez que isso acontecesse, o
  # coordenador comentaria a checagem. Controle desligado protege zero; então espera-se
  # de verdade (até 120s) antes de acusar.
  # A sonda é `:8050/healthz` (nginx `location = /healthz` → api:8000/healthz): é a
  # MESMA cadeia loopback→nginx→api que o cron usa. Sondar a raiz `/` provaria só que o
  # nginx serve o SPA — e passaria com a api morta, que é o caso que interessa.
  local tentativa
  for tentativa in $(seq 1 60); do
    if curl -fsS -o /dev/null --max-time 3 http://127.0.0.1:8050/healthz 2>/dev/null; then
      echo "  api respondendo por :8050 → nginx → api (tentativa $tentativa)"
      return 0
    fi
    sleep 2
  done
  echo "AVISO: a api não respondeu em :8050 em 120s — o smoke do §10.4 vai acusar." >&2
  return 1
}

local_main() {
  command -v docker >/dev/null || {
    echo "docker ausente na VPS"
    exit 1
  }
  mkdir -p /opt && cd /opt
  if [ ! -d jornada/.git ]; then
    git clone https://github.com/sergiogaiotto/jornada.git
  fi
  cd jornada
  git fetch origin && git reset --hard origin/main
  if [ ! -f .env ]; then
    echo "APP_SECRET=$(openssl rand -hex 32)" >.env
    chmod 600 .env
  fi
  # §10.4 ANTES do `up`: o token de máquina precisa existir no .env para o compose
  # injetá-lo no serviço `api` nesta mesma subida (JORNADA_PURGE_TOKEN).
  falhas_pos_deploy=0
  instalar_cron_purge
  instalar_cron_backup
  if ! verificar_cron_ativo; then
    echo "ERRO §10.4: nenhum daemon de cron ativo neste host — $CRON_FILE é inerte." >&2
    echo "            instale com 'apt-get install -y cron && systemctl enable --now cron'." >&2
    falhas_pos_deploy=1
  fi
  verificar_canal_de_alerta

  # A22 · version-stamp: o commit que está sendo deployado viaja para dentro das
  # imagens (ARG GIT_SHA) e reaparece em /healthz.sha — é assim que o smoke prova
  # que o que subiu é o que foi buildado.
  export GIT_SHA="$(git rev-parse HEAD | cut -c1-7)"
  echo "deployando GIT_SHA=$GIT_SHA"
  docker compose -f docker-compose.prod.yml --env-file .env up -d --build
  docker compose -f docker-compose.prod.yml ps
  sleep 3
  curl -fsS -o /dev/null -w "smoke local (web): HTTP %{http_code}\n" http://localhost:8050/ || true
  echo "healthz: $(curl -fsS http://localhost:8000/healthz 2>/dev/null || docker compose -f docker-compose.prod.yml exec -T api curl -fsS http://localhost:8000/healthz 2>/dev/null || echo '(indisponível)')"

  # Smoke do §10.4: DRY-RUN de verdade, agora. Prova a cadeia inteira que o cron vai
  # usar às 03:15 (host, porta, token, RBAC de máquina, política vigente) sem apagar
  # nada — e falha o deploy se estiver quebrada, em vez de descobrir daqui a um mês
  # numa auditoria. Dry-run não carimba: o `--status` continua enxergando só execuções.
  echo "smoke §10.4 (dry-run, não apaga nada):"
  esperar_api || true # o smoke abaixo é quem decide; aqui só se espera a subida
  if ! scripts/purge_retencao.sh; then
    echo "ERRO §10.4: o dry-run do purge falhou — o cron das 03:15 falharia igual." >&2
    falhas_pos_deploy=1
  fi
  tail -n 3 /var/log/jornada-purge.log 2>/dev/null || true

  # Smoke do §10.2: roda um backup DE VERDADE agora. É barato (segundos) e prova a
  # cadeia inteira que o cron das 02:20 vai usar — docker exec, pg_dump nos dois
  # containers, cifra, checksum, retenção — em vez de descobrir na primeira madrugada.
  echo "smoke §10.2 (backup real):"
  if ! scripts/backup_bancos.sh; then
    echo "ERRO §10.2: o backup falhou agora — o cron das 02:20 falharia igual." >&2
    falhas_pos_deploy=1
  else
    tail -n 3 /var/log/jornada-backup.log 2>/dev/null || true
  fi

  # E, na PRIMEIRA vez neste host, prova também que o backup RESTAURA. Depois disso
  # quem cuida é o cron de domingo — restaurar leva minutos e não cabe em todo deploy,
  # mas subir um host novo e sair confiando num backup nunca restaurado é como esta
  # frente começou (zero backups, e todo mundo achando que havia).
  if [ ! -r /var/lib/jornada/restore-teste-ultimo.json ]; then
    echo "smoke §10.2 (PRIMEIRO teste de restauração neste host — container descartável):"
    if ! scripts/restaura_teste.sh; then
      echo "ERRO §10.2: o backup recém-criado NÃO restaura. Não há backup." >&2
      falhas_pos_deploy=1
    fi
  else
    scripts/restaura_teste.sh --status ||
      echo "AVISO §10.2: o teste de restauração está atrasado (ver acima)." >&2
  fi

  if [ "$falhas_pos_deploy" -ne 0 ]; then
    echo "DEPLOY COM FALHA: a aplicação subiu, o controle de retenção §10.4 NÃO está garantido." >&2
    exit 1
  fi
}

if [ "${1:-}" = "--local" ]; then local_main; else remote_main "$@"; fi
