"""Caso de uso do M9 · Compilador plan/apply (SDD §5.4, §8-M9) — DETERMINÍSTICO,
**LLM PROIBIDO em todo este caminho** (§5.4/§10.6): grafo → recursos é código puro
(domain/jornada/compilador.py); aqui entram apenas orquestração, guardas e I/O SFMC
atrás da porta (SFMCPort §2.1).

- `plan(snapshot, ambiente)` (§5.4.1): compila os recursos na ordem de dependência
  (DEs → EventDefs → Assets → Journey → Automations), consulta o estado real via
  porta e gera a lista `{recurso, acao: criar|alterar|manter|destruir, aviso?}`;
  registros órfãos (`resource_registry` de snapshot anterior da MESMA OS) viram
  `destruir` com aviso destrutivo obrigatório (§5.4.3). Persistido em `sync_run`.
- `apply` (§5.4.2): exige plan prévio (A1: 409), aprovação `aprovado|aprovado_
  ressalvas` não invalidada (§5.4.4 — a invalidação por custo M8-A4 roda antes) e
  certificado de elegibilidade VÁLIDO (M5-A3: expirado recusa). Executa na ordem com
  retry/backoff (tenacity) sobre `SfmcIndisponivel`, orçamento
  `SFMC_API_BUDGET_PER_APPLY` (§5.4.2) e IDEMPOTÊNCIA por externalKey (A3: recurso
  já existente e igual → 0 mutações). Falha → rollback compensatório (destrói o que
  ESTA run criou, em ordem inversa; recursos destruídos pelo plano não são
  restauráveis — por isso o aviso destrutivo é obrigatório). Tudo logado em
  `sync_run` + `resource_registry`; sucesso publica a versão do twin e emite
  `sync.applied` (§2.3).
"""

import uuid
from collections.abc import Awaitable, Callable
from typing import Any, cast

from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from application.ports.clock import ClockPort
from application.ports.repositorio_aprovacao import RepositorioAprovacao
from application.ports.repositorio_sync import RepositorioSync
from application.ports.sfmc import SfmcErro, SfmcIndisponivel, SFMCPort
from application.services.aprovacao_service import invalidar_aprovacoes_por_custo
from domain.campanha.erros import EstadoInvalido, NaoEncontrado
from domain.campanha.modelos import OS, EventoDominio
from domain.governanca.modelos import Snapshot
from domain.jornada.compilador import (
    AVISO_DESTRUIR_DE,
    AVISO_RECRIAR_EVENT_SOURCE,
    ORDEM_TIPOS,
    compilar_recursos,
)
from domain.jornada.erros import (
    AprovacaoNecessaria,
    CertificadoNecessario,
    OrcamentoEstourado,
    PrevooReprovado,
    SemPlanPrevio,
)
from domain.jornada.modelos import AMBIENTES_SYNC, JornadaVersao, ResourceRegistry, SyncRun

# SFMCPort por tipo de recurso: (obter, criar, destruir) — dispatch determinístico
_OPERACOES: dict[str, tuple[str, str, str]] = {
    "dataExtension": (
        "obter_data_extension",
        "criar_data_extension",
        "destruir_data_extension",
    ),
    "eventDefinition": (
        "obter_event_definition",
        "criar_event_definition",
        "destruir_event_definition",
    ),
    "asset": ("obter_asset", "criar_asset", "destruir_asset"),
    "journey": ("obter_interaction", "criar_interaction", "destruir_interaction"),
    "automation": ("obter_automation", "criar_automation", "destruir_automation"),
}

_RETRY_TENTATIVAS = 3  # §10.7: retries 2 (3 tentativas) com jitter


def _payload_contido(payload: dict[str, Any], existente: dict[str, Any]) -> bool:
    """Recurso existente 'igual' = todo campo do payload confere (extras do SFMC ok)."""
    return all(existente.get(chave) == valor for chave, valor in payload.items())


def _aviso_do_item(tipo_sfmc: str, acao: str) -> str | None:
    """Avisos destrutivos OBRIGATÓRIOS (§5.4.3)."""
    if tipo_sfmc == "eventDefinition" and acao in ("alterar", "destruir"):
        return AVISO_RECRIAR_EVENT_SOURCE
    if tipo_sfmc == "dataExtension" and acao in ("alterar", "destruir"):
        return AVISO_DESTRUIR_DE
    if acao == "destruir":
        return "DESTRUTIVO: recurso de snapshot anterior será removido do SFMC (§5.4.3)."
    return None


class _ExecutorSfmc:
    """Chamadas SFMC com retry/backoff (tenacity) e orçamento por run (§5.4.2)."""

    def __init__(self, sfmc: SFMCPort, orcamento: int) -> None:
        self._sfmc = sfmc
        self._orcamento = orcamento
        self.chamadas = 0
        self.orcamento_ativo = True  # rollback desliga (compensação deve concluir)

    async def _chamar(self, operacao: Callable[[], Awaitable[Any]]) -> Any:
        async for tentativa in AsyncRetrying(
            retry=retry_if_exception_type(SfmcIndisponivel),
            stop=stop_after_attempt(_RETRY_TENTATIVAS),
            wait=wait_exponential_jitter(initial=0.05, max=0.4),
            reraise=True,
        ):
            with tentativa:
                if self.orcamento_ativo and self.chamadas >= self._orcamento:
                    raise OrcamentoEstourado(
                        f"Orçamento SFMC_API_BUDGET_PER_APPLY ({self._orcamento}) "
                        "excedido — rollback compensatório (§5.4.2)."
                    )
                self.chamadas += 1
                return await operacao()
        return None  # inalcançável (reraise=True) — satisfaz o type checker

    async def obter(self, tipo_sfmc: str, chave: str) -> dict[str, Any] | None:
        nome, _, _ = _OPERACOES[tipo_sfmc]
        return cast(
            dict[str, Any] | None,
            await self._chamar(lambda: getattr(self._sfmc, nome)(chave)),
        )

    async def criar(self, tipo_sfmc: str, payload: dict[str, Any]) -> dict[str, Any]:
        _, nome, _ = _OPERACOES[tipo_sfmc]
        return cast(
            dict[str, Any],
            await self._chamar(lambda: getattr(self._sfmc, nome)(payload)),
        )

    async def destruir(self, tipo_sfmc: str, chave: str) -> bool:
        _, _, nome = _OPERACOES[tipo_sfmc]
        return bool(await self._chamar(lambda: getattr(self._sfmc, nome)(chave)))


class ServicoCompilador:
    def __init__(
        self,
        repositorio: RepositorioSync,
        sfmc: SFMCPort,
        relogio: ClockPort,
        orcamento_por_apply: int,
    ) -> None:
        self._repo = repositorio
        self._sfmc = sfmc
        self._relogio = relogio
        self._orcamento = orcamento_por_apply

    # ------------------------------------------- POST /snapshots/{id}/plan?ambiente=
    async def plan(
        self, tenant_id: str, snapshot_id: uuid.UUID, ambiente: str, *, actor: str
    ) -> SyncRun:
        snapshot, os_ = self._snapshot_da_os(tenant_id, snapshot_id)
        if ambiente not in AMBIENTES_SYNC:
            raise EstadoInvalido(f"Ambiente inválido: {ambiente!r} (§4.1 sync_run).")
        jornada = self._jornada_do_snapshot(snapshot, os_)
        hash_jgc = str(snapshot.conteudo["componentes"]["jgc"]["hash"])
        recursos = compilar_recursos(jornada.grafo, hash_jgc)  # §5.4.1 (código puro)

        executor = _ExecutorSfmc(self._sfmc, self._orcamento)
        plano: list[dict[str, Any]] = []
        for item in recursos:
            existente = await executor.obter(item["tipo_sfmc"], item["recurso"])
            if existente is None:
                acao = "criar"
            elif _payload_contido(item["payload"], existente):
                acao = "manter"  # idempotência por externalKey (§5.4.1/A3)
            else:
                acao = "alterar"
            plano.append({**item, "acao": acao, "aviso": _aviso_do_item(item["tipo_sfmc"], acao)})

        # Órfãos: registrados p/ esta OS neste ambiente e fora do plano → destruir
        chaves_atuais = {item["recurso"] for item in recursos}
        orfaos = [
            registro
            for registro in self._repo.listar_registros(tenant_id, ambiente)
            if registro.external_key not in chaves_atuais and self._registro_da_os(registro, os_)
        ]
        orfaos.sort(  # ordem INVERSA de dependência (destruir com segurança)
            key=lambda r: (-ORDEM_TIPOS.index(r.tipo_sfmc), r.external_key)
        )
        plano.extend(
            {
                "recurso": registro.external_key,
                "tipo_sfmc": registro.tipo_sfmc,
                "no_jgc": registro.no_jgc,
                "payload": None,
                "acao": "destruir",
                "aviso": _aviso_do_item(registro.tipo_sfmc, "destruir"),
            }
            for registro in orfaos
        )

        run = SyncRun(
            id=uuid.uuid4(),
            snapshot_id=snapshot.id,
            ambiente=ambiente,
            fase="plan",
            plano=plano,
            resultado={
                "acoes": {
                    acao: sum(1 for i in plano if i["acao"] == acao)
                    for acao in ("criar", "alterar", "manter", "destruir")
                }
            },
            estado="ok",
            api_calls=executor.chamadas,
            created_at=self._relogio.agora(),
        )
        self._repo.adicionar_sync_run(run)
        return run

    # ------------------------------------------ POST /snapshots/{id}/apply?ambiente=
    async def apply(
        self, tenant_id: str, snapshot_id: uuid.UUID, ambiente: str, *, actor: str
    ) -> SyncRun:
        snapshot, os_ = self._snapshot_da_os(tenant_id, snapshot_id)
        planos = self._repo.listar_sync_runs(snapshot.id, ambiente=ambiente, fase="plan")
        if not planos:  # A1
            raise SemPlanPrevio(
                f"Apply sem plan prévio para o snapshot {snapshot.id} em "
                f"{ambiente!r} — rode POST /snapshots/{{id}}/plan antes (§8-M9-A1)."
            )
        plano = list(planos[-1].plano or [])
        self._exigir_aprovacao(os_, snapshot)  # §5.4.4
        self._exigir_certificado_valido(os_)  # M5-A3
        self._exigir_prevoo(snapshot, ambiente)  # §8-M9: fail bloqueia; prod exige (§5.4.4)

        run = SyncRun(
            id=uuid.uuid4(),
            snapshot_id=snapshot.id,
            ambiente=ambiente,
            fase="apply",
            plano=plano,
            estado="pendente",
            created_at=self._relogio.agora(),
        )
        self._repo.adicionar_sync_run(run)

        executor = _ExecutorSfmc(self._sfmc, self._orcamento)
        criados: list[tuple[str, str]] = []  # (tipo_sfmc, chave) — rollback §5.4.2
        recursos_resultado: list[dict[str, Any]] = []
        mutacoes = 0
        try:
            for item in plano:
                if item["acao"] == "destruir":
                    continue  # destruição por último (ordem inversa, abaixo)
                executado, delta = await self._executar_item(
                    executor, tenant_id, ambiente, snapshot, item, criados
                )
                mutacoes += delta
                recursos_resultado.append(
                    {
                        "recurso": item["recurso"],
                        "tipo_sfmc": item["tipo_sfmc"],
                        "acao_planejada": item["acao"],
                        "acao_executada": executado,
                    }
                )
            for item in plano:
                if item["acao"] != "destruir":
                    continue
                destruido = await executor.destruir(item["tipo_sfmc"], item["recurso"])
                if destruido:
                    mutacoes += 1
                    self._repo.remover_registro(tenant_id, ambiente, item["recurso"])
                recursos_resultado.append(
                    {
                        "recurso": item["recurso"],
                        "tipo_sfmc": item["tipo_sfmc"],
                        "acao_planejada": "destruir",
                        "acao_executada": "destruido" if destruido else "ausente",
                    }
                )
        except (SfmcErro, OrcamentoEstourado) as exc:
            run.estado = await self._rollback(executor, tenant_id, ambiente, criados)
            run.resultado = {
                "erro": str(exc),
                "mutacoes": mutacoes,
                "recursos": recursos_resultado,
                "revertidos": [chave for _, chave in reversed(criados)],
            }
            run.api_calls = executor.chamadas
            self._repo.salvar_sync_run(run)
            return run

        run.estado = "ok"
        run.resultado = {"mutacoes": mutacoes, "recursos": recursos_resultado}
        run.api_calls = executor.chamadas
        self._repo.salvar_sync_run(run)
        self._publicar_jornada(snapshot, os_)
        self._repo.adicionar_evento(
            EventoDominio(
                tenant_id=os_.tenant_id,
                os_id=os_.id,
                type="sync.applied",  # §2.3
                payload={
                    "sync_run_id": str(run.id),
                    "snapshot_id": str(snapshot.id),
                    "ambiente": ambiente,
                    "mutacoes": mutacoes,
                    "api_calls": run.api_calls,
                },
                actor=actor,
                via_ai=False,  # compilador é determinístico (§5.4)
                created_at=self._relogio.agora(),
            )
        )
        return run

    # ----------------------------------------------------- GET /sync-runs/{id}
    def obter_sync_run(self, tenant_id: str, sync_run_id: uuid.UUID) -> SyncRun:
        run = self._repo.obter_sync_run(sync_run_id)
        if run is not None:
            snapshot = self._repo.obter_snapshot(run.snapshot_id)
            if snapshot is not None and self._repo.obter_os(tenant_id, snapshot.os_id):
                return run
        raise NaoEncontrado(f"Sync run {sync_run_id} não encontrada no tenant {tenant_id!r}.")

    # ------------------------------------------------------------------- privados
    async def _executar_item(
        self,
        executor: _ExecutorSfmc,
        tenant_id: str,
        ambiente: str,
        snapshot: Snapshot,
        item: dict[str, Any],
        criados: list[tuple[str, str]],
    ) -> tuple[str, int]:
        """criar/alterar/manter com idempotência por externalKey (A3): o estado REAL
        é reconferido — existente e igual ⇒ `mantido` (0 mutações)."""
        tipo_sfmc, chave = str(item["tipo_sfmc"]), str(item["recurso"])
        payload = dict(item["payload"] or {})
        if item["acao"] == "manter":
            self._registrar(tenant_id, ambiente, snapshot, item, sfmc_id=None)
            return "mantido", 0
        existente = await executor.obter(tipo_sfmc, chave)
        if existente is not None and _payload_contido(payload, existente):
            self._registrar(tenant_id, ambiente, snapshot, item, sfmc_id=None)
            return "mantido", 0
        mutacoes = 0
        executado = "criado"
        if existente is not None:  # alterar = recriar (aviso §5.4.3 veio do plan)
            await executor.destruir(tipo_sfmc, chave)
            mutacoes += 1
            executado = "recriado"
        criado = await executor.criar(tipo_sfmc, payload)
        mutacoes += 1
        criados.append((tipo_sfmc, chave))
        sfmc_id = criado.get("id") or criado.get("objectId")
        self._registrar(
            tenant_id,
            ambiente,
            snapshot,
            item,
            sfmc_id=str(sfmc_id) if sfmc_id is not None else None,
        )
        return executado, mutacoes

    async def _rollback(
        self,
        executor: _ExecutorSfmc,
        tenant_id: str,
        ambiente: str,
        criados: list[tuple[str, str]],
    ) -> str:
        """Compensação §5.4.2: destrói o que ESTA run criou, em ordem inversa."""
        executor.orcamento_ativo = False  # a compensação deve concluir (§5.4.2)
        estado = "revertido"
        for tipo_sfmc, chave in reversed(criados):
            try:
                await executor.destruir(tipo_sfmc, chave)
                self._repo.remover_registro(tenant_id, ambiente, chave)
            except SfmcErro:
                estado = "parcial"  # compensação incompleta fica registrada
        return estado

    def _exigir_aprovacao(self, os_: OS, snapshot: Snapshot) -> None:
        """§5.4.4: decisão aprovado|aprovado_ressalvas VÁLIDA (não invalidada — a
        checagem de variação de custo M8-A4 roda antes, lazy)."""
        invalidar_aprovacoes_por_custo(cast(RepositorioAprovacao, self._repo), os_, self._relogio)
        validas = [
            aprovacao
            for aprovacao in self._repo.listar_aprovacoes(snapshot.id)
            if aprovacao.decisao in ("aprovado", "aprovado_ressalvas")
            and aprovacao.invalidada_em is None
        ]
        if not validas:
            raise AprovacaoNecessaria(
                "Apply exige aprovação `aprovado|aprovado_ressalvas` válida do snapshot "
                "(link mágico §8-M8) — §5.4.4/§8-M9."
            )

    def _exigir_prevoo(self, snapshot: Snapshot, ambiente: str) -> None:
        """§8-M9 (fatia 2): pré-voo com FAIL (`vermelho`) BLOQUEIA o apply em qualquer
        ambiente; em PROD o pré-voo é OBRIGATÓRIO e não-vermelho (§5.4.4 — 'apply em
        prod exige ... pre-flight verde'; warns são registrados e não bloqueiam)."""
        runs = self._repo.listar_preflights(snapshot.id, ambiente)
        ultimo = runs[-1] if runs else None
        if ultimo is not None and ultimo.resultado == "vermelho":
            falhas = [i["item"] for i in ultimo.itens if i["status"] == "fail"]
            raise PrevooReprovado(
                "Apply bloqueado: pré-voo VERMELHO para o snapshot neste ambiente "
                f"(falhas: {', '.join(falhas)}) — corrija e rode POST /preflight de novo "
                "(§8-M9)."
            )
        if ambiente == "prod" and ultimo is None:
            raise PrevooReprovado(
                "Apply em prod exige pré-voo executado e sem falhas — rode "
                "POST /preflight/{snapshot}?ambiente=prod antes (§5.4.4/§8-M9)."
            )

    def _exigir_certificado_valido(self, os_: OS) -> None:
        """M5-A3: publish recusa certificado expirado (ou ausente)."""
        certificados = self._repo.listar_certificados(os_.id)
        if not certificados:
            raise CertificadoNecessario(
                "Apply exige certificado de elegibilidade (Guard M5) — nenhum emitido."
            )
        certificado = max(certificados, key=lambda c: c.emitido_em)
        if certificado.valido_ate is not None and self._relogio.agora() > certificado.valido_ate:
            raise CertificadoNecessario(
                "Certificado de elegibilidade EXPIRADO — re-certifique (M5-A3)."
            )

    def _registrar(
        self,
        tenant_id: str,
        ambiente: str,
        snapshot: Snapshot,
        item: dict[str, Any],
        *,
        sfmc_id: str | None,
    ) -> None:
        """Upsert no `resource_registry` (§4.1) — preserva sfmc_id quando 'mantido'."""
        anterior = self._repo.obter_registro(tenant_id, ambiente, str(item["recurso"]))
        self._repo.upsert_registro(
            ResourceRegistry(
                id=anterior.id if anterior else uuid.uuid4(),
                tenant_id=tenant_id,
                no_jgc=str(item["no_jgc"]),
                tipo_sfmc=str(item["tipo_sfmc"]),
                external_key=str(item["recurso"]),
                sfmc_id=sfmc_id or (anterior.sfmc_id if anterior else None),
                ambiente=ambiente,
                snapshot_hash=snapshot.hash,
            )
        )

    def _registro_da_os(self, registro: ResourceRegistry, os_: OS) -> bool:
        """Órfão só é destruído se pertencer a snapshot DESTA OS (escopo §4.1)."""
        if not registro.snapshot_hash:
            return False
        snapshot = self._repo.obter_snapshot_por_hash(registro.snapshot_hash)
        return snapshot is not None and snapshot.os_id == os_.id

    def _snapshot_da_os(self, tenant_id: str, snapshot_id: uuid.UUID) -> tuple[Snapshot, OS]:
        snapshot = self._repo.obter_snapshot(snapshot_id)
        os_ = self._repo.obter_os(tenant_id, snapshot.os_id) if snapshot is not None else None
        if snapshot is None or os_ is None:  # tenant errado não vaza existência
            raise NaoEncontrado(f"Snapshot {snapshot_id} não encontrado no tenant {tenant_id!r}.")
        return snapshot, os_

    def _jornada_do_snapshot(self, snapshot: Snapshot, os_: OS) -> JornadaVersao:
        jornada_id = uuid.UUID(str(snapshot.conteudo["componentes"]["jgc"]["jornada_id"]))
        jornada = next((j for j in self._repo.listar_jornadas(os_.id) if j.id == jornada_id), None)
        if jornada is None:
            raise NaoEncontrado(
                f"Versão de jornada {jornada_id} do snapshot não encontrada (§4.1)."
            )
        return jornada

    def _publicar_jornada(self, snapshot: Snapshot, os_: OS) -> None:
        """Apply ok ⇒ versão do twin `publicado` (§4.1 jornada_versao.estado)."""
        jornada = self._jornada_do_snapshot(snapshot, os_)
        jornada.estado = "publicado"
        self._repo.salvar_jornada(jornada)
