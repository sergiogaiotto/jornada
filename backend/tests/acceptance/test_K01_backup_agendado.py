"""Aceite K01 · O §10.2 ganha o guarda-corpo que o §10.4 já tinha.

O F04 provou que documentação divergente da instalação é o modo de falha desta
classe de frente: o §10.4 esteve *documentado como implementado* enquanto nada
instalava o cron. O conserto foi o `test_F04_readme_reproduz_byte_a_byte_o_cron_que_o
_deploy_escreve` — que, olhando de perto, prende apenas `blocos[0]`: o PRIMEIRO bloco
```cron do README.

O backup (§10.2) entrou na onda 4 com script, cron, cifra e prova de restauração — e
com **zero** testes. A consequência apareceu sozinha: ao reescrever o README, o bloco
```cron do backup foi redigido com comentários inline inventados (`# prova semanal`) e
sem as linhas `SHELL`/`PATH`/`CRON_TZ`/`MAILTO`. Divergiu do arquivo que o deploy
escreve, e **nenhum teste ficou vermelho** — porque o único vigia olhava o outro bloco.

Este arquivo é a emenda na doença, não no sintoma:

**Parte 1 — paridade genérica.** Todo bloco ```cron do README tem de corresponder, byte
a byte, a um heredoc que o `deploy/deploy.sh` realmente escreve em `/etc/cron.d/`. Vale
para o purge, para o backup e para qualquer cron futuro — que nasce preso por
construção, em vez de nascer livre até alguém lembrar de escrever o teste.

**Parte 2 — o §10.2 tem o mesmo contrato de falha visível do §10.4** (exit codes,
carimbo, vigia, syslog independente do MAILTO), e o vigia do backup não pode mentir com
carimbo no futuro — o mesmo defeito que a auditoria achou no purge.

**Parte 3 — a ordem 02:20 < 03:15 é invariante, não coincidência.** O backup do dia tem
de registrar o estado ANTERIOR à destruição por retenção; invertida, uma política de
`retencao_dias` publicada errada vira perda irreversível em 24h.
"""

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[3]
DEPLOY_SH = RAIZ / "deploy" / "deploy.sh"
BACKUP_SH = RAIZ / "scripts" / "backup_bancos.sh"
RESTAURA_SH = RAIZ / "scripts" / "restaura_teste.sh"
README = RAIZ / "README.md"


def _resolver_defaults(texto: str, deploy: str) -> str:
    """Resolve as expansões de shell do heredoc para o que a VPS recebe de fato."""
    fuso = re.search(r'FUSO_CRON="\$\{JORNADA_CRON_TZ:-([^}]+)\}"', deploy)
    assert fuso, "FUSO_CRON sumiu: cron sem CRON_TZ roda no fuso implícito do host"
    texto = texto.replace("$FUSO_CRON", fuso.group(1))
    return re.sub(r"\$\{[A-Z_]+:-([^}]*)\}", r"\1", texto)


def _crons_que_o_deploy_instala() -> dict[str, str]:
    """Todos os `/etc/cron.d/*` escritos por `deploy.sh`, indexados pelo nome do arquivo.

    Genérico de propósito: o F04 extraía UM heredoc pelo nome da variável, então um cron
    novo (o do backup) entrou sem vigia nenhum. Aqui, qualquer `cat >"$VAR" <<CRON` cujo
    `VAR` aponte para `/etc/cron.d/` é descoberto sozinho.
    """
    deploy = DEPLOY_SH.read_text(encoding="utf-8")
    variaveis = dict(re.findall(r"^([A-Z_]+)=(/etc/cron\.d/[\w.-]+)\s*$", deploy, re.M))
    assert variaveis, (
        "deploy.sh não escreve mais nenhum /etc/cron.d/* — o agendamento voltou a ser papel"
    )

    instalados: dict[str, str] = {}
    for variavel, caminho in variaveis.items():
        corpo = re.search(rf'cat >"\${variavel}" <<CRON\n(.*?)\nCRON\n', deploy, re.S)
        assert corpo, f"{variavel} aponta para {caminho} mas nenhum heredoc o escreve"
        instalados[Path(caminho).name] = _resolver_defaults(corpo.group(1), deploy).strip()
    return instalados


def _blocos_cron_do_readme() -> list[str]:
    blocos = re.findall(r"```cron\n(.*?)```", README.read_text(encoding="utf-8"), re.S)
    return [b.strip() for b in blocos]


# ----------------------------------------------------- Parte 1 · paridade genérica
def test_K01_o_deploy_instala_o_cron_do_backup_em_vez_de_documenta_lo() -> None:
    """O achado do F04, aplicado ao §10.2: alguém precisa ESCREVER o arquivo."""
    instalados = _crons_que_o_deploy_instala()
    assert "jornada-backup" in instalados, "o deploy não instala mais o cron do backup"

    deploy = DEPLOY_SH.read_text(encoding="utf-8")
    assert "backup_bancos.sh" in instalados["jornada-backup"]
    assert "restaura_teste.sh" in instalados["jornada-backup"], (
        "backup sem teste de restauração agendado é backup não provado (§10.2)"
    )
    # a cifra nasce no deploy, nunca no repositório
    assert "garantir_env JORNADA_BACKUP_PASSPHRASE" in deploy
    assert "chmod +x scripts/backup_bancos.sh scripts/restaura_teste.sh" in deploy
    # /etc/cron.d sem daemon de cron é inerte — o deploy confere (mesma trava do F04)
    assert "verificar_cron_ativo" in deploy


def test_K01_todo_bloco_cron_do_readme_corresponde_a_um_cron_instalado() -> None:
    """A emenda vai na doença: o vigia do F04 só olhava `blocos[0]`.

    Este teste é o motivo de existir do K01. Enquanto ele existir, um bloco ```cron novo
    no README que ninguém instala — ou que diverge do instalado numa vírgula — fica
    vermelho. Inversão verificada: mudar um horário no README (ou no deploy.sh) sem
    mudar o outro reprova aqui.
    """
    instalados = _crons_que_o_deploy_instala()
    documentados = _blocos_cron_do_readme()
    assert documentados, "o README perdeu os blocos ```cron do agendamento"

    # todo bloco documentado tem de ser, byte a byte, um arquivo que o deploy escreve
    for bloco in documentados:
        alvo = re.search(r"/etc/cron\.d/([\w.-]+)", bloco)
        assert alvo, f"bloco ```cron sem dizer QUAL arquivo ele descreve:\n{bloco[:200]}"
        nome = alvo.group(1)
        assert nome in instalados, (
            f"o README descreve {nome}, que o deploy.sh não instala em lugar nenhum"
        )
        assert bloco == instalados[nome], (
            f"o README descreve um {nome} diferente do que o deploy instala:\n"
            f"--- README ---\n{bloco}\n--- DEPLOY ---\n{instalados[nome]}"
        )

    # e o inverso: nenhum cron instalado pode ficar sem documentação
    nomes_documentados = {re.search(r"/etc/cron\.d/([\w.-]+)", b).group(1) for b in documentados}  # type: ignore[union-attr]
    faltando = sorted(set(instalados) - nomes_documentados)
    assert not faltando, (
        f"o deploy instala {faltando} que o README não descreve — "
        "agendamento invisível é o que o operador não sabe que existe"
    )


def test_K01_o_backup_roda_antes_do_purge() -> None:
    """Ordem é invariante do §10.2, não coincidência de horário.

    O backup das 02:20 registra o estado ANTERIOR ao purge das 03:15. Invertido, a cópia
    do dia já nasceria sem o que a retenção destruiu, e um `retencao_dias` publicado
    errado viraria perda irreversível em 24h — exatamente o cenário que ter backup
    deveria cobrir.
    """
    instalados = _crons_que_o_deploy_instala()

    def minutos(cron: str, script: str) -> int:
        linha = next(
            (
                candidata
                for candidata in cron.splitlines()
                if re.match(r"^\d", candidata)
                and script in candidata
                and "--status" not in candidata
            ),
            None,
        )
        assert linha, f"não achei a linha de execução de {script} em:\n{cron}"
        m, h = linha.split()[0], linha.split()[1]
        return int(h) * 60 + int(m)

    assert minutos(instalados["jornada-backup"], "backup_bancos.sh") < minutos(
        instalados["jornada-purge"], "purge_retencao.sh"
    ), "o purge passou a rodar ANTES do backup — a cópia do dia perde o que foi destruído"


def test_K01_falha_do_backup_nao_e_silenciosa() -> None:
    """Mesmo contrato do §10.4: nem stderr no arquivo, nem log via `>>` na linha do cron."""
    instalado = _crons_que_o_deploy_instala()["jornada-backup"]
    linhas = [candidata for candidata in instalado.splitlines() if re.match(r"^\d", candidata)]
    assert linhas, "o cron de backup instalado não tem nenhuma linha de job"
    for linha in linhas:
        assert "2>&1" not in linha, "stderr no arquivo = falha silenciosa (o bug do F04)"
        assert ">>" not in linha, "o log é responsabilidade do script (com carimbo de tempo)"
    assert re.search(r"^MAILTO=", instalado, re.M), "sem MAILTO o cron não notifica ninguém"

    for script, etiqueta in ((BACKUP_SH, "jornada-backup"), (RESTAURA_SH, "jornada-restore-teste")):
        texto = script.read_text(encoding="utf-8")
        assert f"logger -t {etiqueta}" in texto, (
            f"{script.name}: sem syslog, a falha depende de um MTA que a VPS não tem"
        )
        assert ">&2" in texto, f"{script.name} tem de falar por stderr quando falha"


# ------------------------------------------------- Parte 2 · contrato dos executores
@pytest.mark.parametrize("script", [BACKUP_SH, RESTAURA_SH], ids=lambda p: p.name)
def test_K01_executores_existem_e_seguem_o_contrato(script: Path) -> None:
    """Existência, shebang, aborto em erro e os exit codes do §10.2.

    O bit de execução não é conferido aqui pelo mesmo motivo do F04: o gate roda com o
    repositório em bind mount e todo arquivo aparece executável, o que tornaria a
    asserção sempre verde. Quem garante na VPS é o `chmod +x` do deploy, prendido acima.
    """
    assert script.exists(), f"{script.name} não existe — o cron chamaria o vazio"
    texto = script.read_text(encoding="utf-8")
    assert texto.startswith("#!/usr/bin/env bash\n")
    assert "set -euo pipefail" in texto, "script de backup não pode seguir após erro"
    assert "--status" in texto, "sem --status ninguém sabe que o backup parou"
    # 0 ok · 1 execução falhou · 2 configuração ausente · 3 atrasado
    for codigo in ("exit 1", "exit 2", "exit 3"):
        assert codigo in texto, f"{script.name} não implementa {codigo} do contrato §10.2"


def test_K01_o_backup_e_pg_dump_e_a_prova_usa_imagem_com_pgvector() -> None:
    """Os dois detalhes que só aparecem quando se testa a restauração de verdade.

    1. `pg_dump -Fc` para arquivo temporário, não `pg_dump | openssl > arq`: num pipeline
       o `$?` é o do último comando, então um dump que morre no meio produz arquivo
       cifrado truncado com exit 0 — backup que só falha no dia do desastre.
    2. A imagem descartável precisa ter a extensão `vector` (§7.4); `postgres:16` puro
       falha no `CREATE EXTENSION` e leva junto tudo que vem depois.
    """
    backup = BACKUP_SH.read_text(encoding="utf-8")
    assert "pg_dump" in backup and "-Fc" in backup
    # Só o CÓDIGO conta: o cabeçalho do script explica justamente por que não usa o
    # pipeline, e uma busca ingênua no texto inteiro casaria com a explicação. É a mesma
    # regra do F04 ("citar a variável fantasma ao contar a história é permitido, usá-la
    # não é") — um teste que confunde comentário com implementação reprova o certo.
    codigo = "\n".join(linha for linha in backup.splitlines() if not linha.lstrip().startswith("#"))
    assert not re.search(r"pg_dump[^\n|]*\|\s*openssl", codigo), (
        "pipeline esconde a falha do pg_dump no $?: dump truncado vira .enc com exit 0"
    )

    restaura = RESTAURA_SH.read_text(encoding="utf-8")
    assert "pgvector/pgvector" in restaura, "imagem sem a extensão vector reprova o §7.4"
    assert "--exit-on-error" in restaura, "sem isto o pg_restore engole erro e sai 0"
    assert "--network none" in restaura, "container de prova não pode alcançar a rede"
    assert "alembic_version" in restaura, "schema restaurado sem marca de migração não serve"


def test_K01_a_passphrase_nao_vai_em_argv_nem_para_o_repositorio() -> None:
    """`ps aux` é público nesta VPS, que tem outros inquilinos.

    A passphrase entra no `openssl` por file descriptor. E nenhum valor literal pode
    existir no repositório — só o NOME da variável (mesma regra do §10.3/F04).
    """
    backup = BACKUP_SH.read_text(encoding="utf-8")
    assert re.search(r"-pass\s+(fd|file):", backup), (
        "passphrase em argv fica visível em `ps` para qualquer processo do host"
    )
    # `-pass pass:...` é a forma que VAZA: o valor vira argumento do processo.
    assert not re.search(r"-pass\s+pass:", backup), "passphrase expandida em argv"

    for arquivo in (README, DEPLOY_SH, BACKUP_SH, RESTAURA_SH):
        conteudo = arquivo.read_text(encoding="utf-8")
        for valor in re.findall(r"JORNADA_BACKUP_PASSPHRASE=([^\s\"']+)", conteudo):
            assert not re.fullmatch(r"[0-9a-f]{32,}", valor), (
                f"{arquivo.name} tem uma passphrase literal — segredo no repositório"
            )


# ------------------------------------------------------- Parte 3 · o vigia não mente
@pytest.mark.skipif(shutil.which("bash") is None, reason="precisa de bash (gate roda no container)")
def test_K01_o_vigia_do_backup_nao_atesta_saude_com_carimbo_no_futuro() -> None:
    """O mesmo defeito que a auditoria achou no purge, conferido no backup.

    `idade = agora - carimbo`: com data no FUTURO a idade sai NEGATIVA e passa por
    `-gt 26` para sempre — o `--status` das 09:40 declararia "backup em dia" com o cron
    morto. VPS sem NTP, restauração de snapshot e edição manual produzem exatamente isso.
    """
    with tempfile.TemporaryDirectory() as tmp:
        carimbo = Path(tmp, "backup-ultimo.json")
        ambiente = {
            **os.environ,
            "JORNADA_BACKUP_STAMP": str(carimbo),
            "JORNADA_BACKUP_LOG": str(Path(tmp, "backup.log")),
            "JORNADA_BACKUP_DIR": str(Path(tmp, "backups")),
            "JORNADA_ENV_FILE": str(Path(tmp, "sem-env")),
        }

        def status() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                ["bash", str(BACKUP_SH), "--status"], env=ambiente, capture_output=True, text=True
            )

        # 1. sem carimbo nenhum: "nunca rodou"
        assert status().returncode == 3, "backup que nunca rodou não pode passar por saudável"

        # 2. carimbo no futuro: NÃO pode ser lido como saúde
        carimbo.parent.mkdir(parents=True, exist_ok=True)
        carimbo.write_text(
            '{"ts":"2099-01-01T00:00:00Z","modo":"backup","resultado":"ok","detalhe":"x"}\n',
            encoding="utf-8",
        )
        futuro = status()
        assert futuro.returncode == 3, "carimbo no futuro silenciou o vigia — ele pode mentir"
        assert "FUTURO" in futuro.stderr, futuro.stderr
