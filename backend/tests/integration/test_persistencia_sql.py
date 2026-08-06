"""A7 parte 1 — persistência PostgreSQL dos agregados core (@integration).

Prova o contrato de durabilidade: tudo que o `RepositorioSql` grava sobrevive a um
"restart" (engine/sessão NOVOS sobre o mesmo banco), com hidratação fiel dos tipos
(jsonb↔dict, text[], bytea, numeric, uuid, timestamptz) e seeds DEMO idempotentes
(upsert por uuid5 — §11.4/A15).
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from adapters.demo_seeds import OS_CODIGO_DEMO, semear_demo
from adapters.persistence.sql import RepositorioSql, criar_engine, criar_repositorio
from domain.campanha.modelos import OS, EventoDominio, Pendencia, SlaClock
from domain.esteira.modelos import EtapaWorkflow, HikeImportLog
from domain.intake.modelos import Pedido
from domain.validacao.modelos import DocumentoPortao, ThreadWarRoom, ValidacaoCampo

pytestmark = pytest.mark.integration

TENANT = "torre-movel"
AGORA = datetime(2026, 8, 5, 12, 0, 0, tzinfo=UTC)


def _repositorio_novo(url: str) -> RepositorioSql:
    """Engine NOVO — simula um restart do processo (nada em cache/na memória)."""
    return RepositorioSql(criar_engine(url))


def _os_exemplo(codigo: str = "OS-2026-9001") -> OS:
    return OS(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        codigo=codigo,
        nome="Campanha Integração",
        tshirt="M",
        fase="criada",
        briefing={"objetivo": "upsell 5G", "canais": ["email", "sms"], "verba": 120000.5},
        frozen=None,
        created_by=uuid.uuid4(),
        created_at=AGORA - timedelta(days=2),
        updated_at=AGORA,
    )


def test_os_pendencia_sla_sobrevivem_nova_sessao_e_engine(banco_limpo: str) -> None:
    repo1 = _repositorio_novo(banco_limpo)
    os_ = _os_exemplo()
    repo1.adicionar_os(os_)
    pendencia = Pendencia(
        id=uuid.uuid4(),
        os_id=os_.id,
        numero=repo1.proximo_numero_pendencia(os_.id),
        tipo="risk",
        titulo="Base sem opt-in confirmado",
        descricao="Aguardando evidência do DPO",
        severidade="alta",
        bloqueante=True,
        bloqueia_etapa="disparo",
        status="aberta",
        accountable=uuid.uuid4(),
        aceite=None,
        origem="hike",
        via_ai=False,
        created_at=AGORA,
    )
    repo1.adicionar_pendencia(pendencia)
    clock = SlaClock(
        id=uuid.uuid4(),
        os_id=os_.id,
        etapa="audiencia",
        prazo=AGORA + timedelta(days=5),
        estado="correndo",
        pausas=[{"de": AGORA.isoformat(), "ate": None, "motivo": "cliente"}],
    )
    repo1.adicionar_sla_clock(clock)
    repo1.adicionar_evento(
        EventoDominio(
            tenant_id=TENANT,
            type="pendencia.opened",
            payload={"numero": pendencia.numero},
            actor="analista",
            via_ai=False,
            created_at=AGORA,
            os_id=os_.id,
        )
    )

    # mutação + salvar (mesmo fluxo dos serviços: mutate → salvar_*)
    os_.fase = "avaliada"
    repo1.salvar_os(os_)
    pendencia.status = "resolvida"
    repo1.salvar_pendencia(pendencia)

    # "restart": engine/sessão NOVOS — nada pode depender da memória do repo1
    repo2 = _repositorio_novo(banco_limpo)
    recuperada = repo2.obter_os(TENANT, os_.id)
    assert recuperada is not None
    assert recuperada.fase == "avaliada"
    assert recuperada.briefing == os_.briefing  # jsonb hidratado 1:1
    assert recuperada.created_at == os_.created_at  # timestamptz preserva o instante
    assert repo2.obter_os_por_codigo("OS-2026-9001") is not None
    assert repo2.obter_os("outro-tenant", os_.id) is None  # escopo de tenant (§4)
    assert [o.id for o in repo2.listar_os(TENANT, limit=10, offset=0)] == [os_.id]

    pendencias = repo2.listar_pendencias(os_.id)
    assert [p.status for p in pendencias] == ["resolvida"]
    assert pendencias[0].aceite is None and pendencias[0].accountable == pendencia.accountable
    assert repo2.proximo_numero_pendencia(os_.id) == 2
    assert repo2.proximo_sequencial_os(2026) == 9002  # max+1 sobrevive a restart

    clocks = repo2.listar_sla_clocks(os_.id)
    assert len(clocks) == 1 and clocks[0].pausas[0]["motivo"] == "cliente"

    eventos = repo2.listar_eventos(os_id=os_.id, tipo="pendencia.opened")
    assert len(eventos) == 1 and eventos[0].id is not None  # id veio do identity


def test_pedido_crud_sobrevive_nova_sessao(banco_limpo: str) -> None:
    repo1 = _repositorio_novo(banco_limpo)
    pedido = Pedido(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        solicitante={"nome": "Ana", "email": "ana@claro.com.br"},
        conteudo={"objetivo": {"valor": "retenção pós-pago", "inferido": True}},
        completude=20.0,
        faltantes=["publico", "oferta", "verba", "janela"],
        estado="rascunho",
        os_id=None,
        created_at=AGORA,
        updated_at=AGORA,
    )
    repo1.adicionar_pedido(pedido)

    pedido.conteudo["verba"] = {"valor": 50000, "inferido": False}
    pedido.completude = 40.0
    pedido.faltantes = ["publico", "oferta", "janela"]
    pedido.updated_at = AGORA + timedelta(minutes=10)
    repo1.salvar_pedido(pedido)

    repo2 = _repositorio_novo(banco_limpo)
    recuperado = repo2.obter_pedido(TENANT, pedido.id)
    assert recuperado is not None
    assert recuperado.completude == 40.0  # numeric(4,1) → float
    assert recuperado.faltantes == ["publico", "oferta", "janela"]  # text[] → list
    assert recuperado.conteudo["verba"]["valor"] == 50000
    assert recuperado.estado == "rascunho" and recuperado.os_id is None
    assert repo2.obter_pedido("outro-tenant", pedido.id) is None

    outro = Pedido(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        solicitante={"nome": "Bia"},
        conteudo={},
        completude=0.0,
        faltantes=[],
        estado="rascunho",
        created_at=AGORA + timedelta(hours=1),
        updated_at=AGORA + timedelta(hours=1),
    )
    repo2.adicionar_pedido(outro)
    assert [p.id for p in repo2.listar_pedidos(TENANT)] == [outro.id, pedido.id]  # recente 1º


def test_esteira_validacao_warroom_e_documento_roundtrip(banco_limpo: str) -> None:
    repo1 = _repositorio_novo(banco_limpo)
    os_ = _os_exemplo("OS-2026-9002")
    repo1.adicionar_os(os_)
    repo1.adicionar_etapa(
        EtapaWorkflow(
            id=uuid.uuid4(),
            os_id=os_.id,
            ordem=2,
            nome="discovery",
            responsavel=None,
            sla_dias=3,
            estado="pendente",
            checklist=[{"item": "Kickoff", "feito": False, "por": None, "em": None}],
            dependencias=["briefing"],
            hike_ref={"card_id": "HK-1", "importado_em": AGORA.isoformat()},
        )
    )
    repo1.adicionar_etapa(
        EtapaWorkflow(
            id=uuid.uuid4(),
            os_id=os_.id,
            ordem=1,
            nome="briefing",
            responsavel=uuid.uuid4(),
            sla_dias=2,
            estado="concluida",
            checklist=[],
            dependencias=[],
            hike_ref=None,
        )
    )
    repo1.adicionar_hike_log(
        HikeImportLog(
            id=uuid.uuid4(),
            tenant_id=TENANT,
            os_id=os_.id,
            hike_card_id="HK-1",
            status="ok",
            detalhe={"etapas": 7},
            created_at=AGORA,
        )
    )
    repo1.adicionar_validacao(
        ValidacaoCampo(
            id=uuid.uuid4(),
            os_id=os_.id,
            campo="publico",
            veredito="ok",
            checagens=[{"tipo": "contagem", "ok": True, "detalhe": "847312"}],
            evidencia={"fonte": "data_cloud", "contagem": 847312},
            created_at=AGORA,
        )
    )
    repo1.adicionar_thread(
        ThreadWarRoom(
            id=uuid.uuid4(),
            os_id=os_.id,
            campo="verba",
            titulo="Verba diverge do tarifário",
            mensagens=[{"autor": "lider", "texto": "Confirmar com finanças", "em": "2026-08-05"}],
            status="aberta",
            created_at=AGORA,
        )
    )
    docx = b"PK\x03\x04conteudo-docx-fake"
    repo1.adicionar_documento(
        DocumentoPortao(
            id=uuid.uuid4(),
            os_id=os_.id,
            portao="go",
            nome_arquivo="go-OS-2026-9002.docx",
            conteudo=docx,
            hash="a" * 64,
            created_at=AGORA,
        )
    )

    repo2 = _repositorio_novo(banco_limpo)
    etapas = repo2.listar_etapas(os_.id)
    assert [e.nome for e in etapas] == ["briefing", "discovery"]  # ordenadas por `ordem`
    assert etapas[1].checklist[0]["item"] == "Kickoff"
    assert etapas[1].hike_ref is not None and etapas[1].hike_ref["card_id"] == "HK-1"

    logs = repo2.listar_hike_logs(TENANT)
    assert len(logs) == 1 and logs[0].detalhe == {"etapas": 7}

    validacoes = repo2.listar_validacoes(os_.id, campo="publico")
    assert len(validacoes) == 1 and validacoes[0].evidencia["contagem"] == 847312
    assert repo2.listar_validacoes(os_.id, campo="inexistente") == []

    threads = repo2.listar_threads(os_.id)
    assert len(threads) == 1 and threads[0].mensagens[0]["autor"] == "lider"

    documentos = repo2.listar_documentos(os_.id, portao="go")
    assert len(documentos) == 1
    assert documentos[0].conteudo == docx  # bytea → bytes idênticos
    assert isinstance(documentos[0].conteudo, bytes)


def test_seeds_demo_idempotentes_entre_restarts(banco_limpo: str) -> None:
    """§11.4/A15: dois "boots" com SQL — upsert por uuid5 não duplica linhas e a
    parte em memória (jornadas etc.) é re-semeada para o front demo funcionar."""
    for boot in range(2):
        repo = _repositorio_novo(banco_limpo)
        semear_demo(repo, tenant_id=TENANT, agora=AGORA + timedelta(hours=boot))
        os_demo = repo.obter_os_por_codigo(OS_CODIGO_DEMO)
        assert os_demo is not None
        assert len(repo.listar_etapas(os_demo.id)) == 7  # nunca 14 (upsert, não append)
        assert repo.listar_jornadas(os_demo.id)  # memória re-semeada no 2º boot
    assert len([o for o in repo.listar_os(TENANT, 100, 0) if o.codigo == OS_CODIGO_DEMO]) == 1


def test_criar_repositorio_seleciona_sql_quando_alcancavel(banco_limpo: str) -> None:
    repositorio = criar_repositorio(banco_limpo)
    assert isinstance(repositorio, RepositorioSql)
