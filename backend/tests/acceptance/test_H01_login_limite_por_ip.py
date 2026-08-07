"""Aceite HTTP do limite por IP em `/api/v1/auth/login` (frente 1).

Roda via TestClient, sem docker. O que se prova é o contrato de ponta a ponta:

A1. *Password spraying* — uma senha contra muitas contas, de um IP só — para de ser
    atendido, com 429 + `Retry-After` em RFC-7807. O bloqueio por CONTA da G01 não vê
    esse ataque: nenhuma conta chega perto das cinco falhas.
A2. A requisição recusada NÃO paga argon2. Esta é a asserção que transforma o limite de
    "higiene" em defesa de DoS, e ela é medida contando as chamadas ao hash — não
    deduzida do código.
A3. Quem legitimamente falha de OUTRO IP continua sendo atendido (o limite é por IP).
A4. O usuário legítimo do MESMO IP não fica trancado: o acerto zera a conta de falhas.
A5. A janela DESLIZA — provado com `ClockPort` (§2.1), sem `sleep` na suíte.

`TestClient(..., client=(ip, porta))` fixa o peer TCP do escopo ASGI: é assim que se
simulam IPs diferentes sem forjar `X-Forwarded-For` (que o limitador não confia — e é
justamente o ponto).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.errors import PROBLEM_CONTENT_TYPE
from app.middleware_limite import JANELA_CUSTO_S, TETO_CUSTO, LimitePorIp
from domain.identidade import senha as regras_senha
from tests.conftest import ClienteJornada

TENANT = {"X-Tenant": "torre-movel"}
ADMIN = TENANT | {"Authorization": "Bearer dev-admin"}
PROVISORIA = "provisoria-longa-01"

IP_ATACANTE = "203.0.113.9"
IP_LEGITIMO = "198.51.100.4"


class RelogioFixo:
    def __init__(self) -> None:
        self.instante = datetime(2026, 8, 7, 9, 0, tzinfo=UTC)

    def agora(self) -> datetime:
        return self.instante

    def avancar(self, segundos: float) -> None:
        self.instante += timedelta(seconds=segundos)


@pytest.fixture()
def relogio_limite(app: FastAPI) -> RelogioFixo:
    """Injeta o limitador do app com relógio manipulável (o de produção usa RelogioSistema)."""
    relogio = RelogioFixo()
    app.state.limite_login = LimitePorIp(relogio)
    return relogio


def cliente_do_ip(app: FastAPI, ip: str) -> TestClient:
    """Cliente com peer TCP fixo — e com a credencial que existe nos DOIS ambientes.

    `ClienteJornada` (e não o `TestClient` cru) porque o preparo destes aceites chama
    `POST /auth/usuarios` com `Bearer dev-admin`: token estático que NÃO vale em
    `APP_ENV=prod` (§10.3), onde o preparo virava 401 e levava cinco aceites de limite
    junto. O cliente troca o portador declarado por SESSÃO real (tests/conftest.py), o
    que mantém estes testes válidos em dev e em prod — e prod é o modo em que o limite
    de login por IP realmente precisa estar de pé. `client=(ip, porta)` segue intacto:
    é ele que fixa o peer do escopo ASGI, que é o que se mede aqui.
    """
    return ClienteJornada(app, raise_server_exceptions=False, client=(ip, 51000))


def criar_conta(app: FastAPI, email: str) -> None:
    with cliente_do_ip(app, "10.0.0.1") as admin:
        resposta = admin.post(
            "/api/v1/auth/usuarios",
            json={
                "email": email,
                "nome": "Alvo",
                "papeis": ["analista"],
                "senha_provisoria": PROVISORIA,
            },
            headers=ADMIN,
        )
    assert resposta.status_code == 201, resposta.text


def tentar_login(cliente: TestClient, email: str, senha: str):  # noqa: ANN201
    cliente.cookies.clear()
    return cliente.post("/api/v1/auth/login", json={"email": email, "senha": senha}, headers=TENANT)


@pytest.fixture()
def hashes_pagos(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Conta cada argon2 REALMENTE executado no caminho de login.

    É o medidor do A2: sem ele, "a requisição recusada não custa CPU" seria uma
    afirmação sobre a ordem das linhas, não um fato observado.

    Instrumenta SÓ `regras_senha.verificar`, e isso já cobre os dois caminhos: quando a
    conta não existe, `consumir_tempo_de_verificacao` chama `verificar` por dentro (é
    para isso que ela existe — igualar o relógio dos dois caminhos, §10.2). Uma
    tentativa de login = exatamente um `verificar`, exista o e-mail ou não.
    """
    registro: list[str] = []
    verificar_original = regras_senha.verificar

    def verificar(senha_hash: str, senha: str) -> bool:
        registro.append("verificar")
        return verificar_original(senha_hash, senha)

    monkeypatch.setattr(regras_senha, "verificar", verificar)
    return registro


# ------------------------------------------------------------------------------ A1/A2
def test_spraying_de_um_ip_para_no_429_e_nao_paga_argon2(
    app: FastAPI, relogio_limite: RelogioFixo, hashes_pagos: list[str]
) -> None:
    """A1+A2: `TETO_CUSTO` tentativas são atendidas; da seguinte em diante, 429 SEM hash.

    O spraying aqui é literal — cada tentativa é numa CONTA DIFERENTE com a mesma senha,
    então o contador por conta (`bloqueado_ate`, máx. 5 falhas) nunca dispara em conta
    nenhuma. Se o limite por IP não existisse, o laço seguiria indefinidamente.
    """
    with cliente_do_ip(app, IP_ATACANTE) as atacante:
        for i in range(TETO_CUSTO):
            resposta = tentar_login(atacante, f"alvo{i}@torre.local", "Verao@2026")
            assert resposta.status_code == 401, resposta.text

        assert len(hashes_pagos) == TETO_CUSTO  # cada 401 custou exatamente um argon2

        for i in range(5):
            recusada = tentar_login(atacante, f"alvo{TETO_CUSTO + i}@torre.local", "Verao@2026")
            assert recusada.status_code == 429
            assert recusada.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
            corpo = recusada.json()
            assert corpo["status"] == 429 and corpo["title"] == "Too Many Requests"
            assert int(recusada.headers["Retry-After"]) >= 1
            assert corpo["retry_after_s"] == int(recusada.headers["Retry-After"])
            # e o 429 continua sem revelar nada sobre a base
            assert "alvo" not in corpo["detail"]

    # A2: as cinco recusadas não moveram o contador — nenhum hash a mais foi calculado.
    assert len(hashes_pagos) == TETO_CUSTO


def test_retry_after_do_429_e_honesto_e_a_janela_desliza(
    app: FastAPI, relogio_limite: RelogioFixo
) -> None:
    """A5: esperar o `Retry-After` anunciado basta para voltar a ser atendido."""
    criar_conta(app, "ana@torre.local")
    with cliente_do_ip(app, IP_ATACANTE) as atacante:
        for _ in range(TETO_CUSTO):
            tentar_login(atacante, "ana@torre.local", "errada-mas-longa")
        bloqueada = tentar_login(atacante, "ana@torre.local", "errada-mas-longa")
        assert bloqueada.status_code == 429
        espera = int(bloqueada.headers["Retry-After"])
        assert espera <= JANELA_CUSTO_S

        relogio_limite.avancar(espera)
        depois = tentar_login(atacante, "ana@torre.local", "errada-mas-longa")
        assert depois.status_code == 401  # atendido de novo (e recusado por senha, não por IP)


# --------------------------------------------------------------------------------- A3
def test_limite_e_por_ip_o_vizinho_continua_entrando(
    app: FastAPI, relogio_limite: RelogioFixo
) -> None:
    """A3: com o IP do atacante no teto, o usuário legítimo de outro IP entra normalmente."""
    criar_conta(app, "bia@torre.local")
    # O spraying varre contas ALHEIAS (é o que ele faz): a bia não é alvo, e por isso o
    # bloqueio POR CONTA dela nem chega a ser tocado — só o teto do IP do atacante.
    with cliente_do_ip(app, IP_ATACANTE) as atacante:
        for i in range(TETO_CUSTO + 3):
            tentar_login(atacante, f"alvo{i}@torre.local", "Verao@2026")
        assert tentar_login(atacante, "alvo99@torre.local", "Verao@2026").status_code == 429

    with cliente_do_ip(app, IP_LEGITIMO) as legitimo:
        entrada = tentar_login(legitimo, "bia@torre.local", PROVISORIA)
    assert entrada.status_code == 200, entrada.text
    assert entrada.json()["email"] == "bia@torre.local"


# --------------------------------------------------------------------------------- A4
def test_usuario_legitimo_nao_e_trancado_pelo_colega_do_mesmo_ip(
    app: FastAPI, relogio_limite: RelogioFixo
) -> None:
    """A4: NAT de escritório. Quatro pessoas do mesmo IP público erram a senha algumas
    vezes cada (nenhuma chega às 5 falhas que bloqueariam a PRÓPRIA conta) e juntas quase
    esgotam o orçamento anti-spraying do IP. Quem então acerta zera esse orçamento — e o
    andar segue sendo atendido em vez de trancar."""
    colegas = [f"colega{i}@torre.local" for i in range(4)]
    for email in colegas:
        criar_conta(app, email)

    with cliente_do_ip(app, IP_LEGITIMO) as escritorio:
        for email in colegas:
            for _ in range(4):  # 4 < 5: o bloqueio POR CONTA não dispara em ninguém
                assert tentar_login(escritorio, email, "erro-de-digitacao").status_code == 401
                relogio_limite.avancar(7)  # ritmo humano: longe do teto de CUSTO

        assert app.state.limite_login.estado(IP_LEGITIMO)["falhas"] == 16  # 4 × 4

        ok = tentar_login(escritorio, colegas[0], PROVISORIA)
        assert ok.status_code == 200, ok.text
        assert app.state.limite_login.estado(IP_LEGITIMO)["falhas"] == 0  # a válvula

        # e o próximo colega distraído ainda é atendido (recusado pela SENHA, não pelo IP)
        relogio_limite.avancar(7)
        assert tentar_login(escritorio, colegas[1], "outro-erro-longo").status_code == 401


def test_login_normal_de_um_usuario_nunca_encosta_no_limite(
    app: FastAPI, relogio_limite: RelogioFixo
) -> None:
    """Guarda-corpo contra apertar os números demais: o uso REAL (entrar, sair, entrar)
    tem de passar longe do teto. Se um dia alguém baixar `TETO_CUSTO` para 2, é este
    teste que reclama antes do usuário."""
    criar_conta(app, "diana@torre.local")
    with cliente_do_ip(app, IP_LEGITIMO) as pessoa:
        for _ in range(3):
            assert tentar_login(pessoa, "diana@torre.local", PROVISORIA).status_code == 200
            assert pessoa.post("/api/v1/auth/logout", headers=TENANT).status_code == 204
    assert app.state.limite_login.estado(IP_LEGITIMO)["custo"] < TETO_CUSTO


def test_rotas_autenticadas_que_hasheiam_nao_ficam_sob_o_limite_de_ip(
    app: FastAPI, relogio_limite: RelogioFixo
) -> None:
    """O limite guarda a superfície ANÔNIMA. Um admin criando muitas contas de uma vez
    (carga inicial de tenant) hasheia bastante e NÃO pode ser barrado por isso — ali o
    gate é o RBAC, que já provou quem é."""
    with cliente_do_ip(app, IP_LEGITIMO) as admin:
        for i in range(TETO_CUSTO + 5):
            resposta = admin.post(
                "/api/v1/auth/usuarios",
                json={
                    "email": f"lote{i}@torre.local",
                    "nome": "Lote",
                    "papeis": ["analista"],
                    "senha_provisoria": PROVISORIA,
                },
                headers=ADMIN,
            )
            assert resposta.status_code == 201, resposta.text
