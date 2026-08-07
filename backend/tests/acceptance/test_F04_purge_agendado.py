"""Aceite F04 · O cron do §10.4 sai do comentário e passa a existir.

A auditoria de pré-PII achou o §10.4 num estado pior que "não implementado": estava
**documentado como implementado**. `docker-compose.prod.yml` e o README exibiam uma
linha de cron que ninguém instalava (`grep -c cron` = 0 em `backend/Dockerfile`,
`frontend/Dockerfile`, `.github/workflows/ci.yml` e `deploy/deploy.sh`), apontando para
`127.0.0.1:8000` — porta que o serviço `api` **não publica** —, usando um
`JORNADA_DPO_TOKEN` inexistente no repositório e que `/etc/cron.d/*` não herdaria do
host de qualquer jeito, e enterrando o stderr no arquivo de log com `2>&1`.

Este arquivo é o guarda-corpo dos dois lados do conserto:

**Parte 1 — a porta de MÁQUINA** (`backend/api/v1/admin.py::ator_do_purge`). Em
`APP_ENV=prod` não existe Bearer nenhum (`config.py::_prod_proibe_tokens_dev`) e a
sessão é cookie de pessoa: sem uma credencial de máquina o cron não teria como
autenticar justamente no ambiente onde o purge precisa rodar. O que estes testes
prendem é o *fail-closed*: sem a variável de ambiente, com ela vazia ou com token curto,
a porta continua FECHADA e a rota é exatamente o que era antes (só `dpo`/`admin`).

**Parte 2 — a instalação**. Testar "o cron roda às 03:15" exigiria a VPS. O que dá para
provar aqui, e é onde estava o bug, é que o caminho de deploy INSTALA o agendamento, que
o executor existe, e que o README descreve o arquivo que o deploy realmente escreve —
byte a byte. Documentação que diverge da instalação é como esta frente começou.
"""

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.v1.admin import ATOR_SERVICO, VAR_TOKEN_SERVICO

RAIZ = Path(__file__).resolve().parents[3]
DEPLOY_SH = RAIZ / "deploy" / "deploy.sh"
PURGE_SH = RAIZ / "scripts" / "purge_retencao.sh"
COMPOSE = RAIZ / "docker-compose.prod.yml"
README = RAIZ / "README.md"

TENANT = "torre-movel"
TOKEN_MAQUINA = "f4" * 32  # 64 chars, como o `openssl rand -hex 32` do deploy


def _h(token: str) -> dict[str, str]:
    return {"X-Tenant": TENANT, "Authorization": f"Bearer {token}"}


@pytest.fixture()
def com_token_de_maquina(monkeypatch: pytest.MonkeyPatch) -> str:
    """Simula o `.env` do servidor com o token gerado pelo deploy."""
    monkeypatch.setenv(VAR_TOKEN_SERVICO, TOKEN_MAQUINA)
    return TOKEN_MAQUINA


def _eventos_purge(app: FastAPI) -> list[Any]:
    return [e for e in app.state.repositorio_os.listar_eventos() if e.type == "dados.purgados"]


# ------------------------------------------------------------ Parte 1 · credencial
def test_F04_token_de_maquina_autentica_o_purge_e_se_identifica_na_auditoria(
    client: TestClient, app: FastAPI, com_token_de_maquina: str
) -> None:
    """O cron purga sem usuário — e a trilha registra QUE FOI O CRON.

    O `actor` do `dados.purgados` (§2.3) não pode ser o e-mail de um humano que não
    apertou botão nenhum: numa auditoria de LGPD, "quem mandou destruir" é a primeira
    pergunta. `maquina:purge-cron` é uma resposta verdadeira.
    """
    resposta = client.post("/api/v1/admin/purge?aplicar=true", headers=_h(com_token_de_maquina))
    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["aplicado"] is True

    # base vazia (fixture `app` nasce sem seeds): nada expirou, nada foi destruído, e
    # por isso NÃO há evento — o outbox só registra destruição real (§10.4).
    assert resposta.json()["total"] == 0
    assert _eventos_purge(app) == []


def test_F04_token_de_maquina_carimba_o_ator_quando_destroi(
    client: TestClient, app: FastAPI, com_token_de_maquina: str
) -> None:
    """Com dado expirado de verdade, o evento sai com o ator da máquina."""
    from datetime import UTC, datetime, timedelta

    from domain.lancamento.modelos import TelemetryEvent

    app.state.repositorio_os.adicionar_telemetria(
        TelemetryEvent(
            tenant_id=TENANT,
            tipo="sent",
            ts=datetime.now(UTC) - timedelta(days=400),  # além dos 180 do seed §11.4
            canal="email",
            contato_hash="a" * 64,
            fonte="ens",
        )
    )
    aplicado = client.post("/api/v1/admin/purge?aplicar=true", headers=_h(com_token_de_maquina))
    assert aplicado.status_code == 200, aplicado.text
    assert aplicado.json()["removidos"]["telemetry_event"] == 1

    eventos = _eventos_purge(app)
    assert len(eventos) == 1
    assert eventos[0].actor == ATOR_SERVICO == "maquina:purge-cron"
    assert "@" not in eventos[0].actor, "ator de máquina não pode se passar por pessoa"


def test_F04_sem_a_variavel_de_ambiente_a_porta_de_maquina_esta_fechada(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Estado PADRÃO do processo (inclusive todo dev e todo teste): variável ausente.

    Este é o teste que impede a porta de máquina de virar um `dev-admin` novo: o mesmo
    token que funciona com a variável setada tem de bater em 401 sem ela. Se este teste
    ficar vermelho, existe uma senha no repositório de novo.
    """
    monkeypatch.delenv(VAR_TOKEN_SERVICO, raising=False)
    assert client.post("/api/v1/admin/purge", headers=_h(TOKEN_MAQUINA)).status_code == 401


def test_F04_token_curto_ou_vazio_nao_abre_a_porta(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail-closed no piso de 32 caracteres — sem "aceita com aviso no log".

    Um token de 8 caracteres é adivinhável e um aviso em log é o modo de falha
    silenciosa que esta frente veio consertar. Abaixo do piso, a rota trata como
    ausente: 401 na cara do operador, que é onde a falha tem de aparecer.
    """
    for fraco in ("", "   ", "curto", "abc123", "x" * 31):
        monkeypatch.setenv(VAR_TOKEN_SERVICO, fraco)
        resposta = client.post("/api/v1/admin/purge", headers=_h(fraco or "vazio"))
        assert resposta.status_code == 401, f"token {fraco!r} não podia autenticar"


def test_F04_token_errado_nao_passa_e_o_caminho_humano_fica_intacto(
    client: TestClient, com_token_de_maquina: str
) -> None:
    """Abrir a porta da máquina não pode afrouxar o RBAC das pessoas (§8-M0)."""
    assert client.post("/api/v1/admin/purge", headers=_h("f4" * 31 + "00")).status_code == 401
    # analista continua sem poder destruir dado; dpo continua podendo
    assert client.post("/api/v1/admin/purge", headers=_h("dev-analista")).status_code == 403
    assert client.post("/api/v1/admin/purge", headers=_h("portal-dev")).status_code == 401
    assert client.post("/api/v1/admin/purge", headers=_h("dev-dpo")).status_code == 200


def test_F04_dry_run_continua_sendo_o_default_para_a_maquina(
    client: TestClient, app: FastAPI, com_token_de_maquina: str
) -> None:
    """O default seguro vale para o cron também: sem `?aplicar=true`, nada é apagado.

    Importa porque o executor (`scripts/purge_retencao.sh`) roda em dry-run quando
    chamado sem argumento — é o que o deploy usa como smoke. Um dry-run que apagasse
    transformaria o smoke pós-deploy em destruição de dado de cliente.
    """
    from datetime import UTC, datetime, timedelta

    from domain.lancamento.modelos import TelemetryEvent

    app.state.repositorio_os.adicionar_telemetria(
        TelemetryEvent(
            tenant_id=TENANT,
            tipo="sent",
            ts=datetime.now(UTC) - timedelta(days=400),
            fonte="ens",
        )
    )
    seco = client.post("/api/v1/admin/purge", headers=_h(com_token_de_maquina))
    assert seco.status_code == 200, seco.text
    assert seco.json()["aplicado"] is False
    assert seco.json()["removidos"]["telemetry_event"] == 1  # relatou
    assert len(app.state.repositorio_os._telemetria) == 1  # noqa: SLF001 — e não apagou


# ------------------------------------------------------------ Parte 2 · instalação
def _cron_que_o_deploy_instala() -> str:
    """Conteúdo do `/etc/cron.d/jornada-purge` escrito por `deploy/deploy.sh`.

    Extrai o heredoc e resolve as expansões de shell com seus defaults, de modo que a
    comparação com o README seja sobre o arquivo que a VPS realmente recebe.
    """
    texto = DEPLOY_SH.read_text(encoding="utf-8")
    corpo = re.search(r'cat >"\$CRON_FILE" <<CRON\n(.*?)\nCRON\n', texto, re.S)
    assert corpo, "deploy.sh não escreve mais o heredoc do cron — o §10.4 voltou a ser papel"
    conteudo = corpo.group(1)
    fuso = re.search(r'FUSO_CRON="\$\{JORNADA_CRON_TZ:-([^}]+)\}"', texto)
    assert fuso, "FUSO_CRON sumiu: cron sem CRON_TZ roda no fuso implícito do host"
    conteudo = conteudo.replace("$FUSO_CRON", fuso.group(1))
    # demais `${VAR:-default}` do heredoc resolvem para o default
    return re.sub(r"\$\{[A-Z_]+:-([^}]*)\}", r"\1", conteudo)


def test_F04_o_deploy_instala_o_cron_em_vez_de_documenta_lo() -> None:
    """O achado central da frente: nada instalava a linha de cron.

    Inversão verificada (ver relatório): removendo o bloco `cat >"$CRON_FILE"` do
    deploy.sh este teste fica vermelho — que é exatamente o estado em que o repositório
    estava antes do F04, com o README dizendo o contrário.
    """
    deploy = DEPLOY_SH.read_text(encoding="utf-8")
    assert "/etc/cron.d/jornada-purge" in deploy
    assert "purge_retencao.sh --aplicar" in deploy, "o cron não chama o executor do purge"
    assert "purge_retencao.sh --status" in deploy, "sem o vigia, ninguém sabe se parou"
    # a credencial de máquina nasce no deploy, não no repositório
    assert f"garantir_env {VAR_TOKEN_SERVICO}" in deploy
    assert "openssl rand -hex 32" in deploy
    # e o deploy confere se existe daemon de cron: /etc/cron.d sem cron é inerte
    assert "verificar_cron_ativo" in deploy


def test_F04_readme_reproduz_byte_a_byte_o_cron_que_o_deploy_escreve() -> None:
    """README e instalação não podem divergir — foi a divergência que criou o achado.

    O bloco ```cron do README tem de ser o mesmo arquivo que `deploy.sh` escreve em
    `/etc/cron.d/jornada-purge`, com os defaults resolvidos. Mudar o horário no deploy e
    esquecer o README (ou o inverso) deixa este teste vermelho.
    """
    readme = README.read_text(encoding="utf-8")
    blocos = re.findall(r"```cron\n(.*?)```", readme, re.S)
    assert blocos, "o README perdeu o bloco ```cron do §10.4"
    documentado = blocos[0].strip()
    instalado = _cron_que_o_deploy_instala().strip()
    assert documentado == instalado, (
        "o README descreve um cron diferente do que o deploy instala:\n"
        f"--- README ---\n{documentado}\n--- DEPLOY ---\n{instalado}"
    )


def test_F04_executor_existe_e_e_chamavel() -> None:
    """O script tem de existir, ter shebang, abortar em erro e ser executável na VPS.

    O bit de execução não é conferido pelo `os.access` de propósito: o gate roda com o
    repositório em bind mount (todo arquivo aparece como executável no container, o que
    tornaria a asserção sempre verde e, portanto, inútil). A garantia que vale na VPS é
    o `chmod +x` do deploy, e é ele que este teste prende.
    """
    assert PURGE_SH.exists(), "o executor do cron não existe — o cron chamaria o vazio"
    texto = PURGE_SH.read_text(encoding="utf-8")
    assert texto.startswith("#!/usr/bin/env bash\n")
    assert "set -euo pipefail" in texto, "script de destruição de dado não pode seguir após erro"
    assert "chmod +x scripts/purge_retencao.sh" in DEPLOY_SH.read_text(encoding="utf-8")
    # os três modos do contrato, com dry-run no default
    assert "MODO=dry-run" in texto
    assert "--aplicar" in texto and "--status" in texto


def test_F04_host_porta_e_credencial_do_executor_estao_certos() -> None:
    """Os três defeitos da linha antiga, um por asserção.

    1. porta: `api` não publica nada; quem publica é `web` (8050) e o nginx faz proxy
       de `/api/`. `127.0.0.1:8000` do host era connection refused garantido.
    2. credencial: `JORNADA_DPO_TOKEN` não existia em lugar nenhum do repositório.
    3. o token vai para o curl por stdin (`-K -`), não em argv — `ps aux` não o mostra.
    """
    script = PURGE_SH.read_text(encoding="utf-8")
    assert "http://127.0.0.1:8050/api/v1" in script
    assert VAR_TOKEN_SERVICO in script
    assert "-K -" in script, "o token estaria visível em `ps` para qualquer processo do host"

    for arquivo in (README, COMPOSE, DEPLOY_SH, PURGE_SH):
        conteudo = arquivo.read_text(encoding="utf-8")
        # citar a variável fantasma ao contar a história é permitido; USÁ-LA não é —
        # por isso a busca é pela expansão (`$JORNADA_DPO_TOKEN`) e pela atribuição.
        assert "$JORNADA_DPO_TOKEN" not in conteudo, (
            f"{arquivo.name} ressuscitou a variável fantasma"
        )
        assert "JORNADA_DPO_TOKEN=" not in conteudo, (
            f"{arquivo.name} ressuscitou a variável fantasma"
        )
        assert "127.0.0.1:8000/api" not in conteudo, (
            f"{arquivo.name} aponta para porta não publicada"
        )


def test_F04_o_token_de_maquina_chega_ao_container_da_api() -> None:
    """De nada adianta o deploy gerar o token no `.env` se o compose não o injeta.

    Sem esta linha o cron autenticaria contra um processo que não conhece o token: 401
    todo dia às 03:15, e o purge nunca aconteceria — com todos os arquivos no lugar.
    """
    compose = COMPOSE.read_text(encoding="utf-8")
    assert f"{VAR_TOKEN_SERVICO}: ${{{VAR_TOKEN_SERVICO}:-}}" in compose
    # e o compose não pode voltar a fingir que hospeda o agendamento
    assert "15 3 * * *" not in compose, "linha de cron em comentário de compose não instala nada"


def test_F04_falha_do_cron_nao_e_silenciosa() -> None:
    """O terceiro defeito: `>> log 2>&1` mandava o erro para o arquivo e ninguém sabia.

    Agora: a linha do cron não redireciona nada (quem escreve o log é o script, com
    carimbo de tempo), o `MAILTO` entrega o stderr a alguém, e o script separa os dois
    canais — log para o normal, stderr + exit != 0 para a falha.
    """
    instalado = _cron_que_o_deploy_instala()
    linhas_de_job = [linha for linha in instalado.splitlines() if re.match(r"^\d", linha)]
    assert linhas_de_job, "o cron instalado não tem nenhuma linha de job"
    for linha in linhas_de_job:
        assert "2>&1" not in linha, "stderr no arquivo = falha silenciosa (o bug original)"
        assert ">>" not in linha, "o log é responsabilidade do script (com carimbo de tempo)"
    assert re.search(r"^MAILTO=", instalado, re.M), "sem MAILTO o cron não notifica ninguém"

    script = PURGE_SH.read_text(encoding="utf-8")
    assert ">&2" in script, "o script tem de falar por stderr quando falha"
    assert "exit 1" in script and "exit 2" in script and "exit 3" in script
    assert "date -u +%Y-%m-%dT%H:%M:%SZ" in script, "log sem carimbo de tempo não prova quando"


def test_F04_existe_como_saber_que_o_purge_nao_rodou() -> None:
    """Um script não relata a própria ausência — quem relata é o carimbo + o vigia.

    E o carimbo só é escrito por `--aplicar`: se o dry-run carimbasse, o dry-run manual
    de um operador (ou o smoke do deploy) faria o `--status` do dia seguinte declarar
    saúde com o cron morto.
    """
    script = PURGE_SH.read_text(encoding="utf-8")
    assert "purge-ultimo.json" in script
    assert "JORNADA_PURGE_MAX_H:-26" in script, "sem limite de idade, 'atrasado' não existe"
    assert '[ "$MODO" = aplicar ] || return 0' in script, "dry-run não pode carimbar execução"
    assert "NUNCA rodou" in script, "o caso 'nunca rodou' precisa de mensagem própria"
    assert "exit 3" in script


def test_F04_o_repositorio_nao_carrega_segredo_do_purge() -> None:
    """Nenhum valor de token no repositório — só o NOME da variável (§10.3)."""
    for arquivo in (README, COMPOSE, DEPLOY_SH, PURGE_SH):
        conteudo = arquivo.read_text(encoding="utf-8")
        atribuicoes = re.findall(rf"{VAR_TOKEN_SERVICO}=([^\s\"']+)", conteudo)
        for valor in atribuicoes:
            assert not re.fullmatch(r"[0-9a-f]{32,}", valor), (
                f"{arquivo.name} tem um token literal — segredo no repositório"
            )


def test_F04_variavel_de_ambiente_nao_vaza_para_os_outros_testes() -> None:
    """Higiene: nenhum teste desta suíte pode deixar a porta de máquina aberta."""
    assert os.environ.get(VAR_TOKEN_SERVICO) is None


# ------------------------------------------------- Parte 3 · o que a auditoria achou
# Os três testes abaixo nasceram da revisão cética desta frente. Cada um reproduz um
# defeito que a primeira versão do F04 TINHA — e que a suíte original não pegava porque
# só olhava o texto dos arquivos, nunca o comportamento deles.
def test_F04_bearer_nao_ascii_devolve_401_e_nao_500(
    client: TestClient, com_token_de_maquina: str
) -> None:
    """`Authorization: Bearer café` não pode derrubar a rota que destrói dado.

    `secrets.compare_digest` com `str` EXIGE ASCII e levanta `TypeError` fora dele; o
    header chega decodificado em latin-1, então bastava um acento para virar 500. Duas
    consequências: uma exceção não tratada, sem autenticação nenhuma, numa rota
    destrutiva; e um oráculo — 500 (token configurado) contra 401 (não configurado) —
    que diz ao atacante se vale a pena insistir neste host. A comparação agora é em
    bytes, que nunca levanta.
    """
    for hostil in ("café-da-manhã", "ç" * 64, "señor", "ação"):
        resposta = client.post(
            "/api/v1/admin/purge",
            headers={
                b"X-Tenant": TENANT.encode(),
                b"Authorization": f"Bearer {hostil}".encode("latin-1"),
            },
        )
        assert resposta.status_code == 401, (
            f"Bearer {hostil!r} devolveu {resposta.status_code}: {resposta.text[:160]}"
        )


@pytest.mark.skipif(shutil.which("bash") is None, reason="precisa de bash (gate roda no container)")
def test_F04_deploy_nao_cola_a_chave_nova_num_env_sem_newline_final() -> None:
    """`.env` sem newline no fim + `>>` = duas variáveis coladas numa linha só.

    O `.env` da VPS é editado à mão (é assim que `JORNADA_ROOT_EMAIL`/`SENHA` entram) e
    editor que não deixa newline final é regra, não exceção. Sem a correção o arquivo
    virava `APP_SECRET=abcJORNADA_PURGE_TOKEN=0b69…`: o APP_SECRET muda sozinho (toda
    sessão viva morre no `up` seguinte), o token fica ILEGÍVEL para o `sed` do executor
    (cron saindo 2 toda madrugada) e, como o `grep` continua não achando a chave, CADA
    deploy acrescenta mais uma linha. Este teste executa a função de verdade.
    """
    funcao = re.search(
        r"^garantir_env\(\).*?\n\}", DEPLOY_SH.read_text(encoding="utf-8"), re.S | re.M
    )
    assert funcao, "garantir_env sumiu do deploy.sh"
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, ".env").write_bytes(b"APP_SECRET=abc")  # sem \n final, de propósito
        roteiro = (
            f"{funcao.group(0)}\ngarantir_env {VAR_TOKEN_SERVICO} $(printf 'f%.0s' $(seq 64))\n"
        )
        Path(tmp, "roda.sh").write_text(roteiro, encoding="utf-8")
        subprocess.run(["bash", "roda.sh"], cwd=tmp, check=True, capture_output=True)
        linhas = Path(tmp, ".env").read_text(encoding="utf-8").splitlines()

    assert "APP_SECRET=abc" in linhas, f"o APP_SECRET foi corrompido: {linhas}"
    assert any(linha.startswith(f"{VAR_TOKEN_SERVICO}=") for linha in linhas), (
        f"o token não ficou legível numa linha própria: {linhas}"
    )


@pytest.mark.skipif(shutil.which("bash") is None, reason="precisa de bash (gate roda no container)")
def test_F04_o_vigia_nao_atesta_saude_com_carimbo_no_futuro() -> None:
    """Um vigia que pode mentir não é vigia.

    `idade = agora - carimbo`: com data no FUTURO a idade sai NEGATIVA e passa por
    `-gt 26` para sempre — o `--status` das 09:30 declararia "purge em dia" eternamente,
    com o cron morto. E não é hipótese exótica: VPS que sobe sem NTP, restauração de
    snapshot e edição manual do arquivo produzem exatamente isso. Agora idade negativa
    é tratada como "não rodou" (exit 3).
    """
    with tempfile.TemporaryDirectory() as tmp:
        carimbo = Path(tmp, "purge-ultimo.json")
        ambiente = {
            **os.environ,
            "JORNADA_PURGE_STAMP": str(carimbo),
            "JORNADA_PURGE_LOG": str(Path(tmp, "purge.log")),
            "JORNADA_ENV_FILE": str(Path(tmp, "sem-env")),
        }

        def status() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                ["bash", str(PURGE_SH), "--status"], env=ambiente, capture_output=True, text=True
            )

        # 1. sem carimbo nenhum: "nunca rodou"
        assert status().returncode == 3

        # 2. carimbo no futuro: NÃO pode ser lido como saúde
        carimbo.write_text(
            '{"ts":"2099-01-01T00:00:00Z","modo":"aplicar","resultado":"ok","detalhe":"x"}\n',
            encoding="utf-8",
        )
        futuro = status()
        assert futuro.returncode == 3, "carimbo no futuro silenciou o vigia — ele pode mentir"
        assert "FUTURO" in futuro.stderr, futuro.stderr

        # 3. carimbo honesto e recente: silêncio e exit 0 (o vigia não pode virar ruído)
        recente = subprocess.run(
            ["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"], capture_output=True, text=True, check=True
        ).stdout.strip()
        carimbo.write_text(
            f'{{"ts":"{recente}","modo":"aplicar","resultado":"ok","detalhe":"x"}}\n',
            encoding="utf-8",
        )
        assert status().returncode == 0


def test_F04_falha_nao_depende_de_um_MTA_que_a_VPS_nao_tem() -> None:
    """O `MAILTO` do cron só entrega se houver MTA — e numa VPS enxuta não há.

    Sem isto os "três caminhos independentes" colapsam em um: exit code que ninguém lê,
    stderr entregue a um `MAILTO` que o cron descarta ("No MTA installed, discarding
    output") e um vigia que reporta pelo MESMO canal entupido. O syslog é o caminho que
    não depende de configuração de e-mail, e o deploy avisa quando o MTA falta.
    """
    script = PURGE_SH.read_text(encoding="utf-8")
    assert "logger -t jornada-purge" in script, "falha do purge sem canal independente do MAILTO"
    deploy = DEPLOY_SH.read_text(encoding="utf-8")
    assert "verificar_canal_de_alerta" in deploy
    assert "journalctl -t jornada-purge" in deploy
    assert "journalctl -t jornada-purge" in README.read_text(encoding="utf-8"), (
        "o operador precisa saber ONDE olhar — o README é onde ele procura"
    )


def test_F04_o_smoke_que_reprova_o_deploy_espera_a_api_subir() -> None:
    """Controle que reprova o deploy por corrida acaba comentado — e protege zero.

    O smoke do §10.4 falha o deploy inteiro (exit 1). Se ele rodar 3 segundos depois de
    um `up --build`, bate em connection refused enquanto a api ainda migra: na terceira
    vez que isso acontecer, alguém comenta a checagem. Espera-se de verdade, e pela
    MESMA cadeia do cron (`:8050/healthz` → nginx → api) — sondar a raiz `/` passaria
    com a api morta.
    """
    deploy = DEPLOY_SH.read_text(encoding="utf-8")
    assert "esperar_api" in deploy
    assert "http://127.0.0.1:8050/healthz" in deploy
    posicao_espera = deploy.index("esperar_api ||")
    posicao_smoke = deploy.index("if ! scripts/purge_retencao.sh")
    assert posicao_espera < posicao_smoke, "esperar depois do smoke não espera nada"
