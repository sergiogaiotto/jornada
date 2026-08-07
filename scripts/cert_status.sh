#!/usr/bin/env bash
# "O certificado vence quando?" — vigia da renovação TLS (SDD §10.3).
#
# Por que existe: a renovação em si já é automática (o pacote certbot traz o
# `certbot.timer`, que neste host está ATIVO e roda 2x/dia). O que NÃO existe é alguém
# perceber quando ela para de funcionar. E o modo de falha é o pior possível: silencioso
# por 60 dias e depois total. Certificado vencido não degrada — o navegador recusa a
# conexão ANTES de qualquer byte da aplicação, então a plataforma inteira cai de uma vez,
# para todo mundo, num domingo. É a lição do F04 aplicada ao TLS: automatismo sem vigia
# é automatismo que ninguém sabe que morreu.
#
# Duas perguntas independentes, porque falham por motivos diferentes:
#   1. O ARQUIVO está válido por quanto tempo? (renovação não rodou / falhou)
#   2. O que a :443 REALMENTE SERVE é esse arquivo? (renovou o arquivo e o nginx seguiu
#      servindo o antigo da memória — acontece sempre que falta o --deploy-hook de
#      reload. O arquivo diz 89 dias, o mundo vê 3.)
#
# Uso:
#   ./cert_status.sh            # silencioso se está em dia; ruidoso e exit 3 se não
#   ./cert_status.sh --detalhe  # imprime sempre, mesmo em dia
#
# Exit: 0 = em dia, OU o TLS ainda não foi aplicado neste host (nada a vigiar; ver a
#           marca $MARCA_TLS abaixo) · 2 = TLS foi aplicado e o certificado sumiu
#           · 3 = vencendo, vencido ou divergente
set -euo pipefail

HOST_TLS="${JORNADA_TLS_HOST:-vps.falagaiotto.com.br}"
CERT="/etc/letsencrypt/live/$HOST_TLS/fullchain.pem"
# Marca escrita por deploy/tls_setup.sh quando o TLS é aplicado com sucesso. Ver o
# tratamento de "sem certificado" abaixo: é ela que separa "ainda não instalaram" de
# "instalaram e sumiu".
MARCA_TLS="${JORNADA_TLS_MARCA:-/var/lib/jornada/tls-instalado}"
# 21 dias: o certbot renova aos 30 restantes e tenta 2x/dia. Se aos 21 ainda não
# renovou, já falhou ~18 vezes em silêncio — é aviso de sobra para agir num dia útil.
DIAS_ALERTA="${JORNADA_CERT_ALERTA_DIAS:-21}"
DETALHE=0
[ "${1:-}" = "--detalhe" ] && DETALHE=1

erro() {
  printf 'jornada-cert ERRO: %s\n' "$*" >&2
  command -v logger >/dev/null 2>&1 && logger -t jornada-cert -p daemon.err -- "$*" || true
}

dias_ate() { # $1=data no formato do openssl → dias inteiros a partir de agora
  local fim epoch_fim
  fim="$1"
  epoch_fim="$(date -d "$fim" +%s 2>/dev/null)" || return 1
  echo $(((epoch_fim - $(date +%s)) / 86400))
}

if [ ! -r "$CERT" ]; then
  if [ ! -e "$MARCA_TLS" ]; then
    # O cron deste vigia é instalado pelo deploy.sh (roda a cada push verde), mas o TLS
    # é aplicado À MÃO, depois, com tls_setup.sh --aplicar. Entre um e outro, gritar
    # todo dia sobre um certificado que ninguém pediu ainda treina o time a ignorar o
    # canal — e é o MESMO canal (syslog/MAILTO) por onde chegam os alarmes do purge e
    # do backup. Alarme diário previsível não é vigilância, é ruído que apaga alarme de
    # verdade. Sem a marca: o TLS nunca foi aplicado aqui, silêncio.
    [ "$DETALHE" = 1 ] && echo "TLS ainda não aplicado neste host (sem $MARCA_TLS) — nada a vigiar."
    exit 0
  fi
  # Com a marca e sem certificado: o TLS existia e SUMIU. Isso é alarme.
  erro "sem certificado em $CERT, mas $MARCA_TLS registra que o TLS FOI aplicado neste
       host — /etc/letsencrypt foi removido ou o host trocou. A aplicação está sem HTTPS.
       Reaplique: bash /opt/jornada/deploy/tls_setup.sh --aplicar"
  exit 2
fi

# ---------------------------------------------------------------- 1. o ARQUIVO
fim_arquivo="$(openssl x509 -enddate -noout -in "$CERT" | cut -d= -f2)"
dias_arquivo="$(dias_ate "$fim_arquivo")" || {
  erro "não consegui interpretar a validade de $CERT"
  exit 2
}

# ------------------------------------------------------- 2. o que a :443 SERVE
# `openssl s_client` contra o próprio host: é a única forma de ver o certificado como um
# navegador o vê. Sem isto, um nginx que não recarregou passa despercebido até o dia do
# vencimento — o arquivo em disco estaria ótimo o tempo todo.
fim_servido=""
if servido="$(echo | timeout 15 openssl s_client -connect "127.0.0.1:443" \
  -servername "$HOST_TLS" 2>/dev/null | openssl x509 -enddate -noout 2>/dev/null)"; then
  fim_servido="${servido#*=}"
fi

problemas=0
if [ "$dias_arquivo" -lt 0 ]; then
  erro "certificado de $HOST_TLS VENCEU há $((-dias_arquivo)) dia(s) ($fim_arquivo).
       A aplicação está inacessível por HTTPS AGORA. Renove com:
         certbot renew --force-renewal && systemctl reload nginx"
  problemas=1
elif [ "$dias_arquivo" -le "$DIAS_ALERTA" ]; then
  erro "certificado de $HOST_TLS vence em $dias_arquivo dia(s) ($fim_arquivo) e o
       certbot.timer ainda não renovou — ele tenta 2x/dia desde os 30 dias restantes,
       logo já falhou várias vezes. Investigue:
         systemctl status certbot.timer && certbot renew --dry-run
         journalctl -u certbot -n 50"
  problemas=1
fi

if [ -z "$fim_servido" ]; then
  erro "nada respondeu TLS em 127.0.0.1:443 — o nginx está fora, ou não escuta 443"
  problemas=1
elif [ "$fim_servido" != "$fim_arquivo" ]; then
  dias_servido="$(dias_ate "$fim_servido" || echo '?')"
  erro "DIVERGÊNCIA: o arquivo vale até $fim_arquivo (${dias_arquivo}d), mas a :443 serve
       um certificado que vale até $fim_servido (${dias_servido}d). O certbot renovou e o
       nginx continua com o antigo em memória. Corrija AGORA (é barato) com:
         systemctl reload nginx
       e garanta o hook permanente:
         certbot renew --deploy-hook 'systemctl reload nginx'"
  problemas=1
fi

if [ "$problemas" -ne 0 ]; then
  exit 3
fi
if [ "$DETALHE" = 1 ]; then
  echo "cert $HOST_TLS: válido por mais $dias_arquivo dia(s) (até $fim_arquivo); a :443 serve o mesmo arquivo."
fi
exit 0
