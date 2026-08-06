"""Caso de uso do M10 (parte 1) · Torre de Lançamento T12 (SDD §8-M10, §4.1 `launch`)
— DETERMINÍSTICO, **LLM PROIBIDO em todo este caminho** (§10.6: breakers e kill são
caminho crítico): avaliação de breakers é código puro (domain/lancamento/breakers.py);
aqui entram orquestração, guardas e persistência atrás de portas (§2.1).

- `armar(snapshot)` — exige APPLY OK do snapshot (§8-M10) e nenhum launch ativo;
  congela os `breakers` da política publicada (§4.1: "limites da política congelada")
  e grava o marco de telemetria (janela de avaliação).
- `avancar_onda` — PORTÃO AUTOMÁTICO entre ondas: avalia os breakers sobre a
  telemetria da janela ANTES de avançar; disparo ⇒ pausa (ou kill, se SEV1)
  automática + 409. Rampa 1% → 10% → 100%; após a última onda ⇒ `concluido`.
- `ingerir_telemetria` — ingestão (webhook ENS §8-M10) com guarda-corpo de PII
  (§10.2) + avaliação automática dos launches `em_rampa` das OSs afetadas (A1:
  optout>limite ⇒ `pausado_breaker` AUTOMÁTICO; A2: disparo p/ contato suprimido ⇒
  incidente SEV1 + KILL AUTOMÁTICO).
- `kill` — 2 ETAPAS: solicitação (retorna token de confirmação) → confirmação
  (mata + incidente `kill_manual`).
- `retomar` — SEMPRE humano (A1); incidente SEV1 aberto ⇒ exige 2 aprovadores
  DISTINTOS (§10.5: segregação); retomada resolve os incidentes e re-arma a janela
  de telemetria (marco novo).

M10 parte 2 — telemetria dupla + monitor (§8-M10):
- `carregar_extracts` — job "extracts loader": lê o batch D-1 pela ExtractsPort
  (fixture CSV em dev/teste §11), resolve `os_codigo`→OS e delega à MESMA ingestão
  guardada (`fonte='extract'`, §4.1) — taxas de breaker seguem medindo só ENS
  (breakers.py), mas disparo a contato suprimido no extract também mata (A2).
- `reconciliar` — reconciliação diária ENS×extract (A3): divergência relativa >2%
  em qualquer tipo ⇒ alerta (incidente sev3 `reconciliacao_divergente`, com dedupe
  por incidente aberto, + evento `telemetry.reconciliacao_divergente`).
- `monitor` — TODOS os KPIs como par previsto×realizado (§1.1.2) sobre o Previsto
  CONGELADO do snapshot do launch (domain/lancamento/monitor.py, código puro).
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from application.ports.clock import ClockPort
from application.ports.extracts import ExtractsPort
from application.ports.lista_supressao import ListaSupressaoPort
from application.ports.repositorio_lancamento import RepositorioLancamento
from domain.campanha.erros import NaoEncontrado
from domain.campanha.modelos import OS, EventoDominio
from domain.custo.tarifas import TARIFAS_VIGENTES
from domain.governanca.modelos import Snapshot
from domain.governanca.politicas import POLITICA_PUBLICADA
from domain.lancamento.breakers import avaliar_breakers
from domain.lancamento.erros import (
    ApplyNecessario,
    AprovadorRepetido,
    BreakerDisparado,
    ConfirmacaoInvalida,
    LaunchJaAtivo,
    LaunchNaoOperavel,
    PrevistoAusente,
    TelemetriaInvalida,
)
from domain.lancamento.modelos import (
    APROVADORES_RETOMADA_SEV1,
    ESTADOS_ATIVOS,
    TIPOS_TELEMETRIA,
    Incidente,
    Launch,
    TelemetryEvent,
)
from domain.lancamento.monitor import montar_monitor
from domain.lancamento.reconciliacao import comparar_fontes
from domain.lancamento.telemetria import contato_hash_valido, pii_no_payload

_ACTOR_SISTEMA = "sistema"

# Entradas de `launch.eventos` que reiniciam a contagem de aprovações de retomada
_MARCOS_RETOMADA: tuple[str, ...] = ("breaker_disparado", "kill_confirmado", "retomada")


class ServicoLancamento:
    def __init__(
        self,
        repositorio: RepositorioLancamento,
        relogio: ClockPort,
        supressao: ListaSupressaoPort,
        tarifas: dict[str, Decimal] | None = None,
        extracts: ExtractsPort | None = None,
    ) -> None:
        self._repo = repositorio
        self._relogio = relogio
        self._supressao = supressao
        self._tarifas = tarifas if tarifas is not None else TARIFAS_VIGENTES
        self._extracts = extracts

    # ---------------------------------------------- POST /launch/{snapshot}/armar
    def armar(self, tenant_id: str, snapshot_id: uuid.UUID, *, actor: str) -> Launch:
        snapshot, os_ = self._snapshot_da_os(tenant_id, snapshot_id)
        applies_ok = [
            r for r in self._repo.listar_sync_runs(snapshot.id, fase="apply") if r.estado == "ok"
        ]
        if not applies_ok:  # §8-M10: "exige apply ok"
            raise ApplyNecessario(
                "Armar exige APPLY OK do snapshot (materialização §5.4/§8-M9) — "
                "nenhum sync_run fase=apply estado=ok encontrado (§8-M10)."
            )
        ativos = [
            launch
            for launch in self._repo.listar_launches(snapshot.id)
            if launch.estado in ESTADOS_ATIVOS
        ]
        if ativos:
            raise LaunchJaAtivo(
                f"Snapshot já tem launch ativo ({ativos[-1].estado}) — "
                "conclua, mate ou retome antes de armar outro."
            )
        launch = Launch(
            id=uuid.uuid4(),
            snapshot_id=snapshot.id,
            breakers=dict(POLITICA_PUBLICADA["conteudo"]["breakers"]),  # congelados (§4.1)
        )
        launch.eventos.append(
            self._entrada("armado", actor, marco_telemetria=self._repo.maior_id_telemetria())
        )
        self._repo.adicionar_launch(launch)
        self._outbox(os_, "launch.armado", actor, {"launch_id": str(launch.id)})
        return launch

    # ---------------------------------------------- POST /launch/{id}/avancar-onda
    def avancar_onda(self, tenant_id: str, launch_id: uuid.UUID, *, actor: str) -> Launch:
        launch, snapshot, os_ = self._launch_do_tenant(tenant_id, launch_id)
        if launch.estado == "pausado_breaker":
            raise LaunchNaoOperavel(
                "Launch pausado por breaker — retomar exige humano "
                "(POST /launch/{id}/retomar, §8-M10-A1)."
            )
        if launch.estado in ("morto", "concluido"):
            raise LaunchNaoOperavel(f"Launch {launch.estado} — rampa encerrada (§4.1).")

        # Portão AUTOMÁTICO entre ondas (§8-M10): breakers limpos para avançar
        disparos = self._avaliar(launch, snapshot, os_)
        if disparos:
            self._aplicar_disparos(launch, os_, disparos)
            raise BreakerDisparado(disparos, launch.estado)

        agora = self._relogio.agora()
        if launch.onda_atual >= len(launch.ondas):
            launch.estado = "concluido"
            launch.eventos.append(self._entrada("concluido", actor))
            self._repo.salvar_launch(launch)
            self._outbox(os_, "launch.concluido", actor, {"launch_id": str(launch.id)})
            return launch
        launch.onda_atual += 1
        launch.estado = "em_rampa"
        pct = float(launch.ondas[launch.onda_atual - 1]["pct"])
        launch.eventos.append(
            self._entrada("onda_avancada", actor, onda=launch.onda_atual, pct=pct)
        )
        self._repo.salvar_launch(launch)
        self._outbox(  # §2.3
            os_,
            "launch.wave_advanced",
            actor,
            {
                "launch_id": str(launch.id),
                "onda": launch.onda_atual,
                "pct": pct,
                "em": agora.isoformat(),
            },
        )
        return launch

    # ------------------------------------------------------ POST /launch/{id}/kill
    def kill(
        self,
        tenant_id: str,
        launch_id: uuid.UUID,
        *,
        confirmacao: str | None,
        actor: str,
    ) -> dict[str, Any]:
        """Kill switch em 2 ETAPAS (§8-M10): sem `confirmacao` registra a solicitação
        e devolve o token; com o token da solicitação pendente, mata o launch."""
        launch, _, os_ = self._launch_do_tenant(tenant_id, launch_id)
        if launch.estado in ("morto", "concluido"):
            raise LaunchNaoOperavel(f"Launch {launch.estado} — nada a matar.")
        if confirmacao is None:  # etapa 1
            token = uuid.uuid4().hex
            launch.eventos.append(self._entrada("kill_solicitado", actor, confirmacao=token))
            self._repo.salvar_launch(launch)
            return {"etapa": 1, "confirmacao": token, "launch": launch}
        pendente = next(
            (e for e in reversed(launch.eventos) if e["tipo"] == "kill_solicitado"), None
        )
        if pendente is None or pendente.get("confirmacao") != confirmacao:
            raise ConfirmacaoInvalida(
                "Confirmação de kill inválida — solicite o kill (etapa 1) e repasse o "
                "token devolvido (§8-M10: kill em 2 etapas)."
            )
        launch.estado = "morto"
        launch.eventos.append(self._entrada("kill_confirmado", actor))
        self._repo.salvar_launch(launch)
        self._abrir_incidente(
            os_,
            launch,
            sev="sev2",
            tipo="kill_manual",
            titulo="Kill switch acionado manualmente (2 etapas)",
            meta={"solicitado_por": str(pendente["por"]), "confirmado_por": actor},
            actor=actor,
        )
        self._outbox(
            os_,
            "launch.killed",  # §2.3
            actor,
            {"launch_id": str(launch.id), "automatico": False, "motivo": "kill_manual"},
        )
        return {"etapa": 2, "confirmacao": None, "launch": launch}

    # --------------------------------------------------- POST /launch/{id}/retomar
    def retomar(
        self, tenant_id: str, launch_id: uuid.UUID, *, actor: str, aprovador_id: uuid.UUID
    ) -> dict[str, Any]:
        """Retomada SEMPRE humana (A1). Incidente SEV1 aberto ⇒ 2 aprovadores
        DISTINTOS (§8-M10); aprovador repetido ⇒ 403 (segregação §10.5)."""
        launch, _, os_ = self._launch_do_tenant(tenant_id, launch_id)
        if launch.estado not in ("pausado_breaker", "morto"):
            raise LaunchNaoOperavel(
                f"Launch {launch.estado} — só se retoma launch pausado_breaker|morto."
            )
        abertos = self._repo.listar_incidentes(launch_id=launch.id, estado="aberto")
        exigidas = APROVADORES_RETOMADA_SEV1 if any(i.sev == "sev1" for i in abertos) else 1
        aprovacoes = self._aprovacoes_pendentes(launch)
        if any(a["aprovador_id"] == str(aprovador_id) for a in aprovacoes):
            raise AprovadorRepetido(
                "Retomada SEV1 exige 2 aprovadores DISTINTOS — este usuário já "
                "aprovou esta retomada (§8-M10; segregação §10.5)."
            )
        agora = self._relogio.agora()
        launch.eventos.append(
            self._entrada("retomada_aprovada", actor, aprovador_id=str(aprovador_id))
        )
        aprovacoes = [*aprovacoes, {"por": actor, "aprovador_id": str(aprovador_id)}]
        if len(aprovacoes) < exigidas:
            self._repo.salvar_launch(launch)
            return {
                "retomado": False,
                "aprovacoes": len(aprovacoes),
                "exigidas": exigidas,
                "launch": launch,
            }
        aprovadores = [{"por": a["por"], "em": agora.isoformat()} for a in aprovacoes]
        launch.estado = "em_rampa" if launch.onda_atual >= 1 else "armado"
        launch.eventos.append(  # marco novo: a janela dos breakers recomeça aqui
            self._entrada(
                "retomada",
                actor,
                aprovadores=[a["por"] for a in aprovacoes],
                marco_telemetria=self._repo.maior_id_telemetria(),
            )
        )
        self._repo.salvar_launch(launch)
        for incidente in abertos:
            incidente.estado = "resolvido"
            incidente.resolvido_em = agora
            incidente.meta = {**incidente.meta, "retomada": {"aprovadores": aprovadores}}
            self._repo.salvar_incidente(incidente)
        self._outbox(
            os_,
            "launch.retomado",
            actor,
            {
                "launch_id": str(launch.id),
                "aprovadores": [a["por"] for a in aprovacoes],
                "sev1": exigidas == APROVADORES_RETOMADA_SEV1,
            },
        )
        return {
            "retomado": True,
            "aprovacoes": len(aprovacoes),
            "exigidas": exigidas,
            "launch": launch,
        }

    # ------------------------------------------------------- POST /webhooks/ens
    def ingerir_telemetria(
        self,
        tenant_id: str,
        eventos: list[dict[str, Any]],
        *,
        fonte: str = "ens",
        actor: str = "ens",
    ) -> dict[str, Any]:
        """Ingestão (§8-M10) + avaliação AUTOMÁTICA dos breakers (A1/A2). Guarda-corpo
        de PII (§10.2): payload com PII ou contato fora de hash ⇒ 422, nada é gravado."""
        validados: list[TelemetryEvent] = []
        for bruto in eventos:
            tipo = str(bruto["tipo"])
            if tipo not in TIPOS_TELEMETRIA:  # ENS valida via Pydantic; extract chega aqui
                raise TelemetriaInvalida(
                    f"tipo {tipo!r} fora do contrato `telemetry_event.tipo` (§4.1)."
                )
            contato = bruto.get("contato_hash")
            if not contato_hash_valido(contato):
                raise TelemetriaInvalida(
                    "contato_hash deve ser sha256 hex de 64 chars — NUNCA msisdn/"
                    "e-mail em claro (§4.1/§10.2)."
                )
            motivo_pii = pii_no_payload(bruto.get("payload"))
            if motivo_pii:
                raise TelemetriaInvalida(f"Telemetria rejeitada: {motivo_pii}")
            validados.append(
                TelemetryEvent(
                    tenant_id=tenant_id,
                    os_id=bruto.get("os_id"),
                    no_jgc=bruto.get("no_jgc"),
                    canal=bruto.get("canal"),
                    tipo=str(bruto["tipo"]),
                    contato_hash=contato,
                    fonte=fonte,
                    ts=bruto["ts"],
                    payload=bruto.get("payload"),
                )
            )
        os_afetadas: dict[uuid.UUID, OS] = {}
        for evento in validados:
            self._repo.adicionar_telemetria(evento)
            if evento.os_id is not None and evento.os_id not in os_afetadas:
                os_ = self._repo.obter_os(tenant_id, evento.os_id)
                if os_ is not None:
                    os_afetadas[os_.id] = os_
        for os_ in os_afetadas.values():
            self._outbox(
                os_,
                "telemetry.ingested",  # §2.3
                actor,
                {"fonte": fonte, "quantidade": sum(1 for e in validados if e.os_id == os_.id)},
            )
        avaliados = [
            resultado
            for os_ in os_afetadas.values()
            for resultado in self._avaliar_launches_da_os(os_)
        ]
        return {"recebidos": len(validados), "avaliados": avaliados}

    # ------------------------------------------------- job extracts loader (§8-M10)
    def carregar_extracts(self, tenant_id: str, *, actor: str = "extracts") -> dict[str, Any]:
        """Carrega o batch D-1 da ExtractsPort (fixture CSV §11 em dev/teste) como
        `telemetry_event` fonte='extract' (§4.1) pela MESMA ingestão guardada (PII
        §10.2 + avaliação A2). Linha de OS desconhecida no tenant é IGNORADA e
        contada (extract multi-OS; nada é inventado §1.3.5)."""
        if self._extracts is None:
            raise TelemetriaInvalida(
                "ExtractsPort não configurada — o loader exige a fonte de extracts (§2.1)."
            )
        eventos: list[dict[str, Any]] = []
        ignorados = 0
        os_por_codigo: dict[str, OS | None] = {}
        for bruto in self._extracts.listar_eventos():
            codigo = str(bruto.get("os_codigo") or "")
            if codigo not in os_por_codigo:
                # Busca ESCOPADA no tenant (achado 22/UAT5): `os.codigo` passou a ser
                # unique por tenant (migração 0014), então a busca global devolveria
                # uma OS arbitrária entre os clientes que compartilham o código — e a
                # conferência abaixo descartaria o batch legítimo em silêncio.
                os_por_codigo[codigo] = self._repo.obter_os_por_codigo(codigo, tenant_id)
            os_ = os_por_codigo[codigo]
            if os_ is None:
                ignorados += 1
                continue
            eventos.append(
                {
                    "os_id": os_.id,
                    "no_jgc": bruto.get("no_jgc"),
                    "canal": bruto.get("canal"),
                    "tipo": bruto["tipo"],
                    "contato_hash": bruto.get("contato_hash"),
                    "ts": datetime.fromisoformat(str(bruto["ts"])),
                    "payload": bruto.get("payload"),
                }
            )
        resultado = (
            self.ingerir_telemetria(tenant_id, eventos, fonte="extract", actor=actor)
            if eventos
            else {"recebidos": 0, "avaliados": []}
        )
        return {
            "carregados": resultado["recebidos"],
            "ignorados": ignorados,
            "avaliados": resultado["avaliados"],
        }

    # --------------------------------------- reconciliação diária ENS×extract (A3)
    def reconciliar(
        self, tenant_id: str, os_id: uuid.UUID, *, actor: str = "reconciliacao"
    ) -> dict[str, Any]:
        """Job diário (§8-M10): compara contagens ENS×extract por tipo (código puro
        em reconciliacao.py); divergência >2% ⇒ ALERTA (A3) — incidente sev3
        `reconciliacao_divergente` (dedupe por incidente aberto) + evento."""
        os_ = self._repo.obter_os(tenant_id, os_id)
        if os_ is None:
            raise NaoEncontrado(f"OS {os_id} não encontrada no tenant {tenant_id!r}.")
        resultado = comparar_fontes(self._repo.listar_telemetria(os_.id))
        self._outbox(
            os_,
            "telemetry.reconciliada",
            actor,
            {"divergente": resultado["divergente"], "divergencias": resultado["divergencias"]},
        )
        incidente_id: str | None = None
        if resultado["divergente"]:
            abertos = [
                i
                for i in self._repo.listar_incidentes(os_id=os_.id, estado="aberto")
                if i.tipo == "reconciliacao_divergente"
            ]
            if abertos:  # dedupe: job diário não re-abre alerta já em tratamento
                incidente_id = str(abertos[-1].id)
            else:
                tipos = ", ".join(resultado["divergencias"])
                incidente = self._abrir_incidente(
                    os_,
                    None,
                    sev="sev3",
                    tipo="reconciliacao_divergente",
                    titulo=f"Reconciliação ENS×extract divergente (>{resultado['limite_pct']}%)",
                    meta={"reconciliacao": resultado},
                    actor=actor,
                )
                incidente.descricao = f"Tipos acima do limite: {tipos} (§8-M10-A3)."
                self._repo.salvar_incidente(incidente)
                incidente_id = str(incidente.id)
            self._outbox(
                os_,
                "telemetry.reconciliacao_divergente",
                actor,
                {
                    "divergencias": resultado["divergencias"],
                    "por_tipo": resultado["por_tipo"],
                    "incidente_id": incidente_id,
                },
            )
        return {"os_id": str(os_.id), "incidente_id": incidente_id, **resultado}

    # ------------------------------------------------------- GET /os/{id}/monitor
    def monitor(self, tenant_id: str, os_id: uuid.UUID) -> dict[str, Any]:
        """Monitor T13 (§8-M10): par previsto×realizado em TODO KPI usando o Previsto
        CONGELADO do snapshot do launch (§1.1.2 — nunca a simulação corrente)."""
        os_ = self._repo.obter_os(tenant_id, os_id)
        if os_ is None:
            raise NaoEncontrado(f"OS {os_id} não encontrada no tenant {tenant_id!r}.")
        launch, snapshot = self._launch_de_referencia(os_.id)
        if snapshot is None or not snapshot.previsto:
            raise PrevistoAusente(
                "OS sem snapshot com Previsto congelado — o monitor compara TODO KPI "
                "contra a régua congelada (§8-M10/§1.1.2)."
            )
        eventos = self._repo.listar_telemetria(os_.id)
        experimento = (snapshot.conteudo.get("componentes") or {}).get("experimento") or {}
        holdout_pct = experimento.get("holdout_pct")
        if holdout_pct is None:  # fallback: holdout do segmento da OS (default 10.0 §4.1)
            segmentos = self._repo.listar_segmentos(os_.id)
            holdout_pct = segmentos[-1].holdout_pct if segmentos else None
        painel = montar_monitor(
            previsto=snapshot.previsto,
            eventos=eventos,
            tarifas=self._tarifas,
            metas=dict((os_.briefing or {}).get("metas") or {}),
            holdout_pct=holdout_pct,
        )
        reconciliacao = comparar_fontes(eventos)
        alertas = [
            {"id": str(i.id), "sev": i.sev, "tipo": i.tipo, "titulo": i.titulo}
            for i in self._repo.listar_incidentes(os_id=os_.id, estado="aberto")
        ]
        return {
            "os": {"id": str(os_.id), "codigo": os_.codigo, "nome": os_.nome, "fase": os_.fase},
            "snapshot": {
                "id": str(snapshot.id),
                "hash": snapshot.hash,
                "previsto_congelado_em": snapshot.previsto.get("congelado_em"),
            },
            "launch": None
            if launch is None
            else {
                "id": str(launch.id),
                "estado": launch.estado,
                "onda_atual": launch.onda_atual,
                "ondas": launch.ondas,
            },
            **painel,
            "reconciliacao": {**reconciliacao, "alertas": alertas},
        }

    # ------------------------------------------------------------------- privados
    def _launch_de_referencia(self, os_id: uuid.UUID) -> tuple[Launch | None, Snapshot | None]:
        """Último launch da OS (e seu snapshot); sem launch, o último snapshot com
        Previsto congelado — a régua do monitor (§1.1.2)."""
        launch: Launch | None = None
        snapshot: Snapshot | None = None
        for candidato in self._repo.listar_snapshots(os_id):
            launches = self._repo.listar_launches(candidato.id)
            if launches:
                launch, snapshot = launches[-1], candidato
            elif launch is None and candidato.previsto:
                snapshot = candidato
        return launch, snapshot

    def _avaliar_launches_da_os(self, os_: OS) -> list[dict[str, Any]]:
        """Breakers 'durante onda' (A1): avalia todo launch `em_rampa` da OS; disparo
        ⇒ pausa/kill AUTOMÁTICO (actor sistema)."""
        resultados: list[dict[str, Any]] = []
        for snapshot in self._repo.listar_snapshots(os_.id):
            for launch in self._repo.listar_launches(snapshot.id):
                if launch.estado != "em_rampa":
                    continue
                disparos = self._avaliar(launch, snapshot, os_)
                if disparos:
                    self._aplicar_disparos(launch, os_, disparos)
                resultados.append(
                    {
                        "launch_id": str(launch.id),
                        "estado": launch.estado,
                        "disparos": disparos,
                    }
                )
        return resultados

    def _avaliar(self, launch: Launch, snapshot: Snapshot, os_: OS) -> list[dict[str, Any]]:
        """Avaliação determinística (breakers.py) sobre a JANELA de telemetria —
        eventos após o marco do armar/última retomada."""
        marco = next(
            (
                int(e["marco_telemetria"])
                for e in reversed(launch.eventos)
                if "marco_telemetria" in e
            ),
            0,
        )
        eventos = self._repo.listar_telemetria(os_.id, apos_id=marco)
        hashes = {e.contato_hash for e in eventos if e.tipo == "sent" and e.contato_hash}
        listas_por_contato = {
            h: listas
            for h in hashes
            if (listas := self._supressao.listas_do_contato(os_.tenant_id, h))
        }
        custo = (snapshot.conteudo.get("componentes") or {}).get("custo") or {}
        return avaliar_breakers(
            eventos=eventos,
            limites=launch.breakers,
            listas_por_contato=listas_por_contato,
            custo_projetado_total=custo.get("previsto_p50"),
            pct_acumulado=sum(float(o["pct"]) for o in launch.ondas[: launch.onda_atual]),
            tarifas=self._tarifas,
        )

    def _aplicar_disparos(self, launch: Launch, os_: OS, disparos: list[dict[str, Any]]) -> None:
        """Disparo ⇒ `pausado_breaker` AUTOMÁTICO (A1); SEV1 (lista de supressão) ⇒
        KILL AUTOMÁTICO (A2). Incidentes TIPADOS por breaker; tudo do SISTEMA (§10.6:
        zero LLM), via_ai=False."""
        launch.eventos.append(self._entrada("breaker_disparado", _ACTOR_SISTEMA, disparos=disparos))
        for disparo in disparos:
            self._abrir_incidente(
                os_,
                launch,
                sev=str(disparo["sev"]),
                tipo=str(disparo["breaker"]),
                titulo=f"Breaker {disparo['breaker']} disparado na onda {launch.onda_atual}",
                meta={"disparo": disparo},
                actor=_ACTOR_SISTEMA,
            )
        self._outbox(
            os_,
            "launch.breaker_tripped",  # §2.3
            _ACTOR_SISTEMA,
            {
                "launch_id": str(launch.id),
                "onda": launch.onda_atual,
                "breakers": [d["breaker"] for d in disparos],
            },
        )
        if any(d.get("kill") for d in disparos):  # A2: SEV1 + kill automático
            launch.estado = "morto"
            launch.eventos.append(self._entrada("kill_automatico", _ACTOR_SISTEMA))
            self._outbox(
                os_,
                "launch.killed",  # §2.3
                _ACTOR_SISTEMA,
                {
                    "launch_id": str(launch.id),
                    "automatico": True,
                    "motivo": "disparo_lista_supressao",
                },
            )
        else:
            launch.estado = "pausado_breaker"
        self._repo.salvar_launch(launch)

    def _aprovacoes_pendentes(self, launch: Launch) -> list[dict[str, Any]]:
        """Aprovações de retomada desde a última pausa/kill/retomada (histórico
        auditável em launch.eventos §4.1)."""
        aprovacoes: list[dict[str, Any]] = []
        for entrada in launch.eventos:
            if entrada["tipo"] in _MARCOS_RETOMADA or entrada["tipo"] == "kill_automatico":
                aprovacoes = []
            elif entrada["tipo"] == "retomada_aprovada":
                aprovacoes.append({"por": entrada["por"], "aprovador_id": entrada["aprovador_id"]})
        return aprovacoes

    def _abrir_incidente(
        self,
        os_: OS,
        launch: Launch | None,  # None = incidente da OS (ex.: reconciliação A3)
        *,
        sev: str,
        tipo: str,
        titulo: str,
        meta: dict[str, Any],
        actor: str,
    ) -> Incidente:
        incidente = Incidente(
            id=uuid.uuid4(),
            os_id=os_.id,
            launch_id=None if launch is None else launch.id,
            sev=sev,
            tipo=tipo,
            titulo=titulo,
            meta=meta,
            aberto_em=self._relogio.agora(),
        )
        self._repo.adicionar_incidente(incidente)
        self._outbox(
            os_,
            "incidente.aberto",
            actor,
            {"incidente_id": str(incidente.id), "sev": sev, "tipo": tipo},
        )
        return incidente

    def _entrada(self, tipo: str, actor: str, **extra: Any) -> dict[str, Any]:
        return {"tipo": tipo, "por": actor, "em": self._relogio.agora().isoformat(), **extra}

    def _outbox(self, os_: OS, tipo: str, actor: str, payload: dict[str, Any]) -> None:
        self._repo.adicionar_evento(
            EventoDominio(
                tenant_id=os_.tenant_id,
                os_id=os_.id,
                type=tipo,
                payload=payload,
                actor=actor,
                via_ai=False,  # caminho crítico determinístico (§10.6)
                created_at=self._relogio.agora(),
            )
        )

    def _launch_do_tenant(
        self, tenant_id: str, launch_id: uuid.UUID
    ) -> tuple[Launch, Snapshot, OS]:
        launch = self._repo.obter_launch(launch_id)
        if launch is not None:
            snapshot = self._repo.obter_snapshot(launch.snapshot_id)
            if snapshot is not None:
                os_ = self._repo.obter_os(tenant_id, snapshot.os_id)
                if os_ is not None:  # tenant errado não vaza existência
                    return launch, snapshot, os_
        raise NaoEncontrado(f"Launch {launch_id} não encontrado no tenant {tenant_id!r}.")

    def _snapshot_da_os(self, tenant_id: str, snapshot_id: uuid.UUID) -> tuple[Snapshot, OS]:
        snapshot = self._repo.obter_snapshot(snapshot_id)
        os_ = self._repo.obter_os(tenant_id, snapshot.os_id) if snapshot is not None else None
        if snapshot is None or os_ is None:
            raise NaoEncontrado(f"Snapshot {snapshot_id} não encontrado no tenant {tenant_id!r}.")
        return snapshot, os_
