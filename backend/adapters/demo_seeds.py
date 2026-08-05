"""Seeds DEMO_MODE (SDD §11.4): OS-2026-0457 COMPLETA, ponta a ponta, para o front
demo funcionar sem nenhum passo manual — briefing 14 campos, segmento 847.312, JGC
(4 canais + holdout), Previsto CONGELADO em snapshot, telemetria de 20 dias (ENS +
extract reconciliados) calibrada para lift +24,1pp / ROAS 18,5x, experimento
pré-registrado com janela FECHADA (apuração T15 funciona na hora), launch em rampa,
2 propostas pendentes do optimize e aprendizados aceitos.

Idempotente e 100% local (zero rede, zero LLM — §1.3.5): objetos de domínio direto no
repositório (mesmo padrão de `atelie_seeds.py`). Só roda quando `DEMO_MODE=true` e
`APP_ENV=dev` (create_app); os testes de aceite criam o app com `demo=False` — o
comportamento dos módulos M0–M12 é idêntico com ou sem seeds.

Ids DETERMINÍSTICOS (A15 — UAT na VPS): uuid5(NAMESPACE_URL, 'jornada/<rotulo>') em
TODOS os objetos semeados — restart do backend re-semeia com os MESMOS ids e nenhum
link/bookmark do front quebra (antes, uuid4 trocava tudo a cada boot).

Números calibrados (verificáveis em `tests/acceptance/test_seeds_demo.py`):
- lift realizado = (271/900 − 6/100) × 100 = +24,11 pp · IC95 ≈ [+18,6, +29,6] —
  SIGNIFICATIVO (IC exclui zero, §8-M11-A2); holdout 10% ⇒ n_holdout = 100.
- custo real = 900×0,0018 + 300×0,0005 + 200×0 + 10.590×0,3597 = R$ 3.810,99;
  receita = 271 × R$ 260 (ticket congelado) = R$ 70.460 ⇒ ROAS = 18,49 ("18,5x").
- reconciliação ENS×extract por tipo dentro do limite de 2% (§8-M10-A3): sem alerta.
"""

import hashlib
import uuid
from datetime import datetime, timedelta
from typing import Any, Protocol

from domain.audiencia.modelos import CertificadoElegibilidade, Segmento
from domain.campanha.modelos import OS
from domain.esteira.modelos import EtapaWorkflow
from domain.experimento.modelos import Experimento
from domain.governanca.modelos import Snapshot
from domain.governanca.politicas import POLITICA_PUBLICADA
from domain.governanca.snapshot import hash_composto
from domain.jornada.canonico import hash_jgc
from domain.jornada.diff import diff_grafos
from domain.jornada.modelos import JornadaVersao, SyncRun
from domain.lancamento.modelos import Launch, TelemetryEvent
from domain.otimizacao import ranking
from domain.otimizacao.modelos import Aprendizado, PropostaOtimizacao

OS_CODIGO_DEMO = "OS-2026-0457"

# Escala do realizado (docstring): 900 contatos tratados expostos, 271 conversões
# tratado, 6 no holdout — lift +24,11pp; WhatsApp domina o custo (ROAS 18,5x).
_N_TRATADO = 900
_CONV_TRATADO = 271
_CONV_HOLDOUT = 6
_SENTS = {"email": 900, "push": 300, "sms": 200, "whatsapp": 10_590}
_NO_POR_CANAL = {"email": "n3", "push": "n5", "sms": "n7", "whatsapp": "n9"}
_TICKET_MEDIO = 260.0
_DIAS_TELEMETRIA = 20


class RepositorioDemo(Protocol):
    """Subconjunto do RepositorioOsMemoria usado pelas seeds (tipagem estrutural §2.1)."""

    def obter_os_por_codigo(self, codigo: str) -> Any: ...
    def adicionar_os(self, os_: Any) -> None: ...
    def adicionar_etapa(self, etapa: Any) -> None: ...
    def adicionar_segmento(self, segmento: Any) -> None: ...
    def adicionar_certificado(self, certificado: Any) -> None: ...
    def adicionar_jornada(self, jornada: Any) -> None: ...
    def adicionar_experimento(self, experimento: Any) -> None: ...
    def adicionar_snapshot(self, snapshot: Any) -> None: ...
    def adicionar_sync_run(self, run: Any) -> None: ...
    def adicionar_telemetria(self, evento: Any) -> None: ...
    def maior_id_telemetria(self) -> int: ...
    def adicionar_launch(self, launch: Any) -> None: ...
    def adicionar_proposta(self, proposta: Any) -> None: ...
    def adicionar_aprendizado(self, aprendizado: Any) -> None: ...


def _hash_contato(rotulo: str) -> str:
    """contato_hash sintético (sha256 hex) — NUNCA PII (§10.2)."""
    return hashlib.sha256(f"demo-{rotulo}".encode()).hexdigest()


def _uuid_demo(rotulo: str) -> uuid.UUID:
    """Id DETERMINÍSTICO das seeds (A15): uuid5(NAMESPACE_URL, 'jornada/<rotulo>') —
    dois restarts do backend geram os MESMOS ids e nenhum link do front quebra."""
    return uuid.uuid5(uuid.NAMESPACE_URL, f"jornada/{rotulo}")


def _grafo_demo() -> dict[str, Any]:
    """JGC §5 da OS demo com a paleta COMPLETA do §5.2 (canvas T7 realista — A14):
    entrada por DE → holdout 90/10 (randomSplit) → STO → e-mail → wait →
    decisionSplit (não abriu → push; senão pula) → wait → SMS → wait → WhatsApp →
    goal; braço holdout → exit."""
    return {
        "jgcVersion": "1.0",
        "meta": {
            "osCodigo": OS_CODIGO_DEMO,
            "tenant": "torre-movel",
            "reentrada": "nao",
            "quietHours": {"inicio": "20:00", "fim": "08:00"},
        },
        "nodes": [
            {
                "id": "n1",
                "type": "entrySource",
                "data": {"deRef": "DE_457_entrada", "modo": "fire_once", "reentrada": "nao"},
            },
            {
                "id": "n2",
                "type": "randomSplit",
                "data": {"braços": [{"id": "tratado", "pct": 90}, {"id": "holdout", "pct": 10}]},
            },
            {
                "id": "n12",
                "type": "sto",
                "data": {"janelaHoras": 12, "fallback": "10:00"},
            },
            {
                "id": "n3",
                "type": "channel.email",
                "data": {"assetRef": "asset-email-457-A", "optIn": True, "throttlePorHora": 25_000},
            },
            {"id": "n4", "type": "wait", "data": {"duracao": "PT48H"}},
            {
                "id": "n13",
                "type": "decisionSplit",
                "data": {
                    "regras": [
                        {"expr": "abriu_email == false", "to": "n5"},
                        {"expr": "senao", "to": "n6"},
                    ]
                },
            },
            {
                "id": "n5",
                "type": "channel.push",
                "data": {"assetRef": "asset-push-457", "optIn": True},
            },
            {"id": "n6", "type": "wait", "data": {"duracao": "PT48H"}},
            {
                "id": "n7",
                "type": "channel.sms",
                "data": {"assetRef": "asset-sms-457", "optIn": True},
            },
            {"id": "n8", "type": "wait", "data": {"duracao": "PT24H"}},
            {
                "id": "n9",
                "type": "channel.whatsapp",
                "data": {"assetRef": "template-wa-457", "optIn": True, "throttlePorHora": 5_000},
            },
            {
                "id": "n10",
                "type": "goal",
                "data": {"metrica": "conversion", "deRef": "DE_457_conv"},
            },
            {"id": "n11", "type": "exit", "data": {"motivo": "holdout"}},
        ],
        "edges": [
            {"id": "e1", "from": "n1", "to": "n2", "cond": None},
            {"id": "e2", "from": "n2", "to": "n12", "cond": "tratado"},
            {"id": "e3", "from": "n2", "to": "n11", "cond": "holdout"},
            {"id": "e4", "from": "n12", "to": "n3", "cond": None},
            {"id": "e5", "from": "n3", "to": "n4", "cond": None},
            {"id": "e6", "from": "n4", "to": "n13", "cond": None},
            {"id": "e7", "from": "n5", "to": "n6", "cond": None},
            {"id": "e8", "from": "n6", "to": "n7", "cond": None},
            {"id": "e9", "from": "n7", "to": "n8", "cond": None},
            {"id": "e10", "from": "n8", "to": "n9", "cond": None},
            {"id": "e11", "from": "n9", "to": "n10", "cond": None},
        ],
    }


def _faixa(p10: float, p50: float, p90: float) -> dict[str, float]:
    return {"p10": p10, "p50": p50, "p90": p90}


def _simulacao_demo(segmento_id: uuid.UUID, executada_em: datetime) -> dict[str, Any]:
    """Bloco `jornada_versao.simulacao` (§6) na MESMA forma do motor — números do
    mock T8/T13: prev. 248 conversões · ROAS 15,2x · lift +21pp (o realizado supera
    a régua: +9,3% em conversões, ROAS 18,5x, lift +24,1pp)."""
    return {
        "runs": 500,
        "n_personas": 10_000,
        "volume_entrada": 847_312,
        "funil": {
            "n1": {"tipo": "entrySource", **_faixa(1000, 1000, 1000)},
            "n2": {"tipo": "randomSplit", **_faixa(1000, 1000, 1000)},
            "n12": {"tipo": "sto", **_faixa(900, 900, 900)},
            "n3": {"tipo": "channel.email", **_faixa(905, 950, 985)},
            "n4": {"tipo": "wait", **_faixa(860, 900, 940)},
            "n13": {"tipo": "decisionSplit", **_faixa(860, 900, 940)},
            "n5": {"tipo": "channel.push", **_faixa(245, 280, 315)},
            "n6": {"tipo": "wait", **_faixa(238, 270, 300)},
            "n7": {"tipo": "channel.sms", **_faixa(160, 190, 222)},
            "n8": {"tipo": "wait", **_faixa(700, 820, 930)},
            "n9": {"tipo": "channel.whatsapp", **_faixa(10_400, 11_800, 13_100)},
            "n10": {"tipo": "goal", **_faixa(214, 248, 287)},
            "n11": {"tipo": "exit", **_faixa(100, 100, 100)},
        },
        "conversoes": _faixa(214, 248, 287),
        "custo": _faixa(4_100.0, 4_246.3, 4_400.0),
        "receita": _faixa(55_640.0, 64_480.0, 74_620.0),
        "roas": _faixa(12.9, 15.2, 17.8),
        "lift_pp": _faixa(17.8, 21.0, 24.6),
        "horas_ate_concluir": _faixa(96.0, 120.0, 168.0),
        "pressao_contato": {
            "email": {
                "msgs_por_contato": _faixa(1.0, 1.0, 1.0),
                "cap_janela": 4,
                "colisao_critica": False,
            },
            "push": {
                "msgs_por_contato": _faixa(0.2, 0.3, 0.4),
                "cap_janela": 5,
                "colisao_critica": False,
            },
            "sms": {
                "msgs_por_contato": _faixa(0.1, 0.2, 0.3),
                "cap_janela": 2,
                "colisao_critica": False,
            },
            "whatsapp": {
                "msgs_por_contato": _faixa(1.6, 1.9, 2.0),
                "cap_janela": 2,
                "colisao_critica": False,
            },
        },
        "gargalos": [{"no": "n8", "tipo": "wait", "espera_horas_p50": 24.0}],
        "poder": {
            "aplicavel": True,
            "portao": "verde",
            "suficiente": True,
            "n_disponivel": 762_580,
            "n_minimo": 74_000,
            "mde_pp": 2.0,
            "poder": 0.93,
            "poder_minimo": 0.8,
        },
        "semaforo": "verde",
        "motivos_semaforo": [],
        "portoes": {"experimento": "verde"},
        "avisos": [],
        "premissas": [
            "personas amostradas de agregados do read model (anti-reidentificação §6)",
            f"ticket médio R$ {_TICKET_MEDIO:.0f} (histórico de campanhas de franquia)",
            "quiet hours 20:00–08:00 e caps da política v1 aplicados no relógio virtual",
        ],
        "parametros": {
            "seed": 42,
            "runs": 500,
            "n_personas": 10_000,
            "segmento_id": str(segmento_id),
            "ticket_medio": _TICKET_MEDIO,
            "priors_versao": 1,
        },
        "executada_em": executada_em.isoformat(),
    }


def _briefing_demo() -> dict[str, Any]:
    """Briefing dos 14 campos (§8-M3) — `metas` cru (o monitor T13 lê o dict §8-M10)."""
    campos: dict[str, Any] = {
        "objetivo": "Upgrade de clientes pós-pago para planos 5G",
        "publico": "Pós-pago ativos há 12+ meses sem 5G, ARPU ≥ R$ 80",
        "oferta": "2× dados por 6 meses + streaming incluso na migração 5G",
        "verba": "R$ 32.000",
        "janela": "01/07 a 15/08 (rampa canário 1% → 10% → 100%)",
        "canais": ["email", "push", "sms", "whatsapp"],
        "ticket_medio": _TICKET_MEDIO,
        "tom_de_marca": "Direto, benefício primeiro, sem jargão técnico",
        "restricoes": "Sem abordagem a inadimplentes; quiet hours 20:00–08:00",
        "compliance": "7 listas de supressão + opt-in por canal (Guard determinístico)",
        "experimento_holdout": "10% holdout pré-registrado · janela 15 dias · MDE 2pp",
        "dependencias": "Batch Hybris D-1 (frescor); templates WhatsApp aprovados",
        "responsavel_negocio": "Diretoria Torre Móvel",
    }
    briefing = {campo: {"valor": valor, "inferido": False} for campo, valor in campos.items()}
    briefing["metas"] = {"conversoes": 248, "roas": 15.2, "receita": 64_480.0}  # 14º campo
    return briefing


def _semear_telemetria(
    repositorio: RepositorioDemo, tenant_id: str, os_id: uuid.UUID, agora: datetime
) -> None:
    """20 dias de telemetria (§11.4): ENS (régua do monitor/breakers) + extract
    espelhado dentro do limite de 2% (§8-M10-A3 — reconciliação SEM alerta)."""
    inicio = agora - timedelta(days=_DIAS_TELEMETRIA)

    def _ts(indice: int, total: int) -> datetime:
        """Espalha eventos uniformemente pela janela de 20 dias (1º sent = D-20)."""
        if total <= 1:
            return inicio
        janela_s = _DIAS_TELEMETRIA * 86_400 - 3_600
        return inicio + timedelta(seconds=janela_s * indice / (total - 1))

    def _evento(
        tipo: str,
        ts: datetime,
        *,
        canal: str | None = None,
        no_jgc: str | None = None,
        contato: str | None = None,
        payload: dict[str, Any] | None = None,
        fonte: str = "ens",
    ) -> None:
        repositorio.adicionar_telemetria(
            TelemetryEvent(
                tenant_id=tenant_id,
                os_id=os_id,
                no_jgc=no_jgc,
                canal=canal,
                tipo=tipo,
                contato_hash=contato,
                fonte=fonte,
                ts=ts,
                payload=payload,
            )
        )

    # --- ENS: sents por canal (contatos DISTINTOS = n tratado = 900) ---
    for canal, quantidade in _SENTS.items():
        for i in range(quantidade):
            _evento(
                "sent",
                _ts(i, quantidade),
                canal=canal,
                no_jgc=_NO_POR_CANAL[canal],
                contato=_hash_contato(f"tratado-{i % _N_TRATADO:04d}"),
            )
    # --- ENS: conversões (tratado + holdout — recorte do motor §6/monitor T13) ---
    for i in range(_CONV_TRATADO):
        _evento(
            "conversion",
            _ts(i, _CONV_TRATADO) + timedelta(hours=6),
            contato=_hash_contato(f"tratado-{i:04d}"),
            payload={"grupo": "tratado"},
        )
    for i in range(_CONV_HOLDOUT):
        _evento(
            "conversion",
            _ts(i, _CONV_HOLDOUT) + timedelta(hours=6),
            contato=_hash_contato(f"holdout-{i:04d}"),
            payload={"grupo": "holdout"},
        )
    # --- extract D-1: contagens espelhadas por tipo, divergência < 2% (A3) ---
    total_sents = sum(_SENTS.values())  # 11.990 ENS → 11.960 extract (0,25%)
    for i in range(total_sents - 30):
        _evento("sent", _ts(i, total_sents - 30), canal="email", fonte="extract")
    for i in range(_CONV_TRATADO + _CONV_HOLDOUT - 1):  # 277 → 276 (0,36%)
        _evento("conversion", _ts(i, _CONV_TRATADO + _CONV_HOLDOUT - 1), fonte="extract")


def _propostas_demo(os_: OS, jornada: JornadaVersao, agora: datetime) -> list[PropostaOtimizacao]:
    """2 propostas PENDENTES do optimize (mock T15) — diff/esforço/risco/score pelas
    MESMAS funções determinísticas do M11 (ranking.py/diff.py); decidir é humano."""
    base_p50 = {
        "conversoes": 248.0,
        "custo": 4_246.3,
        "receita": 64_480.0,
        "roas": 15.2,
        "lift_pp": 21.0,
    }

    def _montar(
        titulo: str,
        motivacao: str,
        grafo_proposto: dict[str, Any],
        proposto_p50: dict[str, float],
        semaforo: str,
    ) -> PropostaOtimizacao:
        diff = diff_grafos(jornada.grafo, grafo_proposto)
        deltas = {m: round(proposto_p50[m] - base_p50[m], 4) for m in base_p50}
        esforco = ranking.esforco_do_diff(diff)
        risco = ranking.risco_da_proposta(
            semaforo=semaforo,
            delta_custo_p50=float(deltas["custo"]),
            altera_entrada=False,
        )
        score = ranking.score_da_proposta(
            conversoes_base_p50=base_p50["conversoes"],
            conversoes_proposto_p50=proposto_p50["conversoes"],
            esforco=esforco,
            risco=risco,
        )
        return PropostaOtimizacao(
            id=_uuid_demo(f"proposta/{OS_CODIGO_DEMO}/{titulo}"),  # estável (A15)
            os_id=os_.id,
            jornada_base_id=jornada.id,
            titulo=titulo,
            motivacao=motivacao,
            grafo_proposto=grafo_proposto,
            diff=diff,
            impacto={
                "base": base_p50,
                "proposto": proposto_p50,
                "deltas": deltas,
                "semaforo_proposto": semaforo,
                "parametros": {"seed": 42, "runs": 500, "n_personas": 10_000},
            },
            esforco=esforco,
            risco=risco,
            score=score,
            created_at=agora,
        )

    # Proposta 1 — promover a variante B do e-mail âncora (evidência: +9pp abertura)
    grafo_b = _grafo_demo()
    for no in grafo_b["nodes"]:
        if no["id"] == "n3":
            no["data"]["assetRef"] = "asset-email-457-B"
    proposta_b = _montar(
        "Promover variante B do e-mail âncora → 100%",
        "Variante B com +9pp de abertura (significativo) na onda atual — promover "
        "para toda a audiência tratada.",
        grafo_b,
        {"conversoes": 312.0, "custo": 4_246.3, "receita": 81_120.0, "roas": 19.1, "lift_pp": 24.8},
        "verde",
    )

    # Proposta 2 — WhatsApp só para engagement_score > 90 (corta 38% do custo WA)
    grafo_wa = _grafo_demo()
    grafo_wa["nodes"].append(
        {
            "id": "n14",
            "type": "decisionSplit",
            "data": {
                "regras": [
                    {"expr": "engagement_score > 90", "to": "n9"},
                    {"expr": "senao", "to": "n10"},
                ]
            },
        }
    )
    for aresta in grafo_wa["edges"]:
        if aresta["id"] == "e10":  # n8 → n9 passa por n14
            aresta["to"] = "n14"
    proposta_wa = _montar(
        "WhatsApp só para engagement_score > 90",
        "CTR do WhatsApp 30% abaixo do previsto no perfil de baixo engajamento — "
        "restringir ao decil superior corta 38% do custo do canal.",
        grafo_wa,
        {"conversoes": 236.0, "custo": 2_633.1, "receita": 61_360.0, "roas": 18.3, "lift_pp": 20.4},
        "verde",
    )
    return [proposta_b, proposta_wa]


def semear_demo(repositorio: RepositorioDemo, *, tenant_id: str, agora: datetime) -> None:
    """Semeia a OS-2026-0457 ponta a ponta (§11.4); no-op se já semeada."""
    if repositorio.obter_os_por_codigo(OS_CODIGO_DEMO) is not None:
        return

    os_ = OS(
        id=_uuid_demo(f"os/{OS_CODIGO_DEMO}"),
        tenant_id=tenant_id,
        codigo=OS_CODIGO_DEMO,
        nome="Upgrade Pós-Pago 5G",
        tshirt="G",
        fase="monitorada",
        briefing=_briefing_demo(),
        frozen={
            "agent_versions": {
                nome: "1.0"
                for nome in (
                    "consultor",
                    "engineer",
                    "flow",
                    "visual",
                    "copy",
                    "content",
                    "insight",
                    "optimize",
                )
            },
            "policy_version": POLITICA_PUBLICADA["versao"],
            "tarifario_id": "tarifas-2026-01",
            "slas": {"tshirt": "G", "congelado_em": (agora - timedelta(days=45)).isoformat()},
        },
        created_by=uuid.uuid5(uuid.NAMESPACE_DNS, "demo.jornada.claro"),
        created_at=agora - timedelta(days=50),
        updated_at=agora,
    )
    repositorio.adicionar_os(os_)

    # ------------------------------------------------------- esteira T4a (M2)
    etapas = (
        ("briefing", "concluida"),
        ("discovery", "concluida"),
        ("audiencia", "concluida"),
        ("criativos", "concluida"),
        ("configuracao", "concluida"),
        ("disparo", "concluida"),
        ("acompanhamento", "em_andamento"),
    )
    for ordem, (nome, estado) in enumerate(etapas, start=1):
        checklist: list[dict[str, Any]] = []
        if nome == "criativos":  # 4 subtarefas padrão (§8-M2-A1)
            checklist = [
                {
                    "item": item,
                    "feito": True,
                    "por": "analista@claro.com.br",
                    "em": (agora - timedelta(days=40)).isoformat(),
                }
                for item in ("KV master", "Copy por canal", "HTML e-mail", "Template WhatsApp")
            ]
        repositorio.adicionar_etapa(
            EtapaWorkflow(
                id=_uuid_demo(f"etapa/{OS_CODIGO_DEMO}/{nome}"),
                os_id=os_.id,
                ordem=ordem,
                nome=nome,
                responsavel=None,
                sla_dias=5,
                estado=estado,
                checklist=checklist,
                dependencias=[],
                hike_ref=None,
            )
        )

    # ------------------------------------------- segmento 847.312 (§11.4) + guard
    segmento = Segmento(
        id=_uuid_demo(f"segmento/{OS_CODIGO_DEMO}"),
        os_id=os_.id,
        origem="estudio_sql",
        sql_publico=(
            "select contato_hash from base_clientes\n"
            "where plano = 'pos_pago' and meses_ativo >= 12 and flag_5g = false\n"
            "  and contato_hash not in (select contato_hash from lista_supressao\n"
            "    where lista in ('blacklist','fraude','nao_perturbe','optout',\n"
            "                    'procon','inadimplente','reprovado_credito'))"
        ),
        criterios_resumo="Pós-pago 12+ meses sem 5G, ARPU ≥ R$ 80, elegíveis (7 listas)",
        contagem_bruta=1_012_400,
        contagem_liquida=847_312,
        waterfall=[
            {
                "etapa": "7 listas de supressão",
                "corte": 152_988,
                "restante": 859_412,
                "motivo": "Guard determinístico (§8-M5)",
            },
            {
                "etapa": "opt-in por canal",
                "corte": 10_100,
                "restante": 849_312,
                "motivo": "sem opt-in em nenhum canal da campanha",
            },
            {
                "etapa": "colisões do governor",
                "corte": 2_000,
                "restante": 847_312,
                "motivo": "pressão de contato cross-campanha",
            },
        ],
        volume_abordagem={
            "email": {"n": 610_065, "pct": 72.0},
            "sms": {"n": 796_473, "pct": 94.0},
            "push": {"n": 457_548, "pct": 54.0},
            "whatsapp": {"n": 398_236, "pct": 47.0},
        },
        holdout_pct=10.0,
        frescor={
            "hybris_billing": (agora - timedelta(hours=14)).isoformat(),
            "navegacao": agora.isoformat(),
            "data_cloud": (agora - timedelta(hours=3)).isoformat(),
        },
    )
    repositorio.adicionar_segmento(segmento)
    repositorio.adicionar_certificado(
        CertificadoElegibilidade(
            id=_uuid_demo(f"certificado/{OS_CODIGO_DEMO}"),
            os_id=os_.id,
            hash=hashlib.sha256(b"demo-certificado-457").hexdigest(),
            suprimidos={
                "blacklist": 12_406,
                "fraude": 8_112,
                "nao_perturbe": 45_210,
                "optout": 60_104,
                "procon": 3_208,
                "inadimplente": 12_880,
                "reprovado_credito": 11_068,
            },
            liquido=847_312,
            emitido_em=agora - timedelta(days=22),
            valido_ate=agora + timedelta(days=7),
        )
    )

    # ---------------------------------------- twin (JGC) + Ensaio + Previsto (§6)
    grafo = _grafo_demo()
    executada_em = agora - timedelta(days=21)
    simulacao = _simulacao_demo(segmento.id, executada_em)
    jornada = JornadaVersao(
        id=_uuid_demo(f"jornada/{OS_CODIGO_DEMO}/v1"),
        os_id=os_.id,
        versao=1,
        grafo=grafo,
        hash=hash_jgc(grafo),
        estado="publicado",  # launch em rampa ⇒ versão materializada (M9: apply ok)
        premissas=["cadência D0 → D2 → D4 → D5 (e-mail → push → SMS → WhatsApp)"],
        custo_projetado=31_800.0,
        simulacao=simulacao,
        previsto={
            **simulacao,
            "congelado_em": executada_em.isoformat(),
            "congelado_por": "analista@claro.com.br",
        },
    )
    repositorio.adicionar_jornada(jornada)

    # ------------------------------ experimento pré-registrado, janela FECHADA (T15)
    experimento = Experimento(
        id=_uuid_demo(f"experimento/{OS_CODIGO_DEMO}"),
        os_id=os_.id,
        holdout_pct=10.0,
        n_minimo=74_000,
        mde_pp=2.0,
        janela_dias=15,  # 1º sent D-20 ⇒ janela fechou D-5 — apuração liberada (A1)
        metricas={"primaria": "conversion", "janela_atribuicao_dias": 7},
        travado_em=agora - timedelta(days=21),
        estado="pre_registrado",
    )
    repositorio.adicionar_experimento(experimento)

    # -------------------------------------- snapshot com Previsto CONGELADO (§4.1)
    componentes: dict[str, Any] = {
        "jgc": {"jornada_id": str(jornada.id), "versao": jornada.versao, "hash": jornada.hash},
        "sql": segmento.sql_publico,
        "criativos": [],
        "politica": {
            "versao": POLITICA_PUBLICADA["versao"],
            "conteudo": POLITICA_PUBLICADA["conteudo"],
        },
        "custo": {"previsto_p50": 4_246.3, "moeda": "BRL"},
        "experimento": {
            "id": str(experimento.id),
            "holdout_pct": experimento.holdout_pct,
            "n_minimo": experimento.n_minimo,
            "mde_pp": experimento.mde_pp,
            "janela_dias": experimento.janela_dias,
        },
    }
    snapshot = Snapshot(
        id=_uuid_demo(f"snapshot/{OS_CODIGO_DEMO}"),
        os_id=os_.id,
        hash=hash_composto(componentes),
        conteudo={
            "componentes": componentes,
            "os": {"id": str(os_.id), "codigo": os_.codigo, "nome": os_.nome},
            "segmento": {
                "id": str(segmento.id),
                "contagem_liquida": segmento.contagem_liquida,
                "waterfall": segmento.waterfall,
                "volume_abordagem": segmento.volume_abordagem,
            },
            "criado_por": "analista@claro.com.br",
        },
        previsto=jornada.previsto,
        created_at=agora - timedelta(days=21),
    )
    repositorio.adicionar_snapshot(snapshot)
    repositorio.adicionar_sync_run(  # materialização (§8-M9) — pré-condição do armar
        SyncRun(
            id=_uuid_demo(f"sync-run/{OS_CODIGO_DEMO}/apply-homolog"),
            snapshot_id=snapshot.id,
            ambiente="homolog",
            fase="apply",
            plano=[],
            resultado={"aplicados": 14, "avisos": []},
            estado="ok",
            api_calls=14,
            created_at=agora - timedelta(days=20, hours=2),
        )
    )

    # -------------------------------- telemetria 20d + launch em rampa (§8-M10)
    _semear_telemetria(repositorio, tenant_id, os_.id, agora)
    marco = repositorio.maior_id_telemetria()  # janela dos breakers começa APÓS as seeds
    inicio_rampa = agora - timedelta(days=_DIAS_TELEMETRIA)
    repositorio.adicionar_launch(
        Launch(
            id=_uuid_demo(f"launch/{OS_CODIGO_DEMO}"),
            snapshot_id=snapshot.id,
            onda_atual=2,
            estado="em_rampa",
            breakers=dict(POLITICA_PUBLICADA["conteudo"]["breakers"]),
            eventos=[
                {
                    "tipo": "armado",
                    "por": "lider@claro.com.br",
                    "em": inicio_rampa.isoformat(),
                    "marco_telemetria": marco,
                },
                {
                    "tipo": "onda_avancada",
                    "por": "lider@claro.com.br",
                    "em": inicio_rampa.isoformat(),
                    "onda": 1,
                    "pct": 1.0,
                },
                {
                    "tipo": "onda_avancada",
                    "por": "lider@claro.com.br",
                    "em": (agora - timedelta(days=13)).isoformat(),
                    "onda": 2,
                    "pct": 10.0,
                },
            ],
        )
    )

    # ------------------------------------ loop T15: propostas + aprendizados (M11)
    for proposta in _propostas_demo(os_, jornada, agora - timedelta(hours=4)):
        repositorio.adicionar_proposta(proposta)
    aprendizados = (
        ("experimento", "Cadência D0→D2→D4 supera D0→D1→D3 (+6pp CTR)"),
        ("proposta_aprovada", "Headline '2× dados' vence 'sem sustos' neste perfil"),
        ("proposta_rejeitada", "WhatsApp só compensa com engagement_score > 90"),
    )
    for origem, texto in aprendizados:
        repositorio.adicionar_aprendizado(
            Aprendizado(
                id=_uuid_demo(f"aprendizado/{OS_CODIGO_DEMO}/{origem}"),
                tenant_id=tenant_id,
                os_id=os_.id,
                origem=origem,
                status="aceito" if origem != "proposta_rejeitada" else "sinal",
                texto=texto,
                meta={"seed_demo": True},
                created_at=agora - timedelta(days=2),
            )
        )
