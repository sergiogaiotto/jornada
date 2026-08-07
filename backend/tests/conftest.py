"""Fixtures compartilhadas — testes rodam via TestClient, SEM docker.

Os pings do /healthz são substituídos por dublê (`dependency_overrides`):

- `ping_db` simula a pré-condição do aceite M0-A1 ("dado compose up" → db saudável);
- `ping_llm` é guarda-corpo de §1.3.5. O ping REAL só devolve "skip" sem tocar a rede
  quando `APP_ENV=dev`; fora de dev ele abre um `httpx` contra `hub-gpus.claro.com.br`.
  Desde que a suíte roda TAMBÉM em `APP_ENV=prod` (frente 3), sem este dublê todo
  `GET /healthz` de teste viraria uma chamada de rede ao hub da Claro — exatamente o
  que o §1.3.5 proíbe, e uma dependência de rede num gate que precisa ser hermético.

Guarda-corpos de LLM/observabilidade (§1.3.5, §10.8): todo app de teste nasce com
`state.llm = LLMFake()` e `state.embedding = EmbeddingFake()` (o hub real NUNCA é
chamado em teste — testes que precisam de resposta específica trocam o fake) e
`state.tracer` = Langfuse DESABILITADO (LANGFUSE_ENABLED=false → no-op absoluto,
nenhuma rede).

A CREDENCIAL DOS ACEITES — por que o `client` deixou de mandar `Bearer dev-<papel>`
-----------------------------------------------------------------------------------
A auditoria da frente 3 mediu o buraco: a suíte inteira rodava em `APP_ENV=dev` e, em
`APP_ENV=prod`, ~200 aceites caíam em 401 — todos pela MESMA causa, o token estático
`dev-<papel>`, que em prod não existe e não deve existir (§10.3, `tokens_dev_ativos`).
O modo em que a PII real vai rodar tinha cobertura ZERO.

Consertar isso trocando `prod` por `dev` seria fraudar o gate. O caminho é o contrário:
os aceites param de depender de uma credencial que só existe em dev e passam a usar a
credencial que existe nos DOIS modos — a SESSÃO por cookie que o G01 entregou.

`ClienteJornada` faz essa tradução DO LADO DO CLIENTE (nunca do lado da aplicação):
o teste continua escrevendo `Authorization: Bearer dev-analista` — que é a forma como
ele DECLARA "quem sou eu neste request" —, e o cliente materializa esse portador como
conta + sessão de verdade no repositório do app, mandando o cookie no lugar do header.
A aplicação recebe só o cookie: nenhuma linha de produção afrouxa, e o mesmo aceite
prova a mesma regra de negócio em dev e em prod.

Três consequências desenhadas de propósito:

1. **O `DEV_TOKENS` vira o catálogo de identidades de teste, não uma credencial.** Quem
   monkeypatcha o dicionário (ex.: `tokens_outro_tenant`) continua funcionando sem
   saber da tradução — a fixture descreve um portador, e o cliente o materializa.
2. **A tradução é INCONDICIONAL (dev e prod).** Ter dois caminhos por ambiente seria
   ter dois comportamentos e um deles sem cobertura — que é o problema de origem. Um
   caminho só, exercitado nos dois modos.
3. **Só o `Bearer <token>` CANÔNICO é traduzido.** As variantes malformadas do aceite
   E05-A8 (esquema minúsculo, tab, dois espaços, sobra no fim) seguem intactas até a
   aplicação: é ela que tem de recusá-las, e é isso que aquele aceite mede.

Quem precisa medir o portador BEARER em si — os aceites que provam que `dev-admin`
morre fora de dev — usa `client_bearer`, o cliente CRU, sem tradução nenhuma.
"""

import re
import secrets
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from functools import lru_cache
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from adapters.embedding.fake import EmbeddingFake
from adapters.llm.fake import LLMFake
from adapters.observabilidade.langfuse import TracerLangfuse
from app.auth import DEV_TOKENS, PORTAL_TOKENS, Usuario, nome_cookie_sessao, servico_identidade
from app.config import Settings
from app.main import create_app, ping_db, ping_llm
from application.services.identidade_service import ServicoIdentidade
from domain.identidade import senha as regras_senha
from domain.identidade.modelos import ContaUsuario


@pytest.fixture(autouse=True)
def _persistencia_em_memoria(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guarda-corpo A7: fora dos testes @integration, `create_app` NUNCA seleciona os
    repos SQL — mesmo se o dev estiver com docker de pé e DATABASE_URL exportado, os
    aceites M0–M12 valem sobre repositório em memória isolado (sem estado entre runs)."""
    if "integration" in request.keywords:
        return
    monkeypatch.delenv("DATABASE_URL", raising=False)


@pytest.fixture()
def app() -> FastAPI:
    # demo=False: os aceites M0–M12 valem sobre repositório VAZIO (as seeds §11.4 são
    # cobertas por tests/acceptance/test_seeds_demo.py com create_app(demo=True)).
    application = create_app(demo=False)
    application.dependency_overrides[ping_db] = lambda: "ok"  # dublê: compose up / db saudável
    application.dependency_overrides[ping_llm] = lambda: "skip"  # §1.3.5: zero rede (ver módulo)
    application.state.llm = LLMFake()  # §1.3.5: hub real jamais em teste
    application.state.embedding = EmbeddingFake()  # §1.3.5 idem para embeddings (A11)
    application.state.tracer = TracerLangfuse(  # §10.8: LANGFUSE_ENABLED=false em teste
        Settings(_env_file=None, langfuse_enabled=False)
    )
    # O catálogo de identidades (§8-M0/M3) vira CONTA de verdade — ver `_semear_roster`.
    # Repositório "vazio" acima quer dizer sem OS/jornada/evento: PESSOAS o tenant tem,
    # senão nenhum aceite teria a quem endereçar uma aprovação.
    _semear_roster(application)
    return application


# --------------------------------------------------------------- portador → sessão real
# `Bearer <token>` e nada mais: UM espaço, esquema com a grafia exata, sem sobra. Ver a
# consequência (3) no cabeçalho do módulo — o E05-A8 depende de as variantes malformadas
# chegarem à aplicação exatamente como o teste as escreveu.
_BEARER_CANONICO = re.compile(r"^Bearer (\S+)$")


@lru_cache(maxsize=1)
def _hash_de_fixture() -> str:
    """UM argon2 por sessão de pytest, sobre um segredo sorteado em tempo de execução.

    Duas decisões aqui, e as duas importam:

    · **Sorteado, não literal.** Nenhuma senha de fixture entra no repositório — nem
      como exemplo. Como consequência natural, nenhuma conta criada por este módulo
      consegue fazer login por senha, nem por acidente: o segredo morre com o processo.
    · **Um só, memoizado.** `gerar_hash` é argon2id (caro por construção). Uma conta de
      fixture por identidade por app, em ~700 testes, custaria minutos de gate para
      hash nenhum ser conferido — nenhuma fixture autentica por senha, todas por sessão.
    """
    return regras_senha.gerar_hash(secrets.token_urlsafe(32))


def _agora(app: FastAPI) -> datetime:
    """Relógio do app (§2.1) quando o teste fixou um; senão, o do sistema."""
    relogio = getattr(app.state, "relogio", None)
    return relogio.agora() if relogio is not None else datetime.now(UTC)


def _servico(app: FastAPI) -> ServicoIdentidade:
    """Serviço de identidade do app, montado como as rotas o montam.

    `servico_identidade` só toca `request.app.state`; passar o app embrulhado mantém UMA
    fonte da verdade (mesmo relógio §2.1, mesmo TTL, mesmo repositório) em vez de uma
    segunda cópia da montagem que envelheceria à parte da de produção.
    """
    return servico_identidade(cast(Request, SimpleNamespace(app=app)))


def _sessao_viva(app: FastAPI, token: str) -> bool:
    """A sessão ainda autentica? (leitura pura — `resolver_sessao` não muta nada)."""
    return _servico(app).resolver_sessao(token) is not None


def _conta_persistida(app: FastAPI, portador: Usuario) -> ContaUsuario:
    """Garante `portador` como CONTA no repositório do app (idempotente).

    A conta é escrita DIRETO no repositório em vez de passar por
    `ServicoIdentidade.criar_usuario` de propósito: aquele caminho valida política de
    senha, marca `senha_expirada=True` (o portador não navegaria) e emite `usuario.created`
    no outbox §2.3 — três efeitos que poluiriam os aceites de trilha.
    """
    repositorio = app.state.repositorio_os
    conta = repositorio.obter_usuario(portador.id)
    if conta is None:
        conta = ContaUsuario(
            id=portador.id,
            tenant_id=portador.tenant_id,
            email=portador.email,
            nome=portador.nome,
            senha_hash=_hash_de_fixture(),
            papeis=list(portador.papeis),
            ativo=True,
            senha_expirada=False,  # fixture é conta já "onboardada": autentica E navega
            criado_em=_agora(app),
        )
        repositorio.adicionar_usuario(conta)
    return conta


def _semear_roster(app: FastAPI) -> None:
    """O catálogo de identidades de teste existe como CONTA — não só como token.

    Segundo eixo do mesmo buraco da frente 3, e o que sobrou depois que o `client` passou
    a autenticar por sessão. Não basta o portador do REQUEST existir em prod: os aceites
    também NOMEIAM terceiros que nunca fazem request nenhum. O caso é o link mágico —
    `POST /snapshots/{id}/link-magico` endereça o pacote a `aprovador@dev.jornada.local`
    e o serviço confere os papéis do destinatário contra a faixa de alçada (§11.4, E03).

    Quem respondia essa consulta em dev era `api/v1/portoes.py::_papeis_no_roster`, que
    cai no dicionário `DEV_TOKENS` quando `tokens_dev_ativos()`. Em prod essa perna não
    roda — e não deve rodar —, o destinatário passava por "não é usuário do sistema" e o
    link nascia 409. Efeito medido: 26 aceites de M8/M9/M10 (segregação criador≠aprovador,
    alçada, apply, rampa) verdes em dev e vermelhos em prod, sem que uma linha de regra de
    negócio tivesse mudado.

    Semear o catálogo INTEIRO — e só ele — mantém os dois lados honestos:

    · quem está no catálogo tem conta de verdade, com os MESMOS papéis do portador, então
      a consulta de alçada é respondida pelo caminho de produção (o repositório) nos dois
      modos, e não pelo atalho de dev;
    · quem NÃO está segue sem conta, que é exatamente o que os aceites E03 medem —
      `diretor.cliente@claro.com.br` continua "de fora" (409) e `aprovador+qa@…` continua
      sendo uma conta que só existe porque o teste a criou pela rota de admin.

    Incondicional (dev e prod), pela mesma razão da tradução de credencial acima: dois
    caminhos por ambiente seriam dois comportamentos, um deles sem cobertura.
    """
    for portador in (*DEV_TOKENS.values(), *PORTAL_TOKENS.values()):
        _conta_persistida(app, portador)


def _abrir_sessao_real(app: FastAPI, portador: Usuario) -> str:
    """Conta persistida + SESSÃO viva; devolve o token do cookie.

    A SESSÃO é aberta pelo serviço de verdade (`abrir_sessao`), porque é ela que a
    aplicação vai conferir a cada request.
    """
    return _servico(app).abrir_sessao(_conta_persistida(app, portador))


class ClienteJornada(TestClient):
    """TestClient que troca o `Bearer dev-<papel>` das fixtures por SESSÃO REAL.

    Ver o cabeçalho do módulo para o porquê. Aqui fica só a mecânica: um token
    reconhecido em `DEV_TOKENS`/`PORTAL_TOKENS` (lidos a cada request, para que o
    monkeypatch das fixtures continue valendo) vira uma sessão, reaproveitada enquanto
    o cliente viver — abrir uma sessão nova por request encheria o repositório de linhas
    que aceite nenhum pediu.

    O cookie viaja como `cookies=` do request (prioridade sobre o jar do cliente, por
    contrato do httpx) e o header `Authorization` é REMOVIDO: a aplicação precisa ver
    exatamente o que veria em produção — cookie, e só.

    A sessão em cache é CONFERIDA antes de cada uso, e reaberta se não valer mais. Não é
    zelo: vários aceites manipulam o `ClockPort` do app (§2.1) para provar janela de
    experimento, expiração e desbloqueio — o M11-A1 empurra o relógio 14 dias à frente e
    a sessão aberta com o relógio anterior morre no meio do teste. Uma credencial que
    expira sozinha no meio de um aceite de OUTRO assunto vira 401 misterioso.
    """

    def __init__(self, app: FastAPI, **kwargs: Any) -> None:
        super().__init__(app, **kwargs)
        self._app_jornada = app
        self._sessoes: dict[str, str] = {}

    def _portador_declarado(self, headers: Any) -> tuple[list[tuple[str, str]], str] | None:
        if not headers:
            return None
        itens: list[tuple[str, str]] = list(
            headers.items() if hasattr(headers, "items") else headers
        )
        autorizacao = next((v for k, v in itens if k.lower() == "authorization"), None)
        if autorizacao is None:
            return None
        casamento = _BEARER_CANONICO.match(autorizacao)
        if casamento is None:
            return None
        rotulo = casamento.group(1)
        portador = DEV_TOKENS.get(rotulo) or PORTAL_TOKENS.get(rotulo)
        if portador is None:  # token desconhecido segue intacto → a rota responde 401
            return None
        token = self._sessoes.get(rotulo)
        if token is None or not _sessao_viva(self._app_jornada, token):
            token = _abrir_sessao_real(self._app_jornada, portador)
            self._sessoes[rotulo] = token
        return [(k, v) for k, v in itens if k.lower() != "authorization"], token

    def request(self, method: str, url: Any, **kwargs: Any) -> Any:  # type: ignore[override]
        declarado = self._portador_declarado(kwargs.get("headers"))
        if declarado is not None:
            kwargs["headers"], token = declarado
            kwargs["cookies"] = dict(kwargs.get("cookies") or {}) | {nome_cookie_sessao(): token}
        return super().request(method, url, **kwargs)


@pytest.fixture()
def client(app: FastAPI) -> Iterator[ClienteJornada]:
    with ClienteJornada(app, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture()
def client_bearer(app: FastAPI) -> Iterator[TestClient]:
    """Cliente CRU — o `Authorization` chega à aplicação como o teste escreveu.

    Só para os aceites que medem o PORTADOR BEARER em si (o `dev-<papel>` recusado fora
    de dev, §10.3/UAT #5). Todo o resto usa `client`: aceite de regra de negócio não deve
    depender de uma credencial que produção não tem.
    """
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture()
def ambiente_sem_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Apaga do processo TODA variável que o `Settings` lê (§3.1).

    `Settings(_env_file=None)` NÃO é hermético e nunca foi: `_env_file=None` desliga só
    o ARQUIVO — `os.environ` continua sendo fonte, por desenho do pydantic-settings. Com
    a suíte rodando também em `APP_ENV=prod` (frente 3), os testes que afirmam DEFAULTS
    passaram a medir o ambiente do processo em vez do default do código, e o fail-fast
    do §10.3 deixou de falhar porque o `APP_SECRET` do ambiente já era ≠ do default.
    Derivado de `model_fields` para não envelhecer a cada variável nova.
    """
    for nome in Settings.model_fields:
        monkeypatch.delenv(nome.upper(), raising=False)


TENANT_ALHEIO = "outra-torre"


@pytest.fixture()
def tokens_outro_tenant(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Segunda identidade REAL (achado 5/UAT5): portadores de dev e de portal de `outra-torre`.

    Os portadores seed (§8) são todos de `torre-movel`. Desde que o `X-Tenant` é conferido
    contra o portador (o header é asserção, não fonte da verdade), provar isolamento
    exige um USUÁRIO do outro tenant — forjar o header é exatamente o que o fix proíbe.
    Devolve `{"pleno": ..., "portal": ...}`."""
    pleno, portal = "dev-analista-outra-torre", "portal-outra-torre"
    monkeypatch.setitem(
        DEV_TOKENS,
        pleno,
        Usuario(
            id=uuid.uuid5(uuid.NAMESPACE_URL, "jornada/dev/analista/outra-torre"),
            tenant_id=TENANT_ALHEIO,
            nome="Dev Analista (outra torre)",
            email="analista@outra-torre.local",
            papeis=("analista",),
        ),
    )
    monkeypatch.setitem(
        PORTAL_TOKENS,
        portal,
        Usuario(
            id=uuid.uuid5(uuid.NAMESPACE_URL, "jornada/portal/outra-torre"),
            tenant_id=TENANT_ALHEIO,
            nome="Solicitante (Portal, outra torre)",
            email="portal@outra-torre.local",
            papeis=("solicitante",),
        ),
    )
    return {"pleno": pleno, "portal": portal}
