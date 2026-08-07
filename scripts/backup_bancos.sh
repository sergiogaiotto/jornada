#!/usr/bin/env bash
# Backup cifrado dos DOIS bancos do Jornada (SDD §10.2/§10.4) — executor do cron do host.
#
# Contexto: até aqui NÃO existia backup nenhum. Os dados vivem em dois volumes nomeados
# do Docker (`jornada_db-data` e `jornada_db-langfuse-data`) num único disco; um
# `docker volume rm` distraído, um `down -v`, ou o /dev/sda1 deste host levam a base de
# clientes de telco junto e não há de onde voltar.
#
# Decisões e o porquê:
#   · pg_dump -Fc (custom) e NÃO cópia do volume: copiar o diretório de dados de um
#     Postgres VIVO produz um backup que às vezes restaura e às vezes não — e a versão
#     que não restaura só se descobre no dia do desastre. O dump é consistente por MVCC:
#     é um retrato de uma transação, com o banco no ar.
#   · dump para arquivo TEMPORÁRIO antes de cifrar, e não `pg_dump | openssl > arq`:
#     num pipeline o `$?` é o do ÚLTIMO comando, então um pg_dump que morre no meio
#     produziria um .enc perfeitamente cifrado, com tamanho plausível, contendo meio
#     dump — e exit 0. É a forma mais comum de backup que só falha na restauração.
#   · cifrado SEMPRE: um dump do Jornada é PII de telco em texto puro (§10.2). Ele vai
#     parar em disco de VPS compartilhada com outros seis projetos e, se sair daqui,
#     em algum armazenamento de terceiro.
#   · a senha entra no openssl por FILE DESCRIPTOR (`-pass fd:3`), nunca por argv: em
#     `ps aux` este host tem outros inquilinos.
#
# Uso:
#   ./backup_bancos.sh              → executa o backup (é o que o cron roda)
#   ./backup_bancos.sh --status     → "quando foi o último backup bom?" — silencioso se
#                                     em dia, ruidoso e exit 3 se não
#   ./backup_bancos.sh --listar     → o que existe hoje, com tamanho e idade
#
# Exit: 0 = ok · 1 = execução falhou · 2 = configuração ausente · 3 = --status atrasado
set -euo pipefail

RAIZ="${JORNADA_RAIZ:-/opt/jornada}"
ENV_FILE="${JORNADA_ENV_FILE:-$RAIZ/.env}"
DESTINO="${JORNADA_BACKUP_DIR:-/var/backups/jornada}"
LOG="${JORNADA_BACKUP_LOG:-/var/log/jornada-backup.log}"
CARIMBO="${JORNADA_BACKUP_STAMP:-/var/lib/jornada/backup-ultimo.json}"
RETENCAO_DIAS="${JORNADA_BACKUP_RETENCAO_DIAS:-14}"
# Piso de segurança da retenção, POR BANCO: por mais velhos que estejam, nunca deixar
# menos que isto de cada banco. Sem o piso, um host que ficou 3 semanas parado teria
# TODOS os backups apagados pela primeira execução ao voltar — a limpeza destruindo
# justamente o que se guardava.
RETENCAO_MINIMO="${JORNADA_BACKUP_MINIMO:-3}"
# 26h como no purge: diário com folga para atraso de cron/reboot, sem deixar passar um
# dia inteiro perdido.
MAX_HORAS="${JORNADA_BACKUP_MAX_H:-26}"
# Um dump menor que isto é sinal de dump truncado, não de "pouco dado".
#
# O piso precisa passar no caso que MAIS se parece com defeito e é legítimo: banco de
# PRODUÇÃO recém-migrado, com ZERO linhas. Medido (8e21341, `alembic upgrade head` num
# Postgres vazio; langfuse:2 recém-migrada): jornada VAZIO = 74.733 bytes, Langfuse
# recém-criada = 137.253 bytes. Os dois passam com folga de 3,7× e 6,9×. A margem
# importa porque a falha aqui é BLOQUEANTE — deploy.sh trata backup falho como falha de
# deploy, e um falso positivo reprovaria justamente o primeiro deploy de produção, com
# a mensagem errada ("banco vazio ou dump truncado") apontando para o lugar errado.
MIN_BYTES="${JORNADA_BACKUP_MIN_BYTES:-20000}"
# Cópia FORA do host (scp). Vazio = só disco local — ver "limites" no fim deste arquivo.
REMOTO="${JORNADA_BACKUP_REMOTO:-}"

agora() { date -u +%Y-%m-%dT%H:%M:%SZ; }

if ! { [ -e "$LOG" ] && [ -w "$LOG" ]; } && ! (umask 027 && touch "$LOG") 2>/dev/null; then
  LOG=/dev/null
  SEM_LOG=1
fi
log() { printf '%s %s\n' "$(agora)" "$*" >>"$LOG"; }
erro() {
  log "ERRO: $*"
  # stderr (→ MAILTO do cron) e syslog, pelo mesmo motivo do purge: numa VPS enxuta não
  # há MTA, e sem o syslog a única notificação de falha seria descartada em silêncio.
  printf '%s jornada-backup ERRO: %s\n' "$(agora)" "$*" >&2
  command -v logger >/dev/null 2>&1 && logger -t jornada-backup -p daemon.err -- "$*" || true
}

MODO=backup
case "${1:-}" in
  --status) MODO=status ;;
  --listar) MODO=listar ;;
  "" | --backup) MODO=backup ;;
  -h | --help)
    sed -n '2,/^set -euo/p' "$0" | sed '$d'
    exit 0
    ;;
  *)
    erro "argumento desconhecido: $1"
    exit 2
    ;;
esac

# ------------------------------------------------------------------ carimbo / status
idade_horas() {
  [ -r "$CARIMBO" ] || return 1
  local ts epoch_ts
  ts="$(sed -n 's/.*"ts":"\([^"]*\)".*/\1/p' "$CARIMBO")"
  [ -n "$ts" ] || return 1
  epoch_ts="$(date -u -d "$ts" +%s 2>/dev/null)" || return 1
  echo $((($(date -u +%s) - epoch_ts) / 3600))
}
resultado_carimbo() {
  [ -r "$CARIMBO" ] || return 1
  sed -n 's/.*"resultado":"\([^"]*\)".*/\1/p' "$CARIMBO"
}
gravar_carimbo() { # $1=resultado $2=detalhe
  mkdir -p "$(dirname "$CARIMBO")" 2>/dev/null || return 0
  printf '{"ts":"%s","resultado":"%s","detalhe":"%s","destino":"%s"}\n' \
    "$(agora)" "$1" "$2" "$DESTINO" >"$CARIMBO" 2>/dev/null || true
}

if [ "$MODO" = listar ]; then
  echo "backups em $DESTINO (retenção ${RETENCAO_DIAS}d, mínimo ${RETENCAO_MINIMO}):"
  ls -lh "$DESTINO"/*.enc 2>/dev/null || echo "  (nenhum)"
  idade="$(idade_horas 2>/dev/null || echo '?')"
  echo "último carimbo: ${idade}h atrás, resultado=$(resultado_carimbo 2>/dev/null || echo 'nunca rodou')"
  exit 0
fi

if [ "$MODO" = status ]; then
  # Mesmo desenho do purge: um script não relata a própria ausência, então quem relata é
  # este modo, chamado por uma SEGUNDA linha de cron em outro horário.
  if ! idade="$(idade_horas)"; then
    erro "backup dos bancos NUNCA rodou (sem $CARIMBO). Não há de onde restaurar."
    exit 3
  fi
  resultado="$(resultado_carimbo || echo desconhecido)"
  if [ "$resultado" != "ok" ]; then
    erro "último backup terminou como '$resultado' (há ${idade}h) — ver $LOG"
    exit 3
  fi
  # Carimbo no futuro passaria por qualquer comparação `-gt` e o vigia diria "em dia"
  # para sempre (relógio do host errado, restauração de snapshot, edição à mão).
  if [ "$idade" -lt 0 ]; then
    erro "carimbo $CARIMBO está no FUTURO (${idade}h) — relógio do host ou arquivo
       adulterado. Trate como NÃO rodou."
    exit 3
  fi
  if [ "$idade" -gt "$MAX_HORAS" ]; then
    erro "último backup OK foi há ${idade}h (limite ${MAX_HORAS}h) — o cron não está rodando"
    exit 3
  fi
  # O carimbo diz que rodou; conferir que o ARQUIVO existe fecha a diferença entre
  # "o script terminou bem" e "existe um backup". Não são a mesma coisa: alguém pode ter
  # limpado /var/backups depois.
  recentes="$(find "$DESTINO" -name '*.enc' -mtime -2 2>/dev/null | wc -l)"
  if [ "$recentes" -lt 2 ]; then
    erro "carimbo diz OK há ${idade}h, mas há só $recentes arquivo(s) .enc recente(s) em
       $DESTINO (esperado 2: jornada + langfuse). Alguém apagou, ou o destino mudou."
    exit 3
  fi
  log "status: último backup OK há ${idade}h, $recentes arquivo(s) recente(s)"
  exit 0
fi

# ------------------------------------------------------------------ pré-condições
command -v docker >/dev/null || {
  erro "docker ausente — não há como chamar o pg_dump dentro dos containers"
  exit 2
}
command -v openssl >/dev/null || {
  erro "openssl ausente — o backup seria gravado EM CLARO; recuso"
  exit 2
}

# A senha vive só no .env do servidor (0600, root), gerada pelo deploy. Nunca no
# repositório, nunca no CI, e — como o cron não herda ambiente — lida do arquivo.
SENHA="${JORNADA_BACKUP_PASSPHRASE:-}"
if [ -z "$SENHA" ] && [ -r "$ENV_FILE" ]; then
  SENHA="$(sed -n 's/^[[:space:]]*JORNADA_BACKUP_PASSPHRASE=//p' "$ENV_FILE" | tail -n 1 |
    sed -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'$/\1/" -e 's/[[:space:]]*$//')"
fi
if [ "${#SENHA}" -lt 32 ]; then
  gravar_carimbo "config" "passphrase ausente ou curta"
  erro "JORNADA_BACKUP_PASSPHRASE ausente ou com menos de 32 caracteres em $ENV_FILE.
       Gere com: openssl rand -hex 32  (e GUARDE FORA DA VPS — sem ela o backup é lixo
       cifrado; com ela num backup roubado, o backup é PII em claro)."
  exit 2
fi

mkdir -p "$DESTINO"
chmod 700 "$DESTINO" # dump de PII: nem `others`, nem `group`

# Espaço: um pg_dump que enche o disco derruba o Postgres que está sendo copiado — o
# backup causando a indisponibilidade. 2 GiB livres é o piso.
livre_kb="$(df -Pk "$DESTINO" | awk 'NR==2{print $4}')"
if [ "${livre_kb:-0}" -lt 2097152 ]; then
  gravar_carimbo "falha" "disco cheio"
  erro "menos de 2 GiB livres em $DESTINO ($((livre_kb / 1024)) MiB) — abortando ANTES
       de começar: um dump que enche o disco derruba o banco que ele copia."
  exit 1
fi

# Descoberta do container: o compose é a fonte da verdade; o nome fixo é o plano B para
# quando o compose não puder ser lido (ex.: `.env` sem alguma variável obrigatória, que
# faz `docker compose ps` sair diferente de zero).
container_de() { # $1=serviço  $2=nome fixo de fallback
  local id
  id="$(docker compose -f "$RAIZ/docker-compose.prod.yml" --env-file "$ENV_FILE" \
    ps -q "$1" 2>/dev/null | head -n 1)" || true
  if [ -n "$id" ]; then echo "$id"; else echo "$2"; fi
}

# ------------------------------------------------------------------------- execução
if anterior="$(idade_horas)"; then
  log "início — anterior há ${anterior}h, resultado=$(resultado_carimbo || echo '?')"
else
  log "início — primeira execução registrada neste host"
fi
[ "${SEM_LOG:-0}" = 1 ] && erro "sem permissão de escrita no log ($LOG) — seguindo só pelo stderr"

DATA="$(date -u +%Y%m%dT%H%M%SZ)"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/jornada-backup.XXXXXX")"
chmod 700 "$TMP"
# O temporário guarda o dump EM CLARO por alguns segundos. O trap garante que ele morre
# mesmo se o script for interrompido — senão a PII fica em /tmp até o próximo boot.
trap 'rm -rf "$TMP"' EXIT INT TERM

falhas=0
gerados=""

copiar_banco() { # $1=rótulo  $2=container  $3=usuário  $4=database  $5=tabelas do manifesto
  local rotulo="$1" cont="$2" usuario="$3" banco="$4" tabelas="$5"
  local cru="$TMP/$rotulo.dump" alvo="$DESTINO/${rotulo}-${DATA}.dump.enc"

  if ! docker exec "$cont" pg_dump -U "$usuario" -d "$banco" -Fc --no-owner --no-acl \
    >"$cru" 2>"$TMP/$rotulo.err"; then
    erro "pg_dump falhou para $rotulo ($cont): $(tr -d '\n' <"$TMP/$rotulo.err" | cut -c1-300)"
    falhas=$((falhas + 1))
    return 1
  fi
  # `-Fc` grava um cabeçalho próprio; um dump truncado costuma passar despercebido pelo
  # tamanho, então além do piso de bytes o pg_restore --list é chamado como conferência
  # barata de integridade estrutural ANTES de cifrar (o custo é ler o índice, não os dados).
  local bytes
  bytes="$(stat -c %s "$cru" 2>/dev/null || echo 0)"
  if [ "$bytes" -lt "$MIN_BYTES" ]; then
    erro "dump de $rotulo tem só $bytes bytes (piso $MIN_BYTES) — banco vazio ou dump truncado"
    falhas=$((falhas + 1))
    return 1
  fi
  if ! docker exec -i "$cont" pg_restore --list >/dev/null 2>"$TMP/$rotulo.lst.err" <"$cru"; then
    erro "o dump de $rotulo não passa no pg_restore --list — arquivo corrompido, NÃO
       vou publicá-lo como backup: $(tr -d '\n' <"$TMP/$rotulo.lst.err" | cut -c1-200)"
    falhas=$((falhas + 1))
    return 1
  fi

  # MANIFESTO — contagens da ORIGEM, colhidas agora (logo após o dump). É o que permite
  # ao restaura_teste.sh perguntar "voltou o que havia?" em vez de "voltou pelo menos 1
  # linha?". A diferença não é cosmética: um piso fixo (`os >= 1`) reprova um banco de
  # produção RECÉM-CRIADO, que legitimamente tem zero OS — as seeds da OS-2026-0457 só
  # rodam com DEMO_MODE=true E APP_ENV=dev (backend/app/main.py:182), e o root é semeado
  # sob demanda na primeira chamada de auth (api/v1/autenticacao.py:171). Em prod, no
  # instante do deploy, `os` e `usuario` estão vazias e ESTÃO CERTAS. Comparar com a
  # origem distingue "banco novo e vazio" (ok) de "dump só de estrutura" (falha), que o
  # piso fixo confunde. Só contagens entram aqui — nenhum dado, nenhuma PII.
  local manifesto_txt="" t n
  for t in $tabelas; do
    n="$(docker exec "$cont" psql -U "$usuario" -d "$banco" -tAc \
      "select count(*) from \"$t\"" 2>/dev/null | tr -d '[:space:]')"
    [ -n "$n" ] || n="?" # tabela ausente nesta versão do schema: registra, não quebra
    manifesto_txt="${manifesto_txt}${t}=${n}"$'\n'
  done

  # Cifra. `-pass fd:3` mantém a senha fora de argv (este host tem outros inquilinos).
  # Escreve num `.parcial` e só renomeia no fim: um `.enc` existente é sempre completo,
  # e o restaura_teste.sh nunca pega um arquivo em construção.
  if ! openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt \
    -in "$cru" -out "$alvo.parcial" -pass fd:3 3< <(printf '%s' "$SENHA"); then
    erro "openssl falhou ao cifrar $rotulo"
    rm -f "$alvo.parcial"
    falhas=$((falhas + 1))
    return 1
  fi
  mv "$alvo.parcial" "$alvo"
  chmod 600 "$alvo"
  # Checksum do arquivo CIFRADO: detecta bit-rot em disco e corrupção na cópia remota,
  # sem precisar da senha para conferir.
  sha256sum "$alvo" | awk '{print $1}' >"$alvo.sha256"
  # O manifesto acompanha o .enc e é lido pelo restaura_teste.sh. Fica EM CLARO de
  # propósito: são contagens, não conteúdo, e precisam ser legíveis sem a passphrase
  # (quem confere a restauração pode não ser quem guarda a chave). Não é controle de
  # segurança — quem consegue editar o manifesto já consegue editar o dump.
  printf '%s' "$manifesto_txt" >"$alvo.manifesto"
  chmod 600 "$alvo.manifesto"
  shred -u "$cru" 2>/dev/null || rm -f "$cru"

  log "$rotulo: $(numfmt --to=iec "$bytes" 2>/dev/null || echo "$bytes")B em claro → $(basename "$alvo")"
  gerados="$gerados $(basename "$alvo")"
  return 0
}

copiar_banco jornada "$(container_de db jornada-db-1)" jornada jornada "os usuario politica_ia" || true
copiar_banco langfuse "$(container_de db-langfuse jornada-db-langfuse-1)" langfuse langfuse "users" || true

# --------------------------------------------------------------- cópia fora do host
# O disco da VPS morre junto com o banco: backup no mesmo /dev/sda1 protege contra
# `docker volume rm` e contra erro humano no banco, mas NÃO contra perda do host.
if [ -n "$REMOTO" ] && [ "$falhas" -eq 0 ]; then
  if scp -q -o BatchMode=yes -o ConnectTimeout=20 \
    "$DESTINO"/*-"$DATA".dump.enc "$DESTINO"/*-"$DATA".dump.enc.sha256 \
    "$DESTINO"/*-"$DATA".dump.enc.manifesto "$REMOTO/" 2>>"$LOG"; then
    log "cópia remota enviada para $REMOTO"
  else
    # Não derruba o backup local (que existe e é válido), mas é falha de verdade: a
    # partir daqui só há uma cópia, e ela mora no disco que se quer sobreviver.
    erro "cópia remota para $REMOTO FALHOU — o backup existe SÓ no disco desta VPS"
    falhas=$((falhas + 1))
  fi
fi

# ------------------------------------------------------------------------- retenção
# Só limpa se o backup de hoje deu certo: apagar o antigo depois de falhar em gerar o
# novo é como se perde tudo em duas madrugadas.
if [ "$falhas" -eq 0 ]; then
  # O piso é POR BANCO, não pelo total. Contando os dois juntos, um piso de 3 significa
  # 1,5 dia de histórico — e, pior, um banco cujo dump venha falhando há semanas pode ser
  # zerado enquanto o piso continua satisfeito pelas cópias do OUTRO banco. Cada banco
  # precisa sobreviver por si.
  removidos=0
  for rotulo in jornada langfuse; do
    total="$(find "$DESTINO" -name "${rotulo}-*.dump.enc" | wc -l)"
    while IFS= read -r velho; do
      [ "$total" -le "$RETENCAO_MINIMO" ] && break
      rm -f "$velho" "$velho.sha256" "$velho.manifesto"
      total=$((total - 1))
      removidos=$((removidos + 1))
    done < <(find "$DESTINO" -name "${rotulo}-*.dump.enc" -mtime +"$RETENCAO_DIAS" | sort)
  done
  [ "$removidos" -gt 0 ] && log "retenção: $removidos arquivo(s) com mais de ${RETENCAO_DIAS}d removidos"
fi

if [ "$falhas" -gt 0 ]; then
  gravar_carimbo "falha" "$falhas etapa(s) falharam"
  log "fim: $falhas falha(s) — exit 1"
  exit 1
fi
gravar_carimbo "ok" "gerados:${gerados}"
log "fim: ok —${gerados}"
exit 0

# ----------------------------------------------------------------- LIMITES DECLARADOS
# 1. UMA CÓPIA, UM DISCO. Sem `JORNADA_BACKUP_REMOTO` configurado, o backup mora no
#    mesmo /dev/sda1 do banco. Protege contra `docker volume rm`, `down -v`, DROP TABLE e
#    corrupção lógica — NÃO protege contra perda do host, que é o cenário que a pergunta
#    "e se o disco morrer?" descreve. Levar cópia para fora exige um destino e uma
#    credencial que esta frente não pode criar sem escolher um fornecedor e gastar
#    dinheiro do dono; o gancho está pronto (scp/BatchMode, chave só de escrita), a
#    decisão é dele. Enquanto estiver vazio, o RPO é honesto: 24h para erro lógico,
#    INFINITO para perda de disco.
# 2. CHAVE NA MESMA MÁQUINA. A passphrase está no .env do host que gera o backup. Isso
#    protege a cópia que SAI daqui e o descarte do disco; NÃO protege contra quem
#    conseguir root nesta VPS — esse leva o dump e a chave. A evolução é cifra
#    assimétrica (`age -r <pubkey>`), com a privada fora do host; o preço é que o
#    restaura_teste.sh deixa de rodar sozinho, e teste de restauração automático vale
#    mais, hoje, que essa camada.
# 3. NÃO INCLUI: os volumes em si, `pg_dumpall --globals` (papéis/senhas do cluster — há
#    um papel por banco, recriado pelo compose), nem o `.env` do servidor. Restaurar do
#    zero exige o `.env` (APP_SECRET, senhas), que por definição não pode entrar aqui.
#    Guarde-o à parte, com a passphrase.
