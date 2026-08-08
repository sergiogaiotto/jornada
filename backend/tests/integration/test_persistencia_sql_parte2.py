"""A7 parte 2 — persistência PostgreSQL do restante dos agregados (@integration).

Prova o contrato de durabilidade com "restart" real (engine/sessão NOVOS sobre o
mesmo banco): twin com versões + restaurar, snapshot/aprovação, ledger `invocacao`
(FK para `agente` — roster semeado antes), launch + telemetria (identity),
segmento/certificado (last_mile via `salvar_certificado`), criativo (células
dataclass ↔ jsonb), compilador (sync_run/registry/drift/preflight) e otimização/
Ateliê/política. Ordenações "o último é o corrente" usam o `created_at` que SÓ o
banco escreve (migração 0012).
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from adapters.atelie_seeds import semear_atelie, semear_politicas
from adapters.persistence.sql import RepositorioSql, criar_engine
from domain.agentes.modelos import Invocacao, agente_uuid
from domain.audiencia.modelos import CertificadoElegibilidade, Segmento
from domain.campanha.modelos import OS
from domain.criativo.modelos import CelulaCriativo, Criativo
from domain.experimento.modelos import Experimento
from domain.governanca.modelos import Aprovacao, Snapshot
from domain.jornada.modelos import (
    DriftCheck,
    JornadaVersao,
    PreflightRun,
    ResourceRegistry,
    SyncRun,
)
from domain.lancamento.modelos import Incidente, Launch, TelemetryEvent
from domain.otimizacao.modelos import Aprendizado, CalibracaoPrior, PropostaOtimizacao

pytestmark = pytest.mark.integration

TENANT = "torre-movel"
AGORA = datetime(2026, 8, 5, 12, 0, 0, tzinfo=UTC)


def _repositorio_novo(url: str) -> RepositorioSql:
    """Engine NOVO — simula um restart do processo (nada em cache/na memória)."""
    return RepositorioSql(criar_engine(url))


def _os_exemplo(codigo: str) -> OS:
    return OS(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        codigo=codigo,
        nome="Campanha Integração P2",
        tshirt="M",
        fase="criada",
        briefing={"objetivo": "retenção"},
        frozen=None,
        created_by=uuid.uuid4(),
        created_at=AGORA - timedelta(days=1),
        updated_at=AGORA,
    )


def _grafo(rotulo: str) -> dict:
    return {
        "meta": {"nome": rotulo, "reentrada": "nao"},
        "nodes": [{"id": "n1", "tipo": "entrada"}],
        "edges": [],
    }


def test_twin_versoes_e_restaurar_sobrevivem_reengine(banco_limpo: str) -> None:
    """O fluxo do M7 (nova versão → editar → restaurar = NOVA versão com o grafo da
    antiga) persiste inteiro: versões ordenadas, hash/simulacao/previsto hidratados
    e `proxima_versao` = max+1 mesmo depois de um restart."""
    repo1 = _repositorio_novo(banco_limpo)
    os_ = _os_exemplo("OS-2026-9101")
    repo1.adicionar_os(os_)

    v1 = JornadaVersao(
        id=uuid.uuid4(),
        os_id=os_.id,
        versao=repo1.proxima_versao(os_.id),
        grafo=_grafo("v1"),
        hash="a" * 64,
        estado="rascunho",
        premissas=["custo tabela 2026"],
        custo_projetado=1234.56,
        created_at=AGORA,
    )
    repo1.adicionar_jornada(v1)
    v2 = JornadaVersao(
        id=uuid.uuid4(),
        os_id=os_.id,
        versao=repo1.proxima_versao(os_.id),
        grafo=_grafo("v2"),
        hash="b" * 64,
        estado="simulado",
        simulacao={"semaforo": "verde", "p50": {"conversoes": 812}},
        previsto={"conversoes": [700, 812, 930]},
        created_at=AGORA + timedelta(minutes=5),
    )
    repo1.adicionar_jornada(v2)

    # "restart" 1: restaurar v1 → NOVA versão v3 com o grafo da v1 (contrato M7)
    repo2 = _repositorio_novo(banco_limpo)
    alvo = repo2.obter_jornada(v1.id)
    assert alvo is not None and alvo.grafo == _grafo("v1")
    v3 = JornadaVersao(
        id=uuid.uuid4(),
        os_id=os_.id,
        versao=repo2.proxima_versao(os_.id),
        grafo=dict(alvo.grafo),
        hash=alvo.hash,
        estado="rascunho",
        created_at=AGORA + timedelta(minutes=10),
    )
    repo2.adicionar_jornada(v3)
    assert v3.versao == 3  # max+1 veio do banco, não de contador em memória

    # "restart" 2: tudo hidratado 1:1
    repo3 = _repositorio_novo(banco_limpo)
    versoes = repo3.listar_jornadas(os_.id)
    assert [j.versao for j in versoes] == [1, 2, 3]
    assert versoes[1].simulacao == v2.simulacao and versoes[1].previsto == v2.previsto
    assert versoes[0].custo_projetado == 1234.56  # numeric(12,2) → float
    assert versoes[2].grafo == _grafo("v1") and versoes[2].hash == "a" * 64
    assert repo3.proxima_versao(os_.id) == 4

    # mutação + salvar (mesmo fluxo dos serviços)
    versoes[2].estado = "aprovado"
    repo3.salvar_jornada(versoes[2])
    assert repo3.obter_jornada(v3.id).estado == "aprovado"  # type: ignore[union-attr]


def test_ledger_invocacao_persiste_com_roster(banco_limpo: str) -> None:
    """O ledger via_ai (LGPD Art. 20) sobrevive a restart: FK `agente` satisfeita
    pelo roster do Ateliê (ids uuid5 = `agente_uuid(nome)` dos serviços)."""
    repo1 = _repositorio_novo(banco_limpo)
    semear_atelie(repo1, tenant_id=TENANT, agora=AGORA)
    invocacao = Invocacao(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        os_id=None,
        agente_id=agente_uuid("consultor"),
        skill_versao="1.0",
        usuario_portador=uuid.uuid4(),
        input={"mensagem": "quero campanha 5G"},
        output={"resposta": "ok", "inferencias": {"objetivo": "upsell"}},
        evidencias=["chunk-1", "chunk-2"],
        judge={"score": 96, "dimensoes": {"correcao": 98}},
        tokens=321,
        latencia_ms=875,
        created_at=AGORA,
    )
    repo1.adicionar_invocacao(invocacao)

    repo2 = _repositorio_novo(banco_limpo)
    do_tenant = repo2.listar_invocacoes(TENANT)
    assert [i.id for i in do_tenant] == [invocacao.id]
    recuperada = repo2.obter_invocacao(invocacao.id)
    assert recuperada is not None
    assert recuperada.agente_id == agente_uuid("consultor")
    assert recuperada.evidencias == ["chunk-1", "chunk-2"]
    assert recuperada.judge == invocacao.judge and recuperada.tokens == 321
    assert repo2.listar_invocacoes("outro-tenant") == []
    # roster + skills publicadas também sobreviveram (GO congela do banco — §8-M4)
    assert repo2.obter_agente_por_nome("consultor") is not None
    assert repo2.versoes_skills_publicadas().get("consultor") == "1.0"


def test_launch_telemetria_e_incidente_sobrevivem_reengine(banco_limpo: str) -> None:
    repo1 = _repositorio_novo(banco_limpo)
    os_ = _os_exemplo("OS-2026-9102")
    repo1.adicionar_os(os_)
    snapshot = Snapshot(
        id=uuid.uuid4(),
        os_id=os_.id,
        hash="c" * 64,
        conteudo={"jgc": {"nodes": []}},
        previsto={"conversoes": [1, 2, 3]},
        created_at=AGORA,
    )
    repo1.adicionar_snapshot(snapshot)
    launch = Launch(
        id=uuid.uuid4(),
        snapshot_id=snapshot.id,
        breakers={"optout_max_pct": 0.5},
        eventos=[{"tipo": "armado", "em": AGORA.isoformat(), "marco_telemetria": 0}],
    )
    repo1.adicionar_launch(launch)
    for indice, tipo in enumerate(("sent", "delivered", "open")):
        repo1.adicionar_telemetria(
            TelemetryEvent(
                tenant_id=TENANT,
                tipo=tipo,
                ts=AGORA + timedelta(minutes=indice),
                os_id=os_.id,
                no_jgc="n1",
                canal="email",
                contato_hash="d" * 64,
                fonte="ens",
                payload={"onda": 1},
            )
        )
    marco = repo1.maior_id_telemetria()
    assert marco >= 3  # identity do banco atribuiu ids crescentes

    # rampa avança + breaker dispara → mutação + salvar
    launch.estado = "em_rampa"
    launch.onda_atual = 1
    launch.eventos.append({"tipo": "onda_iniciada", "onda": 1})
    repo1.salvar_launch(launch)
    repo1.adicionar_incidente(
        Incidente(
            id=uuid.uuid4(),
            os_id=os_.id,
            launch_id=launch.id,
            sev="sev2",
            tipo="optout",
            titulo="Breaker de optout disparou",
            meta={"valor": 0.9, "limite": 0.5},
            aberto_em=AGORA + timedelta(minutes=10),
        )
    )

    repo2 = _repositorio_novo(banco_limpo)
    launches = repo2.listar_launches(snapshot.id)
    assert len(launches) == 1
    recuperado = launches[-1]  # "o último é o corrente" (_launch_de_referencia)
    assert recuperado.estado == "em_rampa" and recuperado.onda_atual == 1
    assert recuperado.ondas == [{"pct": 1}, {"pct": 10}, {"pct": 100}]
    assert [e["tipo"] for e in recuperado.eventos] == ["armado", "onda_iniciada"]
    assert recuperado.breakers == {"optout_max_pct": 0.5}

    telemetria = repo2.listar_telemetria(os_.id)
    assert [e.tipo for e in telemetria] == ["sent", "delivered", "open"]
    assert repo2.listar_telemetria(os_.id, apos_id=telemetria[1].id) == telemetria[2:]
    assert repo2.maior_id_telemetria() == marco

    abertos = repo2.listar_incidentes(launch_id=launch.id, estado="aberto")
    assert len(abertos) == 1 and abertos[0].meta == {"valor": 0.9, "limite": 0.5}


def test_snapshot_aprovacao_segmento_certificado_criativo(banco_limpo: str) -> None:
    repo1 = _repositorio_novo(banco_limpo)
    os_ = _os_exemplo("OS-2026-9103")
    repo1.adicionar_os(os_)
    snapshot = Snapshot(
        id=uuid.uuid4(),
        os_id=os_.id,
        hash="e" * 64,
        conteudo={"custo": 1000.0},
        previsto=None,
        created_at=AGORA,
    )
    repo1.adicionar_snapshot(snapshot)
    aprovacao = Aprovacao(
        id=uuid.uuid4(),
        snapshot_id=snapshot.id,
        token_hash="f" * 64,
        expira_em=AGORA + timedelta(hours=72),
        alcada="head_crm",
    )
    repo1.adicionar_aprovacao(aprovacao)
    segmento = Segmento(
        id=uuid.uuid4(),
        os_id=os_.id,
        origem="estudio_sql",
        sql_publico="select 1",
        contagem_bruta=1000,
        contagem_liquida=900,
        waterfall=[{"etapa": "optout", "corte": 100, "restante": 900}],
        volume_abordagem={"email": {"n": 810, "pct": 90.0}},
        holdout_pct=12.5,
    )
    repo1.adicionar_segmento(segmento)
    certificado = CertificadoElegibilidade(
        id=uuid.uuid4(),
        os_id=os_.id,
        hash="1" * 64,
        suprimidos={"optout": 80, "blacklist": 20},
        liquido=900,
        emitido_em=AGORA,
        valido_ate=AGORA + timedelta(days=7),
        # §8-M5-A5: contagens de seed/fixture — nunca medidas executando o SQL
        contagens_derivadas_do_sql=False,
    )
    repo1.adicionar_certificado(certificado)
    criativo = Criativo(
        id=uuid.uuid4(),
        os_id=os_.id,
        kv_master={"conceito": "5G sem limites"},
        celulas=[
            CelulaCriativo(canal="email", variante="A", conteudo={"assunto": "Oi"}),
            CelulaCriativo(
                canal="sms",
                variante="B",
                conteudo={"mensagem": "Oferta 5G"},
                estado="aprovado",
                aprovada_por=uuid.uuid4(),
                aprovada_em=AGORA,
                observacao="ok",
            ),
        ],
        created_at=AGORA,
        updated_at=AGORA,
    )
    repo1.adicionar_criativo(criativo)
    experimento = Experimento(
        id=uuid.uuid4(),
        os_id=os_.id,
        holdout_pct=10.0,
        n_minimo=8000,
        mde_pp=1.5,
        janela_dias=14,
        metricas={"primaria": "conversao"},
        travado_em=AGORA,
    )
    repo1.adicionar_experimento(experimento)

    # "restart": decisão do link + last-mile no certificado (salvar_certificado)
    repo2 = _repositorio_novo(banco_limpo)
    link = repo2.obter_aprovacao_por_token_hash("f" * 64)
    assert link is not None and link.decisao is None
    link.decisao = "aprovado"
    link.decidido_em = AGORA + timedelta(hours=1)
    link.decidido_meta = {"ip": "10.0.0.1"}
    repo2.salvar_aprovacao(link)
    cert = repo2.listar_certificados(os_.id)[-1]
    cert.last_mile = {"status": "pass", "varrido_em": AGORA.isoformat()}
    repo2.salvar_certificado(cert)

    # recontagem cria um SEGUNDO segmento — "o último é o corrente" deve valer
    # após restart (ordem de inserção durável via created_at do banco — 0012)
    recontagem = Segmento(
        id=uuid.uuid4(),
        os_id=os_.id,
        origem="estudio_sql",
        sql_publico="select 2",
        contagem_liquida=870,
        holdout_pct=12.5,
    )
    repo2.adicionar_segmento(recontagem)

    repo3 = _repositorio_novo(banco_limpo)
    assert repo3.obter_snapshot_por_hash("e" * 64) is not None
    assert [s.id for s in repo3.listar_snapshots(os_.id)] == [snapshot.id]
    decidida = repo3.listar_aprovacoes(snapshot.id)[-1]
    assert decidida.decisao == "aprovado" and decidida.decidido_meta == {"ip": "10.0.0.1"}
    segmentos = repo3.listar_segmentos(os_.id)
    assert [s.id for s in segmentos] == [segmento.id, recontagem.id]
    ultimo_segmento = segmentos[-1]
    assert ultimo_segmento.contagem_liquida == 870
    assert ultimo_segmento.holdout_pct == 12.5  # numeric(4,1) → float
    assert segmentos[0].waterfall[0]["corte"] == 100
    assert segmentos[0].volume_abordagem["email"]["n"] == 810
    assert repo3.listar_certificados(os_.id)[-1].last_mile == {
        "status": "pass",
        "varrido_em": AGORA.isoformat(),
    }
    matriz = repo3.obter_criativo(criativo.id)
    assert matriz is not None and len(matriz.celulas) == 2
    aprovada = matriz.celulas[1]
    assert isinstance(aprovada, CelulaCriativo) and aprovada.estado == "aprovado"
    assert aprovada.aprovada_em == AGORA  # isoformat ↔ datetime round-trip
    corrente = repo3.experimento_da_os(os_.id)
    assert corrente is not None and corrente.mde_pp == 1.5 and corrente.travado_em == AGORA


def test_compilador_sync_registry_drift_preflight(banco_limpo: str) -> None:
    repo1 = _repositorio_novo(banco_limpo)
    os_ = _os_exemplo("OS-2026-9104")
    repo1.adicionar_os(os_)
    snapshot = Snapshot(
        id=uuid.uuid4(), os_id=os_.id, hash="2" * 64, conteudo={}, previsto=None, created_at=AGORA
    )
    repo1.adicionar_snapshot(snapshot)
    plan = SyncRun(
        id=uuid.uuid4(),
        snapshot_id=snapshot.id,
        ambiente="homolog",
        fase="plan",
        plano=[{"recurso": "de_entrada", "acao": "criar"}],
        estado="ok",
        created_at=AGORA,
    )
    repo1.adicionar_sync_run(plan)
    aplicacao = SyncRun(
        id=uuid.uuid4(),
        snapshot_id=snapshot.id,
        ambiente="homolog",
        fase="apply",
        resultado={"mutacoes": 3},
        estado="ok",
        api_calls=7,
        created_at=AGORA + timedelta(minutes=1),
    )
    repo1.adicionar_sync_run(aplicacao)
    registro = ResourceRegistry(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        no_jgc="n1",
        tipo_sfmc="dataExtension",
        external_key="jornada-de-entrada",
        sfmc_id="DE-1",
        ambiente="homolog",
        snapshot_hash="2" * 64,
    )
    repo1.upsert_registro(registro)
    # upsert pela unique(tenant, ambiente, external_key): atualiza, não duplica
    repo1.upsert_registro(
        ResourceRegistry(
            id=uuid.uuid4(),
            tenant_id=TENANT,
            no_jgc="n1",
            tipo_sfmc="dataExtension",
            external_key="jornada-de-entrada",
            sfmc_id="DE-2",
            ambiente="homolog",
            snapshot_hash="2" * 64,
        )
    )
    repo1.adicionar_drift_check(
        DriftCheck(
            id=uuid.uuid4(),
            snapshot_id=snapshot.id,
            recurso="jornada-de-entrada",
            estado="drift_sfmc",
            diff={"campos": {"assunto": {"twin": "A", "sfmc": "B"}}},
            checked_at=AGORA,
        )
    )
    repo1.adicionar_preflight(
        PreflightRun(
            id=uuid.uuid4(),
            snapshot_id=snapshot.id,
            ambiente="prod",
            resultado="amarelo",
            itens=[{"item": "des_schema", "status": "warn"}],
            created_at=AGORA,
        )
    )

    repo2 = _repositorio_novo(banco_limpo)
    runs = repo2.listar_sync_runs(snapshot.id, ambiente="homolog")
    assert [r.fase for r in runs] == ["plan", "apply"]
    assert runs[-1].api_calls == 7 and runs[0].plano[0]["acao"] == "criar"  # type: ignore[index]
    assert repo2.listar_sync_runs(snapshot.id, fase="apply")[-1].resultado == {"mutacoes": 3}
    vinculo = repo2.obter_registro(TENANT, "homolog", "jornada-de-entrada")
    assert vinculo is not None and vinculo.sfmc_id == "DE-2"
    assert len(repo2.listar_registros(TENANT, "homolog")) == 1  # upsert, não append
    repo2.remover_registro(TENANT, "homolog", "jornada-de-entrada")
    assert repo2.obter_registro(TENANT, "homolog", "jornada-de-entrada") is None

    check = repo2.listar_drift_checks(snapshot.id)[-1]
    assert check.estado == "drift_sfmc" and check.resolucao is None
    check.resolucao = "adopt"
    repo2.salvar_drift_check(check)
    repo3 = _repositorio_novo(banco_limpo)
    assert repo3.obter_drift_check(check.id).resolucao == "adopt"  # type: ignore[union-attr]
    prevoos = repo3.listar_preflights(snapshot.id, ambiente="prod")
    assert len(prevoos) == 1 and prevoos[0].resultado == "amarelo"


def test_otimizacao_aprendizado_calibracao_e_policy(banco_limpo: str) -> None:
    repo1 = _repositorio_novo(banco_limpo)
    semear_politicas(repo1, tenant_id=TENANT, agora=AGORA)
    os_ = _os_exemplo("OS-2026-9105")
    repo1.adicionar_os(os_)
    base = JornadaVersao(
        id=uuid.uuid4(),
        os_id=os_.id,
        versao=1,
        grafo=_grafo("base"),
        hash="3" * 64,
        created_at=AGORA,
    )
    repo1.adicionar_jornada(base)
    proposta = PropostaOtimizacao(
        id=uuid.uuid4(),
        os_id=os_.id,
        jornada_base_id=base.id,
        titulo="Ajustar janela do SMS",
        motivacao="Abertura baixa 18h-20h",
        grafo_proposto=_grafo("proposto"),
        diff={"alterados": ["n1"]},
        impacto={"p50": {"base": 800, "proposto": 860}},
        esforco=2,
        risco=0.25,
        score=1.83,
        created_at=AGORA,
    )
    repo1.adicionar_proposta(proposta)
    repo1.adicionar_aprendizado(
        Aprendizado(
            id=uuid.uuid4(),
            tenant_id=TENANT,
            os_id=os_.id,
            origem="proposta_rejeitada",
            status="sinal",
            texto="Cliente não aceita SMS após 20h",
            created_at=AGORA,
        )
    )
    repo1.adicionar_calibracao(
        CalibracaoPrior(
            id=uuid.uuid4(),
            tenant_id=TENANT,
            tipo_campanha="upsell",
            versao=2,
            priors={"conversao_organica": 0.021},
            score=0.87,
            backtest={"mape": 0.12},
            publicada_em=AGORA,
        )
    )

    repo2 = _repositorio_novo(banco_limpo)
    pendentes = repo2.listar_propostas(os_.id, estado="proposta")
    assert len(pendentes) == 1 and pendentes[0].risco == 0.25 and pendentes[0].score == 1.83
    pendentes[0].estado = "aprovada"
    pendentes[0].decidido_por = "lider@claro.com.br"
    repo2.salvar_proposta(pendentes[0])
    repo3 = _repositorio_novo(banco_limpo)
    assert repo3.obter_proposta(proposta.id).estado == "aprovada"  # type: ignore[union-attr]
    sinais = repo3.listar_aprendizados(os_id=os_.id, status="sinal")
    assert [a.texto for a in sinais] == ["Cliente não aceita SMS após 20h"]
    calibracoes = repo3.listar_calibracoes(TENANT, "upsell")
    assert calibracoes[-1].versao == 2 and calibracoes[-1].priors == {"conversao_organica": 0.021}
    assert repo3.listar_calibracoes(TENANT, "aquisicao") == []  # tipo diferente não vaza
    politica = repo3.politica_publicada_atual(TENANT)
    assert politica is not None and politica.estado == "publicada"
