#!/usr/bin/env bash
# TESTE DE RESTAURAÇÃO (SDD §10.2) — restaura num container DESCARTÁVEL e CONFERE.
#
# Backup não testado não é backup: é uma pasta de arquivos com nome de backup. Todo modo
# de falha que interessa (dump truncado com exit 0, senha errada, imagem sem a extensão
# `vector`, retenção que comeu o único arquivo bom) é INVISÍVEL até o dia em que alguém
# precisa restaurar — e nesse dia não há segunda chance. Este script transforma essa
# descoberta num evento agendado e barato, em vez de um evento único e caro.
#
# O que ele NÃO faz: não toca nos bancos de produção, em momento algum. Sobe um Postgres
# novo, sem porta publicada, restaura ali dentro, pergunta, e destrói. Rodar isto no meio
# do expediente é seguro — é justamente para poder rodar sempre que ele é assim.
#
# A imagem do container descartável NÃO é `postgres:16`: o banco do Jornada usa a
# extensão `vector` (pgvector, tabela `agente_evidence` do RAG §7.4). Restaurar num
# Postgres sem a extensão falha no `CREATE EXTENSION` e leva junto tudo que vem depois.
# Este é exatamente o tipo de detalhe que só aparece quando se testa a restauração — e o
# motivo pelo qual "temos pg_dump agendado" não é resposta para "temos backup?".
#
# Uso:
#   ./restaura_teste.sh                    # último backup de cada banco (é o do cron)
#   ./restaura_teste.sh --arquivo X.enc    # um arquivo específico
#   ./restaura_teste.sh --status           # "quando foi o último teste que PASSOU?"
#
# Exit: 0 = restaurou e conferiu · 1 = falhou (o backup NÃO serve) · 2 = configuração
#       ausente · 3 = --status atrasado
set -euo pipefail

RAIZ="${JORNADA_RAIZ:-/opt/jornada}"
ENV_FILE="${JORNADA_ENV_FILE:-$RAIZ/.env}"
DESTINO="${JORNADA_BACKUP_DIR:-/var/backups/jornada}"
LOG="${JORNADA_RESTORE_LOG:-/var/log/jornada-restore-teste.log}"
CARIMBO="${JORNADA_RESTORE_STAMP:-/var/lib/jornada/restore-teste-ultimo.json}"
# Semanal + folga para reboot/atraso. Um teste de restauração de 9 dias atrás ainda diz
# alguma coisa; de 30 dias, não diz nada sobre o backup de ontem.
MAX_HORAS="${JORNADA_RESTORE_MAX_H:-193}"
IMAGEM_JORNADA="${JORNADA_RESTORE_IMG:-pgvector/pgvector:pg16}"
IMAGEM_LANGFUSE="${JORNADA_RESTORE_IMG_LF:-postgres:16-alpine}"
# Pisos de sanidade das TABELAS (estrutura, não conteúdo — o conteúdo é conferido contra
# o manifesto, em `conferir_dados`).
#
# MEDIDO, não estimado (8e21341, `alembic upgrade head` num Postgres vazio + langfuse:2
# recém-migrada, com a MESMA consulta que este script usa — `information_schema.tables`
# em `public`): jornada 42 tabelas, Langfuse 35. Uma versão anterior deste comentário
# dizia 36/31; os pisos abaixo já eram conservadores o bastante para os dois números,
# mas provenance errada é o que faz alguém "ajustar" o piso para perto do valor errado.
# Os pisos ficam abaixo do medido de propósito (migração nova não pode quebrar o teste),
# e MUITO acima de zero — restaurar "com sucesso" um banco de 3 tabelas é o desfecho que
# se quer pegar. Ao contrário das linhas, a contagem de tabelas NÃO depende do ambiente:
# vem do `alembic upgrade head`, igual em dev e em prod.
PISO_TABELAS_JORNADA="${JORNADA_RESTORE_PISO:-30}"
PISO_TABELAS_LANGFUSE="${JORNADA_RESTORE_PISO_LF:-25}"

agora() { date -u +%Y-%m-%dT%H:%M:%SZ; }
if ! { [ -e "$LOG" ] && [ -w "$LOG" ]; } && ! (umask 027 && touch "$LOG") 2>/dev/null; then
  LOG=/dev/null
fi
log() { printf '%s %s\n' "$(agora)" "$*" >>"$LOG"; }
diga() {
  printf '%s\n' "$*"
  log "$*"
}
erro() {
  log "ERRO: $*"
  printf '%s jornada-restore-teste ERRO: %s\n' "$(agora)" "$*" >&2
  command -v logger >/dev/null 2>&1 && logger -t jornada-restore-teste -p daemon.err -- "$*" || true
}

ARQUIVO_FIXO=""
MODO=testar
while [ $# -gt 0 ]; do
  case "$1" in
    --status) MODO=status ;;
    --arquivo)
      ARQUIVO_FIXO="${2:-}"
      shift
      ;;
    -h | --help)
      sed -n '2,/^set -euo/p' "$0" | sed '$d'
      exit 0
      ;;
    *)
      erro "argumento desconhecido: $1"
      exit 2
      ;;
  esac
  shift
done

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
gravar_carimbo() {
  mkdir -p "$(dirname "$CARIMBO")" 2>/dev/null || return 0
  printf '{"ts":"%s","resultado":"%s","detalhe":"%s"}\n' "$(agora)" "$1" "$2" >"$CARIMBO" 2>/dev/null || true
}

if [ "$MODO" = status ]; then
  if ! idade="$(idade_horas)"; then
    erro "o teste de restauração NUNCA rodou. Existem arquivos de backup, mas ninguém
       jamais provou que eles restauram — trate-os como inexistentes até o primeiro
       teste verde: $RAIZ/scripts/restaura_teste.sh"
    exit 3
  fi
  resultado="$(resultado_carimbo || echo desconhecido)"
  if [ "$resultado" != "ok" ]; then
    erro "último teste de restauração terminou como '$resultado' (há ${idade}h) — o
       backup NÃO está provado. Ver $LOG"
    exit 3
  fi
  if [ "$idade" -lt 0 ]; then
    erro "carimbo $CARIMBO está no FUTURO (${idade}h) — relógio ou adulteração; trate como não rodou"
    exit 3
  fi
  if [ "$idade" -gt "$MAX_HORAS" ]; then
    erro "último teste de restauração OK foi há ${idade}h (limite ${MAX_HORAS}h)"
    exit 3
  fi
  log "status: último teste de restauração OK há ${idade}h"
  exit 0
fi

# ------------------------------------------------------------------ pré-condições
command -v docker >/dev/null || {
  erro "docker ausente"
  exit 2
}
SENHA="${JORNADA_BACKUP_PASSPHRASE:-}"
if [ -z "$SENHA" ] && [ -r "$ENV_FILE" ]; then
  SENHA="$(sed -n 's/^[[:space:]]*JORNADA_BACKUP_PASSPHRASE=//p' "$ENV_FILE" | tail -n 1 |
    sed -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'$/\1/" -e 's/[[:space:]]*$//')"
fi
if [ "${#SENHA}" -lt 32 ]; then
  gravar_carimbo "config" "passphrase ausente"
  erro "JORNADA_BACKUP_PASSPHRASE ausente em $ENV_FILE — sem ela não há como abrir o backup"
  exit 2
fi

TMP="$(mktemp -d "${TMPDIR:-/tmp}/jornada-restore.XXXXXX")"
chmod 700 "$TMP"
CONTAINERS=""
limpar() {
  # O container descartável precisa morrer SEMPRE — inclusive se o script for morto no
  # meio. Um Postgres esquecido rodando com uma cópia da base de clientes dentro é um
  # vazamento criado pelo próprio teste de segurança.
  for c in $CONTAINERS; do docker rm -f "$c" >/dev/null 2>&1 || true; done
  rm -rf "$TMP"
}
trap limpar EXIT INT TERM

ultimo_backup() { # $1=rótulo
  find "$DESTINO" -name "${1}-*.dump.enc" -type f 2>/dev/null | sort | tail -n 1
}

falhas=0
relatorio=""
# Quantos bancos passaram SEM a conferência de dados de `conferir_dados` (manifesto
# ausente). Não é falha de restauração — mas também NÃO é prova, e precisa chegar ao
# veredito. Sem este contador o script imprimia "RESTAURAÇÃO PROVADA" e carimbava `ok`
# justamente quando a pergunta central ("voltou o que havia?") não tinha sido feita:
# o mesmo padrão de falso verde que este arquivo existe para não deixar acontecer.
sem_manifesto=0

# Compara o banco RESTAURADO com o `.manifesto` que o backup gravou ao lado do `.enc`
# (contagens da ORIGEM no instante do dump).
#
# Por que não um piso fixo ("os >= 1"), que é o desenho óbvio: ele reprova um banco de
# produção CORRETO. As seeds da OS-2026-0457 só rodam com DEMO_MODE=true E APP_ENV=dev
# (backend/app/main.py:182) e o root é semeado sob demanda, na primeira chamada de auth
# (backend/api/v1/autenticacao.py:171) — logo, num host de prod recém-subido, `os` e
# `usuario` estão VAZIAS e estão certas. Com piso fixo, o primeiro deploy de produção
# falharia (deploy.sh trata o teste de restauração como bloqueante), e falharia dizendo
# "não há backup" quando o backup está perfeito. Medir em dev e concluir sobre prod é
# exatamente o erro que esta verificação existe para não cometer.
#
# Comparar com a origem preserva o que importa e some com o falso positivo:
#   origem 2 → restaurado 0  = FALHA (é o caso do dump `--schema-only`)
#   origem 0 → restaurado 0  = ok    (banco novo, legítimo)
#   origem 2 → restaurado 2  = ok
#
# `perguntar` é definida dentro de testar_banco (fica global depois da 1ª chamada) e já
# existe quando esta função roda — ela pergunta sempre ao container em teste do momento.
conferir_dados() { # $1=rótulo  $2=arquivo .enc  $3=tabelas
  local rotulo="$1" enc="$2" tabelas="$3"
  local manifesto="$enc.manifesto" t esperado restaurado linha="" divergencias=""

  if [ ! -r "$manifesto" ]; then
    # Sem manifesto não há como saber se voltou TUDO o que havia — só dá para listar o
    # que veio. Registrar isso no contador é o que impede o veredito final de chamar de
    # PROVADA uma execução em que esta conferência foi PULADA. Quem gera o `.enc` gera o
    # `.manifesto` ao lado (backup_bancos.sh), então, no caminho automático, ausência
    # aqui significa arquivo apagado/adulterado — e o fim do script trata como falha.
    sem_manifesto=$((sem_manifesto + 1))
    for t in $tabelas; do
      restaurado="$(perguntar "select count(*) from \"$t\"")"
      linha="$linha $t=${restaurado:-?}"
    done
    diga "  linhas:$linha  (sem .manifesto ao lado — não dá para afirmar que voltou tudo)"
    return 0
  fi

  for t in $tabelas; do
    esperado="$(sed -n "s/^${t}=//p" "$manifesto" | head -n 1)"
    restaurado="$(perguntar "select count(*) from \"$t\"")"
    restaurado="${restaurado:-0}"
    linha="$linha $t=$restaurado/${esperado:-?}"
    # Origem que não soube contar (tabela ausente naquela versão do schema): nada a
    # comparar. O `*[!0-9]*` também blinda o `[ -gt ]` abaixo contra lixo no manifesto.
    case "$esperado" in '' | *[!0-9]*) continue ;; esac
    if [ "$esperado" -gt 0 ] && [ "$restaurado" -eq 0 ]; then
      erro "$rotulo: '$t' tinha $esperado linha(s) na ORIGEM e voltou VAZIA. O dump
       trouxe estrutura e não conteúdo — restauração inútil."
      falhas=$((falhas + 1))
      return 1
    fi
    [ "$restaurado" != "$esperado" ] && divergencias="$divergencias $t($esperado→$restaurado)"
  done
  diga "  linhas (restaurado/origem):$linha"
  if [ -n "$divergencias" ]; then
    # Não é falha: o pg_dump é o retrato de UMA transação e o manifesto é colhido logo
    # DEPOIS dele, então escrita concorrente durante o dump gera diferença legítima de
    # poucas linhas. O caso que É falha — voltar vazio o que tinha conteúdo — já saiu
    # acima. A divergência fica registrada para quem lê o log.
    diga "  atenção: divergência origem→restaurado em$divergencias (escrita durante o dump?)"
  fi
  return 0
}

testar_banco() { # $1=rótulo  $2=imagem  $3=piso de tabelas
  local rotulo="$1" imagem="$2" piso="$3"
  local enc cru cont porta_pronta
  cont="jornada-restore-teste-$rotulo-$$"

  if [ -n "$ARQUIVO_FIXO" ]; then enc="$ARQUIVO_FIXO"; else enc="$(ultimo_backup "$rotulo")"; fi
  if [ -z "$enc" ] || [ ! -r "$enc" ]; then
    erro "$rotulo: nenhum backup encontrado em $DESTINO — nada a testar (e nada a restaurar)"
    falhas=$((falhas + 1))
    return 1
  fi
  diga "== $rotulo == $(basename "$enc") ($(du -h "$enc" | cut -f1), $(( ($(date +%s) - $(stat -c %Y "$enc")) / 3600 ))h)"

  # 1. Integridade do arquivo ANTES de gastar um container: o sha256 pega bit-rot em
  #    disco e cópia truncada sem precisar da senha.
  if [ -r "$enc.sha256" ]; then
    if [ "$(sha256sum "$enc" | awk '{print $1}')" != "$(cat "$enc.sha256")" ]; then
      erro "$rotulo: sha256 NÃO confere — arquivo corrompido em disco. NÃO restaure com ele."
      falhas=$((falhas + 1))
      return 1
    fi
    diga "  sha256 confere"
  else
    diga "  (sem .sha256 ao lado — arquivo antigo?)"
  fi

  # 2. Decifra. Senha por fd, nunca por argv.
  cru="$TMP/$rotulo.dump"
  if ! openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 \
    -in "$enc" -out "$cru" -pass fd:3 3< <(printf '%s' "$SENHA"); then
    erro "$rotulo: falha ao DECIFRAR. A passphrase do .env não abre este arquivo — se ela
       foi trocada depois do backup, todos os backups anteriores estão perdidos."
    falhas=$((falhas + 1))
    return 1
  fi
  diga "  decifrado ($(du -h "$cru" | cut -f1))"

  # 3. Container descartável, SEM porta publicada (não se fala com ele pela rede; tudo
  #    por `docker exec`). Um Postgres de teste com a base real e porta aberta seria um
  #    banco de produção sem senha.
  docker run -d --rm --name "$cont" \
    -e POSTGRES_PASSWORD=teste-descartavel-$$ -e POSTGRES_DB=restaurado \
    --network none "$imagem" >/dev/null || {
    erro "$rotulo: não subiu o container de teste ($imagem)"
    falhas=$((falhas + 1))
    return 1
  }
  CONTAINERS="$CONTAINERS $cont"

  # Espera pelo BANCO, não pelo servidor. `pg_isready` não serve aqui: a imagem oficial
  # sobe um Postgres TEMPORÁRIO só no socket durante o initdb, antes de criar o
  # POSTGRES_DB e antes de reiniciar no modo definitivo. Nessa janela o pg_isready já
  # responde "accepting connections" e o pg_restore seguinte morre com
  # `FATAL: database "restaurado" does not exist` — uma falha de CORRIDA, que aparece
  # em algumas execuções e não em outras. Um teste de restauração intermitente é pior
  # que nenhum: ensina a ignorar o vermelho. Um `select 1` DENTRO do banco alvo só
  # passa quando o servidor definitivo está no ar com o banco criado.
  porta_pronta=0
  for _ in $(seq 1 60); do
    if docker exec "$cont" psql -U postgres -d restaurado -tAc 'select 1' >/dev/null 2>&1; then
      porta_pronta=1
      break
    fi
    sleep 2
  done
  if [ "$porta_pronta" -ne 1 ]; then
    erro "$rotulo: o banco de teste não ficou pronto em 120s (imagem $imagem)"
    falhas=$((falhas + 1))
    return 1
  fi

  # 4. RESTAURA. `--exit-on-error`: sem ele o pg_restore engole erro de objeto e sai 0 —
  #    "restaurou com sucesso" um banco sem metade das tabelas é precisamente a mentira
  #    que este script existe para não deixar contar.
  if ! docker exec -i "$cont" pg_restore -U postgres -d restaurado \
    --no-owner --no-acl --exit-on-error >"$TMP/$rotulo.out" 2>"$TMP/$rotulo.err" <"$cru"; then
    erro "$rotulo: pg_restore FALHOU — este backup NÃO restaura:
       $(tail -n 5 "$TMP/$rotulo.err" | tr '\n' ' ' | cut -c1-400)"
    falhas=$((falhas + 1))
    return 1
  fi
  diga "  pg_restore ok"

  # ------------------------------------------------------------- 5. CONFERÊNCIAS
  perguntar() { docker exec "$cont" psql -U postgres -d restaurado -tAc "$1" 2>/dev/null | tr -d '[:space:]'; }

  local n_tabelas
  n_tabelas="$(perguntar "select count(*) from information_schema.tables where table_schema='public'")"
  if [ "${n_tabelas:-0}" -lt "$piso" ]; then
    erro "$rotulo: restaurou só ${n_tabelas:-0} tabela(s), piso é $piso. O dump está
       incompleto — restaurar isto em produção perderia dados sem avisar."
    falhas=$((falhas + 1))
    return 1
  fi
  diga "  tabelas: $n_tabelas (piso $piso)"

  if [ "$rotulo" = jornada ]; then
    # 5a. A extensão do RAG. Se o dump veio de um banco com `vector` e a restauração
    #     silenciou o CREATE EXTENSION, a coluna de embedding não existe e o §7.4 volta
    #     morto. (É também o teste de que a IMAGEM escolhida serve.)
    local ext
    ext="$(perguntar "select count(*) from pg_extension where extname='vector'")"
    if [ "${ext:-0}" -lt 1 ]; then
      erro "jornada: extensão 'vector' AUSENTE no banco restaurado — a imagem $imagem não
       a tem, ou o dump não a trouxe. O RAG (§7.4) não volta com este backup."
      falhas=$((falhas + 1))
      return 1
    fi
    diga "  extensão vector presente"

    # 5b. A migração. `alembic_version` vazia significa schema restaurado sem marca de
    #     versão: o próximo `alembic upgrade head` tentaria recriar tudo do zero.
    local ver
    ver="$(perguntar "select version_num from alembic_version limit 1")"
    if [ -z "$ver" ]; then
      erro "jornada: alembic_version VAZIA no banco restaurado — o schema voltaria sem
       saber em que migração está."
      falhas=$((falhas + 1))
      return 1
    fi
    diga "  alembic_version: $ver"

    # 5c. Os DADOS — ver `conferir_dados`. A pergunta é "voltou o que HAVIA?", contra o
    #     manifesto escrito pelo backup, e NÃO "voltou pelo menos 1 linha".
    conferir_dados "$rotulo" "$enc" "os usuario politica_ia" || return 1

    # 5d. Uma leitura de VERDADE, com join — prova que índices, tipos e constraints
    #     voltaram utilizáveis, não só que as linhas existem. Vale mesmo com as tabelas
    #     vazias: um join que falha por chave ausente falha com zero linhas também.
    if ! perguntar "select count(*) from os o join os_thread t on t.os_id = o.id" >/dev/null; then
      erro "jornada: o join os×os_thread falhou no banco restaurado — chaves/índices não voltaram"
      falhas=$((falhas + 1))
      return 1
    fi
    diga "  consulta com join: ok"
    relatorio="$relatorio jornada(tabelas=$n_tabelas,alembic=$ver)"
  else
    # A Langfuse recebe a MESMA conferência do jornada. Antes ela só imprimia `users=N`
    # sem julgar nada: um dump só de estrutura da Langfuse passava calado.
    conferir_dados "$rotulo" "$enc" "users" || return 1
    relatorio="$relatorio langfuse(tabelas=$n_tabelas)"
  fi

  # 6. O container morre aqui, não no fim de tudo: dois Postgres com cópia da base viva
  #    ao mesmo tempo é o dobro de exposição por nenhum ganho.
  docker rm -f "$cont" >/dev/null 2>&1 || true
  CONTAINERS="${CONTAINERS// $cont/}"
  shred -u "$cru" 2>/dev/null || rm -f "$cru"
  diga "  container descartado"
  return 0
}

diga "== teste de restauração · $(agora) =="
testar_banco jornada "$IMAGEM_JORNADA" "$PISO_TABELAS_JORNADA" || true
if [ -z "$ARQUIVO_FIXO" ]; then
  testar_banco langfuse "$IMAGEM_LANGFUSE" "$PISO_TABELAS_LANGFUSE" || true
fi

# O carimbo é a memória de "o backup DO CRON foi provado", lida por `--status` e pelo
# deploy.sh. Uma execução `--arquivo` examina um arquivo escolhido à mão — pode ser de
# outro host, de outra época, ou o único que alguém sabia estar bom. Deixá-la carimbar
# faria `--status` ficar verde por 8 dias sem que o backup CORRENTE tivesse sido testado:
# perícia avulsa não é vigilância, e não pode se passar por ela.
carimbar() {
  if [ -n "$ARQUIVO_FIXO" ]; then
    diga "  (verificação avulsa --arquivo: não atualiza o carimbo de $CARIMBO)"
    return 0
  fi
  gravar_carimbo "$1" "$2"
}

if [ "$falhas" -gt 0 ]; then
  carimbar "falha" "$falhas banco(s) não restauraram"
  erro "TESTE DE RESTAURAÇÃO FALHOU em $falhas banco(s). Até isto passar, considere que
       NÃO HÁ BACKUP — os arquivos existem, a restauração não foi provada."
  exit 1
fi

# Restaurou, mas sem o manifesto a conferência de DADOS não aconteceu. No caminho
# automático isso é falha: o backup_bancos.sh escreve o `.manifesto` junto de todo
# `.enc`, logo a ausência é arquivo apagado, retenção pela metade ou adulteração — e
# nenhuma dessas é uma condição em que se deva anunciar backup provado e seguir o deploy.
if [ "$sem_manifesto" -gt 0 ] && [ -z "$ARQUIVO_FIXO" ]; then
  carimbar "falha" "$sem_manifesto banco(s) sem .manifesto"
  erro "restaurou, mas $sem_manifesto banco(s) vieram SEM o .manifesto ao lado do .enc —
       a conferência de dados não pôde rodar. NÃO afirmo que o backup está provado: um
       dump só de estrutura passaria por aqui calado. Confira $DESTINO (o manifesto é
       escrito pelo backup; se sumiu, algo o apagou) e rode o backup de novo."
  exit 1
fi
if [ "$sem_manifesto" -gt 0 ]; then
  # Só chega aqui com --arquivo: perícia manual, veredito PARCIAL e honesto.
  carimbar "parcial" ""
  diga "RESTAUROU (parcial — sem .manifesto, dados não conferidos):$relatorio"
  exit 0
fi

carimbar "ok" "$(echo "$relatorio" | sed 's/"/ /g' | cut -c1-200)"
diga "RESTAURAÇÃO PROVADA:$relatorio"
exit 0
