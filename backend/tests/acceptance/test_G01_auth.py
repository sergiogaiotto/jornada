"""Aceites de `/api/v1/auth` (emenda G01) — identidade real por trás do RBAC §8-M0.

Rodam via TestClient, sem docker. O que se prova aqui é o contrato HTTP: cookie
httpOnly, RFC-7807 em todo erro, login que não vira oráculo de existência, o guard de
senha expirada e a recusa dos tokens `dev-<papel>` fora de dev.
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.errors import PROBLEM_CONTENT_TYPE

TENANT = {"X-Tenant": "torre-movel"}
ADMIN = TENANT | {"Authorization": "Bearer dev-admin"}
COOKIE = "jornada_sessao"

PROVISORIA = "provisoria-longa-01"
DEFINITIVA = "correta-cavalo-bateria"


class _RelogioFixo:
    """ClockPort (§2.1) manipulável — expiração de sessão provada por AVANÇO."""

    def __init__(self, instante: datetime) -> None:
        self.instante = instante

    def agora(self) -> datetime:
        return self.instante

    def avancar(self, delta: timedelta) -> None:
        self.instante += delta


def _criar_usuario(
    client: TestClient, email: str = "ana@torre.local", papeis: list[str] | None = None
) -> dict:
    """Cria a conta pela rota de ADMIN (não há e-mail de convite — §3.1 SMTP sem consumidor)."""
    client.cookies.clear()  # garante que a credencial usada é o Bearer, não uma sessão
    resposta = client.post(
        "/api/v1/auth/usuarios",
        json={
            "email": email,
            "nome": "Ana",
            "papeis": papeis or ["analista"],
            "senha_provisoria": PROVISORIA,
        },
        headers=ADMIN,
    )
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


def _login(client: TestClient, email: str, senha: str) -> object:
    client.cookies.clear()
    return client.post("/api/v1/auth/login", json={"email": email, "senha": senha}, headers=TENANT)


# --------------------------------------------------------------------- login/sessão
def test_login_ok_seta_cookie_httponly_e_eu_responde(client: TestClient) -> None:
    _criar_usuario(client)
    resposta = _login(client, "ana@torre.local", PROVISORIA)

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["email"] == "ana@torre.local"
    assert corpo["papeis"] == ["analista"]
    assert corpo["senha_expirada"] is True  # senha provisória
    # o segredo não sai por nenhuma via: nem a senha em claro, nem o hash
    assert PROVISORIA not in resposta.text
    assert "senha_hash" not in resposta.text and "argon2" not in resposta.text

    set_cookie = resposta.headers["set-cookie"]
    assert "HttpOnly" in set_cookie  # JS não alcança — é o ponto do desenho
    assert "SameSite=lax" in set_cookie.replace("samesite", "SameSite")
    assert "Secure" not in set_cookie  # HTTP puro hoje (SESSION_COOKIE_SECURE=false)

    eu = client.get("/api/v1/auth/eu", headers=TENANT)
    assert eu.status_code == 200
    assert eu.json()["nome"] == "Ana"


def test_login_errado_nao_revela_se_o_email_existe(client: TestClient) -> None:
    """A1 do aceite: e-mail inexistente e senha errada devolvem a MESMA resposta —
    corpo e status idênticos. Sem isso o login enumera a base (que tem PII real)."""
    _criar_usuario(client)

    inexistente = _login(client, "ninguem@torre.local", DEFINITIVA)
    senha_errada = _login(client, "ana@torre.local", "chute-bem-longo-01")

    assert inexistente.status_code == senha_errada.status_code == 401
    assert inexistente.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    assert inexistente.json() == senha_errada.json()
    assert "set-cookie" not in inexistente.headers


def test_bloqueio_por_tentativas_recusa_ate_a_senha_certa(client: TestClient) -> None:
    """5 falhas (LOGIN_MAX_TENTATIVAS) → bloqueio temporal; a senha CERTA também é
    recusada, e com o mesmo corpo (o bloqueio não pode virar oráculo de existência)."""
    _criar_usuario(client, email="cauê@torre.local")
    for _ in range(5):
        assert _login(client, "cauê@torre.local", "errada-mas-longa").status_code == 401

    bloqueado = _login(client, "cauê@torre.local", PROVISORIA)
    assert bloqueado.status_code == 401
    assert bloqueado.json() == _login(client, "ninguem@torre.local", PROVISORIA).json()


def test_sessao_expirada_nao_autentica(app: FastAPI, client: TestClient) -> None:
    relogio = _RelogioFixo(datetime(2026, 8, 6, 9, 0, 0, tzinfo=UTC))
    app.state.relogio = relogio
    _criar_usuario(client)
    assert _login(client, "ana@torre.local", PROVISORIA).status_code == 200
    assert client.get("/api/v1/auth/eu", headers=TENANT).status_code == 200

    relogio.avancar(timedelta(hours=13))  # SESSION_TTL_HORAS = 12
    assert client.get("/api/v1/auth/eu", headers=TENANT).status_code == 401


def test_sessao_revogada_pelo_logout_nao_autentica(client: TestClient) -> None:
    """O cookie continua na mão do cliente; o que morreu foi a LINHA em `sessao` — é
    exatamente isso que um JWT no localStorage não conseguiria oferecer."""
    _criar_usuario(client)
    assert _login(client, "ana@torre.local", PROVISORIA).status_code == 200
    token = client.cookies.get(COOKIE)
    assert token

    assert client.post("/api/v1/auth/logout", headers=TENANT).status_code == 204

    client.cookies.clear()
    resposta = client.get("/api/v1/auth/eu", headers=TENANT | {"Cookie": f"{COOKIE}={token}"})
    assert resposta.status_code == 401
    assert resposta.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)


def test_logout_sem_sessao_e_idempotente(client: TestClient) -> None:
    client.cookies.clear()
    assert client.post("/api/v1/auth/logout", headers=TENANT).status_code == 204


def test_cookie_de_outro_tenant_nao_le_pelo_header(
    app: FastAPI, client: TestClient, tokens_outro_tenant: dict[str, str]
) -> None:
    """Achado 5/UAT5 estendido à sessão: o middleware de `main.py` só confere o
    `X-Tenant` contra portadores BEARER; para quem entra por cookie a conferência é do
    `get_current_user`. Sem ela, o header voltaria a ser fonte da verdade."""
    _criar_usuario(client)
    assert _login(client, "ana@torre.local", PROVISORIA).status_code == 200

    resposta = client.get("/api/v1/auth/eu", headers={"X-Tenant": "outra-torre"})
    assert resposta.status_code == 403
    assert "X-Tenant" in resposta.json()["detail"]


# ---------------------------------------------------------- senha expirada / troca
def test_senha_expirada_barra_rota_comum_e_libera_as_tres_de_auth(client: TestClient) -> None:
    """Guard do `get_current_user`: com senha provisória a conta AUTENTICA mas não
    NAVEGA. `eu`, `trocar-senha` e `logout` continuam abertas — senão o usuário fica
    preso sem caminho para sair do estado."""
    _criar_usuario(client)
    assert _login(client, "ana@torre.local", PROVISORIA).status_code == 200

    barrada = client.get("/api/v1/os", headers=TENANT)
    assert barrada.status_code == 403
    assert barrada.headers["x-erro-codigo"] == "senha_expirada"
    assert barrada.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)

    assert client.get("/api/v1/auth/eu", headers=TENANT).status_code == 200


def test_troca_de_senha_limpa_a_flag_e_destrava_a_navegacao(client: TestClient) -> None:
    _criar_usuario(client)
    assert _login(client, "ana@torre.local", PROVISORIA).status_code == 200

    ruim = client.post(
        "/api/v1/auth/trocar-senha",
        json={"senha_atual": PROVISORIA, "senha_nova": "curta"},
        headers=TENANT,
    )
    assert ruim.status_code == 422
    assert ruim.json()["erros"]  # todas as violações de uma vez

    errada = client.post(
        "/api/v1/auth/trocar-senha",
        json={"senha_atual": "chute-bem-longo-01", "senha_nova": DEFINITIVA},
        headers=TENANT,
    )
    assert errada.status_code == 403

    trocada = client.post(
        "/api/v1/auth/trocar-senha",
        json={"senha_atual": PROVISORIA, "senha_nova": DEFINITIVA},
        headers=TENANT,
    )
    assert trocada.status_code == 200
    assert trocada.json()["senha_expirada"] is False
    assert client.get("/api/v1/os", headers=TENANT).status_code == 200  # navegação liberada

    # a senha nova é a que vale a partir de agora
    assert _login(client, "ana@torre.local", PROVISORIA).status_code == 401
    assert _login(client, "ana@torre.local", DEFINITIVA).status_code == 200


def test_provisoria_nao_pode_ser_trocada_por_ela_mesma(client: TestClient) -> None:
    """Auditoria da frente 1: sem esta recusa o admin ficava com credencial PERMANENTE.

    A conta nasce com a senha que o ADMIN escolheu. "Trocar" essa senha por ela mesma
    limpava `senha_expirada` e liberava a navegação — a senha que o admin conhece
    continuava valendo para sempre, que é exatamente o que a flag existe para impedir.
    """
    _criar_usuario(client)
    assert _login(client, "ana@torre.local", PROVISORIA).status_code == 200

    repetida = client.post(
        "/api/v1/auth/trocar-senha",
        json={"senha_atual": PROVISORIA, "senha_nova": PROVISORIA},
        headers=TENANT,
    )
    assert repetida.status_code == 422
    assert repetida.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    # segue presa: a navegação continua barrada e a provisória continua sendo provisória
    assert client.get("/api/v1/auth/eu", headers=TENANT).json()["senha_expirada"] is True
    assert client.get("/api/v1/os", headers=TENANT).status_code == 403


def test_bootstrap_semeia_em_todo_app_do_processo(monkeypatch: pytest.MonkeyPatch) -> None:
    """O bootstrap não pode depender de um estado de PROCESSO que a 1ª passagem destrói.

    Havia aqui um `settings.jornada_root_senha = SecretStr("")` vendido como higiene de
    segredo. Ele não apagava nada (a variável segue em `os.environ`, e todo `Settings()`
    novo a relê em claro) e escrevia no objeto do `lru_cache`, que é global ao PROCESSO,
    enquanto o `_root_semeado` que o protege é do APP: o segundo `create_app()` do mesmo
    processo subia SEM root e sem erro nenhum. Falha silenciosa na conta mais poderosa.
    """
    import api.v1.autenticacao as modulo_auth_api
    from app.main import create_app, ping_db

    unico = Settings(
        _env_file=None,
        jornada_root_email="sergio.gaiotto",
        jornada_root_senha="senha-inicial-root",
    )
    monkeypatch.setattr(modulo_auth_api, "get_settings", lambda: unico)

    for volta in (1, 2):
        aplicacao = create_app(demo=False)
        aplicacao.dependency_overrides[ping_db] = lambda: "ok"
        with TestClient(aplicacao, raise_server_exceptions=False) as cliente:
            entrada = cliente.post(
                "/api/v1/auth/login",
                json={"email": "sergio.gaiotto", "senha": "senha-inicial-root"},
                headers=TENANT,
            )
            assert entrada.status_code == 200, f"app nº {volta} subiu sem root: {entrada.text}"


def test_troca_de_senha_rotaciona_a_sessao(client: TestClient) -> None:
    """Cookie que já circulou não sobrevive à troca (defesa contra fixação de sessão)."""
    _criar_usuario(client)
    assert _login(client, "ana@torre.local", PROVISORIA).status_code == 200
    antigo = client.cookies.get(COOKIE)

    resposta = client.post(
        "/api/v1/auth/trocar-senha",
        json={"senha_atual": PROVISORIA, "senha_nova": DEFINITIVA},
        headers=TENANT,
    )
    novo = resposta.cookies.get(COOKIE)
    assert novo and novo != antigo

    client.cookies.clear()
    assert (
        client.get("/api/v1/auth/eu", headers=TENANT | {"Cookie": f"{COOKIE}={antigo}"}).status_code
        == 401
    )


# ------------------------------------------------------------------ admin/usuários
def test_email_duplicado_no_tenant_409_e_permitido_em_outro_tenant(
    client: TestClient, tokens_outro_tenant: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.auth import DEV_TOKENS, Usuario

    _criar_usuario(client)
    repetido = client.post(
        "/api/v1/auth/usuarios",
        json={
            "email": "ANA@torre.local",
            "nome": "Ana 2",
            "papeis": ["analista"],
            "senha_provisoria": PROVISORIA,
        },
        headers=ADMIN,
    )
    assert repetido.status_code == 409

    # admin do OUTRO tenant: o mesmo e-mail tem de caber lá (unique é por tenant — 0015)
    base = DEV_TOKENS["dev-admin"]
    monkeypatch.setitem(
        DEV_TOKENS,
        "dev-admin-outra-torre",
        Usuario(
            id=base.id,
            tenant_id="outra-torre",
            nome="Dev Admin (outra torre)",
            email="admin@outra-torre.local",
            papeis=("admin",),
        ),
    )
    client.cookies.clear()
    outro = client.post(
        "/api/v1/auth/usuarios",
        json={
            "email": "ana@torre.local",
            "nome": "Ana (outra torre)",
            "papeis": ["analista"],
            "senha_provisoria": PROVISORIA,
        },
        headers={"X-Tenant": "outra-torre", "Authorization": "Bearer dev-admin-outra-torre"},
    )
    assert outro.status_code == 201
    assert outro.json()["tenant_id"] == "outra-torre"


def test_rotas_de_admin_exigem_papel_admin(client: TestClient) -> None:
    client.cookies.clear()
    resposta = client.get(
        "/api/v1/auth/usuarios", headers=TENANT | {"Authorization": "Bearer dev-analista"}
    )
    assert resposta.status_code == 403


def test_listar_usuarios_nao_expoe_hash(client: TestClient) -> None:
    _criar_usuario(client)
    resposta = client.get("/api/v1/auth/usuarios", headers=ADMIN)
    assert resposta.status_code == 200
    assert "argon2" not in resposta.text
    assert "senha_hash" not in resposta.text


def test_desativar_usuario_derruba_a_sessao_no_proximo_request(client: TestClient) -> None:
    criado = _criar_usuario(client)
    assert _login(client, "ana@torre.local", PROVISORIA).status_code == 200
    token = client.cookies.get(COOKIE)

    client.cookies.clear()
    assert (
        client.post(f"/api/v1/auth/usuarios/{criado['id']}/desativar", headers=ADMIN).status_code
        == 200
    )

    resposta = client.get("/api/v1/auth/eu", headers=TENANT | {"Cookie": f"{COOKIE}={token}"})
    assert resposta.status_code == 401


def test_usuario_de_outro_tenant_responde_404(client: TestClient) -> None:
    """Isolamento §8: conta alheia é indistinguível de conta inexistente."""
    import uuid

    resposta = client.post(f"/api/v1/auth/usuarios/{uuid.uuid4()}/desativar", headers=ADMIN)
    assert resposta.status_code == 404


# ---------------------------------------------------- tokens de dev fora de dev (UAT #5)
def test_config_recusa_tokens_dev_em_prod() -> None:
    """Fail-fast de startup no mesmo padrão do APP_SECRET (§10.3)."""
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="prod", app_secret="segredo", permitir_tokens_dev=True)


def test_dev_tokens_recusados_com_app_env_prod(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`dev-admin` é uma senha PUBLICADA no repositório — em prod não pode valer.

    Fecha o achado do UAT #5: até aqui o token estático era aceito em qualquer ambiente.
    """
    import app.auth as modulo_auth

    prod = Settings(_env_file=None, app_env="prod", app_secret="segredo-de-vault")
    monkeypatch.setattr(modulo_auth, "get_settings", lambda: prod)

    client.cookies.clear()
    assert client.get("/api/v1/os", headers=ADMIN).status_code == 401
    assert client.get("/api/v1/auth/eu", headers=ADMIN).status_code == 401
    # e o portal (§8-M3) cai junto
    assert (
        client.get(
            "/api/v1/pedidos", headers=TENANT | {"Authorization": "Bearer portal-dev"}
        ).status_code
        == 401
    )


def test_dev_tokens_valem_em_homolog_so_com_opt_in(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.auth as modulo_auth

    homolog = Settings(_env_file=None, app_env="homolog", permitir_tokens_dev=False)
    monkeypatch.setattr(modulo_auth, "get_settings", lambda: homolog)
    client.cookies.clear()
    assert client.get("/api/v1/os", headers=ADMIN).status_code == 401

    com_opt_in = Settings(_env_file=None, app_env="homolog", permitir_tokens_dev=True)
    monkeypatch.setattr(modulo_auth, "get_settings", lambda: com_opt_in)
    assert client.get("/api/v1/os", headers=ADMIN).status_code == 200


# ------------------------------------------------------------- bootstrap do root
def test_bootstrap_do_root_cria_e_nao_reseta(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Idempotência ponta a ponta: o root nasce com senha expirada; depois de trocar,
    subir de novo com a MESMA variável no ambiente não devolve a senha antiga."""
    import api.v1.autenticacao as modulo_auth_api

    inicial = Settings(
        _env_file=None,
        jornada_root_email="sergio.gaiotto",
        jornada_root_senha="senha-inicial-root",
    )
    monkeypatch.setattr(modulo_auth_api, "get_settings", lambda: inicial)

    assert _login(client, "sergio.gaiotto", "senha-inicial-root").status_code == 200
    assert client.get("/api/v1/auth/eu", headers=TENANT).json()["papeis"] == ["admin"]
    assert client.get("/api/v1/auth/eu", headers=TENANT).json()["senha_expirada"] is True

    assert (
        client.post(
            "/api/v1/auth/trocar-senha",
            json={"senha_atual": "senha-inicial-root", "senha_nova": DEFINITIVA},
            headers=TENANT,
        ).status_code
        == 200
    )

    # "restart": o bootstrap roda de novo com a variável ainda no ambiente
    app.state._root_semeado = False
    monkeypatch.setattr(
        modulo_auth_api,
        "get_settings",
        lambda: Settings(
            _env_file=None,
            jornada_root_email="sergio.gaiotto",
            jornada_root_senha="senha-inicial-root",
        ),
    )
    assert _login(client, "sergio.gaiotto", "senha-inicial-root").status_code == 401
    assert _login(client, "sergio.gaiotto", DEFINITIVA).status_code == 200
