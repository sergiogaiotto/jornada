"""Aceites do CORTE DE AMBIENTE (frente 3) — o que muda quando `APP_ENV=prod`.

Contexto, porque ele explica o formato destes testes. A auditoria mediu que a suíte
inteira rodava em `APP_ENV=dev`: em `prod`, ~200 aceites caíam em 401 — todos pelo
token estático `dev-<papel>`. O modo em que a PII real vai rodar tinha cobertura ZERO,
e virar a chave seria virar para o escuro. A resposta em duas partes:

· a suíte passou a autenticar por SESSÃO em vez de token de dev (tests/conftest.py),
  o que a torna executável nos DOIS modos e a põe no CI com `APP_ENV=prod`;
· este arquivo cobre o que só existe no CORTE — os comportamentos que mudam com o
  ambiente, e que por definição nenhum aceite de módulo (M0–M12) mede.

Cada teste aqui prova o gate por INVERSÃO no próprio corpo: mostra o comportamento em
prod E o comportamento em dev com a mesma chamada. Aceite de configuração que só olha
um lado não distingue "o gate funciona" de "não havia nada para bloquear".
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from adapters.demo_seeds import OS_CODIGO_DEMO
from adapters.embedding.fake import EmbeddingFake
from adapters.llm.fake import LLMFake
from adapters.observabilidade.langfuse import TracerLangfuse
from app.auth import DEV_TOKENS, PORTAL_TOKENS
from app.config import Settings
from app.main import create_app, ping_db, ping_llm

TENANT = {"X-Tenant": "torre-movel"}
RAIZ = Path(__file__).resolve().parents[3]

ROOT_LOGIN = "root.jornada"
ROOT_PROVISORIA = "provisoria-do-root-01"
ROOT_DEFINITIVA = "frase-propria-do-root-01"


def _prod(**extra: object) -> Settings:
    """Config de prod válida — `app_secret` próprio é pré-condição, não detalhe."""
    return Settings(_env_file=None, app_env="prod", app_secret="segredo-de-vault", **extra)


def _preparar(aplicacao: object) -> None:
    """Dublês de §1.3.5 idênticos aos do conftest (estes apps nascem fora da fixture)."""
    aplicacao.dependency_overrides[ping_db] = lambda: "ok"  # type: ignore[attr-defined]
    aplicacao.dependency_overrides[ping_llm] = lambda: "skip"  # type: ignore[attr-defined]
    aplicacao.state.llm = LLMFake()  # type: ignore[attr-defined]
    aplicacao.state.embedding = EmbeddingFake()  # type: ignore[attr-defined]
    aplicacao.state.tracer = TracerLangfuse(  # type: ignore[attr-defined]
        Settings(_env_file=None, langfuse_enabled=False)
    )


# ------------------------------------------------------- 1 · tokens dev fora de dev
@pytest.mark.parametrize("rotulo", sorted(DEV_TOKENS) + sorted(PORTAL_TOKENS))
def test_nenhum_token_estatico_autentica_em_prod(
    client_bearer: TestClient, monkeypatch: pytest.MonkeyPatch, rotulo: str
) -> None:
    """A CLASSE inteira, não três casos: todo `dev-<papel>` e todo `portal-*` morre.

    O G01 já fixava `dev-admin` e `portal-dev`. Aqui o parametrize varre os dicionários
    de verdade, então um portador novo acrescentado amanhã entra no aceite sozinho — é
    a diferença entre um teste e uma lista que envelhece calada.

    `client_bearer` porque o cliente comum troca o token por sessão real antes de sair
    (tests/conftest.py): aqui o header PRECISA chegar cru à aplicação.
    """
    import app.auth as modulo_auth

    cabecalhos = TENANT | {"Authorization": f"Bearer {rotulo}"}

    monkeypatch.setattr(modulo_auth, "get_settings", _prod)
    client_bearer.cookies.clear()
    # `/os` cobre `get_current_user`; `/pedidos` (POST) cobre `get_portador`, o outro
    # portão — o token de portal só existe naquele, e ele também tem de fechar.
    assert client_bearer.get("/api/v1/os", headers=cabecalhos).status_code == 401
    criacao = client_bearer.post(
        "/api/v1/pedidos",
        json={"solicitante": {"nome": "Beto"}, "conteudo": {}},
        headers=cabecalhos,
    )
    assert criacao.status_code == 401, criacao.text

    # INVERSÃO no mesmo teste: em dev o MESMO header autentica. Sem esta metade, um 401
    # por rota errada, header errado ou app quebrado passaria por "gate funcionando".
    monkeypatch.setattr(
        modulo_auth, "get_settings", lambda: Settings(_env_file=None, app_env="dev")
    )
    assert (
        client_bearer.post(
            "/api/v1/pedidos",
            json={"solicitante": {"nome": "Beto"}, "conteudo": {}},
            headers=cabecalhos,
        ).status_code
        == 201
    )


def test_config_recusa_o_opt_in_de_tokens_dev_em_prod() -> None:
    """`PERMITIR_TOKENS_DEV=true` + prod não é aviso: a config NÃO CARREGA (§10.3).

    Fecha o furo seguinte ao do token em si — subir prod com o opt-in ligado "só para
    depurar" e esquecer ligado.
    """
    with pytest.raises(ValidationError) as capturado:
        _prod(permitir_tokens_dev=True)
    mensagem = str(capturado.value)
    assert "PERMITIR_TOKENS_DEV" in mensagem  # a mensagem NOMEIA a variável
    assert "10.3" in mensagem  # e aponta a seção do contrato

    # inversão: fora de prod a mesma combinação é legítima (homolog com opt-in)
    assert Settings(_env_file=None, app_env="homolog", permitir_tokens_dev=True).permitir_tokens_dev


# ------------------------------------------------- 2 · variável obrigatória ausente
def test_app_secret_ausente_derruba_o_startup_com_mensagem_util(
    ambiente_sem_config: None,
) -> None:
    """§10.3: sem `APP_SECRET` próprio, `APP_ENV=prod` não sobe — e diz por quê.

    "Mensagem útil" tem critério: nomear a VARIÁVEL (quem lê o log precisa saber o que
    exportar) e apontar a SEÇÃO do contrato. Uma `ValidationError` genérica manda o
    operador ler o código-fonte às 3h da manhã.

    `ambiente_sem_config` é o que torna este teste honesto: `_env_file=None` desliga só
    o ARQUIVO, e com a suíte rodando também sob `APP_ENV=prod` o `APP_SECRET` do
    processo entrava por baixo — o teste do guarda-corpo dependia do ambiente que o
    guarda-corpo existe justamente para não confiar.
    """
    with pytest.raises(ValidationError) as capturado:
        Settings(_env_file=None, app_env="prod")
    mensagem = str(capturado.value)
    assert "APP_SECRET" in mensagem
    assert "10.3" in mensagem

    # inversão: com segredo próprio a MESMA config carrega
    assert Settings(_env_file=None, app_env="prod", app_secret="segredo-de-vault").app_env == "prod"
    # e fora de prod o default segue valendo (o gate é do ambiente, não do valor)
    assert Settings(_env_file=None, app_env="dev").app_secret == "change-me"


# ------------------------------------------------------- 3 · DEMO_MODE ignorado em prod
def test_demo_mode_e_ignorado_em_prod(monkeypatch: pytest.MonkeyPatch) -> None:
    """`DEMO_MODE=true` + `APP_ENV=prod` NÃO semeia a OS-2026-0457 (§11.4).

    O gate já existia em `app/main.py` (`demo_mode and app_env == "dev"`) e nunca foi
    medido. Importa porque a seed é dado sintético de demonstração entrando num tenant
    que vai conter PII real de cliente: uma campanha fantasma no Cockpit de produção é,
    no melhor caso, ruído de auditoria.
    """
    import app.main as modulo_main

    monkeypatch.setattr(modulo_main, "get_settings", lambda: _prod(demo_mode=True))
    em_prod = create_app(embedding=EmbeddingFake())
    assert em_prod.state.repositorio_os.obter_os_por_codigo(OS_CODIGO_DEMO) is None

    # INVERSÃO: a MESMA `DEMO_MODE=true` semeia em dev — prova que o que bloqueou foi o
    # ambiente, e não a seed ter parado de funcionar.
    monkeypatch.setattr(
        modulo_main, "get_settings", lambda: Settings(_env_file=None, app_env="dev", demo_mode=True)
    )
    em_dev = create_app(embedding=EmbeddingFake())
    assert em_dev.state.repositorio_os.obter_os_por_codigo(OS_CODIGO_DEMO) is not None


# ------------------------------- 4 · a aplicação sobe utilizável num tenant VAZIO
def test_tenant_vazio_sem_demo_sobe_e_cria_a_primeira_os(monkeypatch: pytest.MonkeyPatch) -> None:
    """Com `DEMO_MODE` fora do ar, dá para entrar e criar a PRIMEIRA OS do zero?

    É a pergunta que o corte de ambiente levanta e que nenhum aceite respondia: todos os
    caminhos de teste começavam com uma OS já existente (seed ou criada por token de
    dev). Este percorre a jornada do primeiro dia real, sem NENHUM token estático:

        boot → /healthz → login do root → troca da senha provisória → lista vazia →
        POST /os → a OS aparece na lista.

    O passo do 403 no meio não é ruído: com senha provisória a conta AUTENTICA mas não
    NAVEGA (§8-M0), e quem sobe a plataforma pela primeira vez bate exatamente nele.
    """
    import api.v1.autenticacao as modulo_auth_api
    import app.main as modulo_main

    def _config() -> Settings:
        return _prod(
            demo_mode=True,  # ligado de propósito: em prod tem de ser ignorado
            jornada_root_email=ROOT_LOGIN,
            jornada_root_senha=SecretStr(ROOT_PROVISORIA),
        )

    monkeypatch.setattr(modulo_main, "get_settings", _config)
    monkeypatch.setattr(modulo_auth_api, "get_settings", _config)

    aplicacao = create_app(embedding=EmbeddingFake())
    _preparar(aplicacao)

    with TestClient(aplicacao, raise_server_exceptions=False) as cliente:
        assert cliente.get("/healthz").status_code == 200

        entrada = cliente.post(
            "/api/v1/auth/login",
            json={"email": ROOT_LOGIN, "senha": ROOT_PROVISORIA},
            headers=TENANT,
        )
        assert entrada.status_code == 200, entrada.text
        assert entrada.json()["papeis"] == ["admin"]
        assert entrada.json()["senha_expirada"] is True

        # senha provisória: autentica, não navega — e a saída do estado está aberta
        barrada = cliente.get("/api/v1/os", headers=TENANT)
        assert barrada.status_code == 403
        assert barrada.headers["x-erro-codigo"] == "senha_expirada"
        assert (
            cliente.post(
                "/api/v1/auth/trocar-senha",
                json={"senha_atual": ROOT_PROVISORIA, "senha_nova": ROOT_DEFINITIVA},
                headers=TENANT,
            ).status_code
            == 200
        )

        # tenant VAZIO: a lista responde 200 com [] (estado vazio, não erro) e a seed
        # de demonstração não está lá, apesar de `DEMO_MODE=true`
        vazia = cliente.get("/api/v1/os", headers=TENANT)
        assert vazia.status_code == 200 and vazia.json() == []

        criada = cliente.post(
            "/api/v1/os",
            json={"nome": "Primeira campanha do tenant", "tshirt": "M", "briefing": {}},
            headers=TENANT,
        )
        assert criada.status_code == 201, criada.text
        codigo = criada.json()["codigo"]
        assert codigo != OS_CODIGO_DEMO  # a numeração começa do zero neste tenant

        depois = cliente.get("/api/v1/os", headers=TENANT)
        assert [item["codigo"] for item in depois.json()] == [codigo]

        # e as telas de plataforma que a home consulta respondem em tenant novo
        assert cliente.get("/api/v1/policies", headers=TENANT).status_code == 200
        assert cliente.get("/api/v1/pedidos", headers=TENANT).status_code == 200
        assert cliente.get("/api/v1/auditoria", headers=TENANT).status_code == 200


# ------------------------------------------------- 5 · o `.env.example` como artefato
def test_env_example_nao_tem_comentario_ao_lado_de_variavel_vazia() -> None:
    """Guarda-corpo GENÉRICO da regra que já custou um admin publicado (onda 2).

    O `test_env_example_copiado_nao_cria_root` protege as DUAS variáveis do root. Esta
    protege o arquivo: em variável vazia o parser de `.env` adota o texto do comentário
    COMO VALOR, então `QUALQUER_COISA=  # explicação` é a mesma armadilha em outra
    chave. Varre o arquivo real — não uma cópia — porque o que se protege é o artefato
    que a linha 1 dele manda copiar.
    """
    caminho = RAIZ / ".env.example"
    assert caminho.is_file(), caminho

    infratoras: list[str] = []
    vazias: list[str] = []
    for numero, linha in enumerate(caminho.read_text(encoding="utf-8").splitlines(), start=1):
        if not linha.strip() or linha.lstrip().startswith("#") or "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        if valor.strip().startswith("#"):
            infratoras.append(f"linha {numero}: {linha.strip()}")
        elif not valor.strip():
            vazias.append(chave.strip())

    assert not infratoras, (
        "comentário ao lado de variável VAZIA vira VALOR (ver o topo do .env.example): "
        + "; ".join(infratoras)
    )

    # e o arquivo REAL, lido pelo `Settings`, entrega essas chaves realmente vazias
    lidas = Settings(_env_file=caminho)
    for chave in vazias:
        campo = chave.lower()
        if campo not in Settings.model_fields:
            continue  # variável de infra (ex.: JORNADA_PURGE_TOKEN) — não é campo do config
        valor_lido = getattr(lidas, campo)
        if isinstance(valor_lido, SecretStr):
            valor_lido = valor_lido.get_secret_value()
        assert valor_lido == "", f"{chave} não chegou vazia ao Settings: {valor_lido!r}"
