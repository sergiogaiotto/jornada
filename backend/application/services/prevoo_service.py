"""Caso de uso do M9 (fatia 2) · Pré-voo T11 (SDD §8-M9) — bateria pass/warn/fail com
evidência, DETERMINÍSTICA e **SEM LLM em nenhum ponto** (§5.4/§10.6).

`POST /preflight/{snapshot}?ambiente=` executa os 8 itens do §8-M9 e persiste
`preflight_run` (tabela auxiliar — migração 0007); FAIL ⇒ `vermelho` BLOQUEIA o apply
(gate no compilador_service); apply em prod exige pré-voo executado e não-vermelho
(§5.4.4). Itens:

1. `des_schema` — DEs compiladas × estado real (SFMCPort): ausente ⇒ warn (o apply
   cria), schema sem os campos esperados ⇒ fail.
2. `frescor_hybris` — fixture do read model (§11): ciclo D-1 (24h — §8-M5-A4).
3. `opt_in` — todo `channel.*` do JGC com opt-in configurado (§5.3).
4. `listas_last_mile` — RE-VARREDURA das 7 listas + opt-in via Guard determinístico
   (agents/guard §8-M5) sobre o SQL público do segmento; resultado gravado em
   `certificado_elegibilidade.last_mile` (§4.1).
5. `lint_ampscript` — lint simples sobre células de criativos e assets compilados.
6. `limites_sfmc` — limites verificáveis por código (domain/jornada/prevoo.py).
7. `drift_zero` — job de drift on-demand (ServicoDrift §5.4.5) restrito à OS: qualquer
   drift no ambiente ⇒ fail (e, em prod, a pendência automática A4 já é aberta).
8. `seed_dry_run` — seed sintética validada contra o schema da DE de entrada (DRY-RUN:
   nada é gravado no SFMC); DE ainda não materializada ⇒ warn.

Evento §2.3: `gate.passed|blocked` com portao=`preflight`.
"""

import uuid
from typing import Any

from agents.guard import elegibilidade as guard
from application.ports.clock import ClockPort
from application.ports.read_model_audiencia import ReadModelAudienciaPort
from application.ports.repositorio_sync import RepositorioSync
from application.ports.sfmc import SFMCPort
from application.services.drift_service import ServicoDrift
from domain.campanha.erros import EstadoInvalido, NaoEncontrado
from domain.campanha.modelos import OS, EventoDominio
from domain.governanca.modelos import Snapshot
from domain.jornada import prevoo as regras
from domain.jornada.compilador import chave_journey, compilar_recursos
from domain.jornada.modelos import AMBIENTES_SYNC, JornadaVersao, PreflightRun


class ServicoPrevoo:
    def __init__(
        self,
        repositorio: RepositorioSync,
        sfmc: SFMCPort,
        relogio: ClockPort,
        read_model: ReadModelAudienciaPort,
        drift: ServicoDrift,
    ) -> None:
        self._repo = repositorio
        self._sfmc = sfmc
        self._relogio = relogio
        self._read_model = read_model
        self._drift = drift

    # ------------------------------------------- POST /preflight/{snapshot}?ambiente=
    async def executar(
        self, tenant_id: str, snapshot_id: uuid.UUID, ambiente: str, *, actor: str
    ) -> PreflightRun:
        snapshot, os_ = self._snapshot_da_os(tenant_id, snapshot_id)
        if ambiente not in AMBIENTES_SYNC:
            raise EstadoInvalido(f"Ambiente inválido: {ambiente!r} (§4.1 sync_run).")
        jornada = self._jornada_do_snapshot(snapshot, os_)
        hash_jgc = str(snapshot.conteudo["componentes"]["jgc"]["hash"])
        recursos = compilar_recursos(jornada.grafo, hash_jgc)  # §5.4.1 (código puro)

        itens = [
            await self._item_des_schema(recursos),
            regras.checar_frescor_hybris(self._frescor()),
            regras.checar_opt_in(jornada.grafo),
            self._item_listas_last_mile(os_, ambiente),
            regras.checar_lint_ampscript(self._conteudos_ampscript(os_, recursos)),
            regras.checar_limites_sfmc(recursos),
            await self._item_drift_zero(tenant_id, os_, ambiente, actor),
            await self._item_seed_dry_run(recursos, hash_jgc),
        ]
        run = PreflightRun(
            id=uuid.uuid4(),
            snapshot_id=snapshot.id,
            ambiente=ambiente,
            resultado=regras.semaforo(itens),
            itens=itens,
            created_at=self._relogio.agora(),
        )
        self._repo.adicionar_preflight(run)
        self._evento(
            os_,
            "gate.blocked" if run.resultado == "vermelho" else "gate.passed",  # §2.3
            {
                "portao": "preflight",
                "preflight_id": str(run.id),
                "snapshot_id": str(snapshot.id),
                "ambiente": ambiente,
                "resultado": run.resultado,
                "falhas": [i["item"] for i in itens if i["status"] == "fail"],
            },
            actor,
        )
        return run

    # ------------------------------------------------------------------- itens (I/O)
    async def _item_des_schema(self, recursos: list[dict[str, Any]]) -> dict[str, Any]:
        """Item 1 — DEs/schema: existência e campos esperados ⊆ campos reais."""
        detalhes: list[dict[str, Any]] = []
        status = "pass"
        for recurso in recursos:
            if recurso["tipo_sfmc"] != "dataExtension":
                continue
            chave = recurso["recurso"]
            real = await self._sfmc.obter_data_extension(chave)
            if real is None:
                detalhes.append({"de": chave, "status": "warn", "detalhe": "criada no apply"})
                status = "fail" if status == "fail" else "warn"
                continue
            esperados = {(c["name"], c["fieldType"]) for c in recurso["payload"].get("fields", [])}
            reais = {(c.get("name"), c.get("fieldType")) for c in (real.get("fields") or [])}
            faltantes = sorted(nome for nome, _ in esperados - reais)
            if faltantes:
                detalhes.append({"de": chave, "status": "fail", "campos_faltantes": faltantes})
                status = "fail"
            else:
                detalhes.append({"de": chave, "status": "pass", "campos": len(reais)})
        return regras.item("des_schema", status, {"data_extensions": detalhes})

    def _frescor(self) -> dict[str, Any]:
        """Frescor por fonte do read model (fixtures §11 — Hybris D-1)."""
        dados = self._read_model.contagens_segmentacao("")
        return dict(dados.get("frescor") or {})

    def _item_listas_last_mile(self, os_: OS, ambiente: str) -> dict[str, Any]:
        """Item 4 — re-varredura last-mile das 7 listas + opt-in via Guard (§8-M5)."""
        segmentos = self._repo.listar_segmentos(os_.id)
        if not segmentos:
            return regras.item(
                "listas_last_mile",
                "fail",
                {"detalhe": "OS sem segmento — nada a varrer (Guard §8-M5)."},
            )
        segmento = segmentos[-1]
        agora = self._relogio.agora()
        if segmento.origem == "data_cloud" and not segmento.sql_publico:
            resultado = regras.item(
                "listas_last_mile",
                "warn",
                {
                    "segmento_id": str(segmento.id),
                    "detalhe": "origem data_cloud sem SQL público: listas aplicadas na "
                    "origem (lineage T5a) — varredura textual indisponível.",
                },
            )
        else:
            faltantes, problemas = guard.problemas_no_sql(segmento.sql_publico)
            resultado = regras.item(
                "listas_last_mile",
                "fail" if problemas else "pass",
                {
                    "segmento_id": str(segmento.id),
                    "listas_faltantes": faltantes,
                    "problemas": problemas,
                },
            )
        # §4.1: re-varredura no disparo fica registrada no certificado (last_mile)
        certificados = self._repo.listar_certificados(os_.id)
        if certificados:
            certificado = max(certificados, key=lambda c: c.emitido_em)
            certificado.last_mile = {
                "varrido_em": agora.isoformat(),
                "ambiente": ambiente,
                "status": resultado["status"],
                "evidencia": resultado["evidencia"],
            }
            # A7 parte 2: mutação explícita persistida (com SQL o objeto é uma cópia)
            self._repo.salvar_certificado(certificado)
        return resultado

    def _conteudos_ampscript(self, os_: OS, recursos: list[dict[str, Any]]) -> dict[str, str]:
        """Item 5 — textos a lintar: células de criativos (M6) + content dos assets."""
        conteudos: dict[str, str] = {}
        for recurso in recursos:
            if recurso["tipo_sfmc"] == "asset":
                conteudos[f"asset:{recurso['recurso']}"] = str(
                    recurso["payload"].get("content", "")
                )
        for criativo in self._repo.listar_criativos(os_.id):
            for celula in criativo.celulas:
                texto = " ".join(str(v) for v in celula.conteudo.values())
                conteudos[f"criativo:{celula.canal}:{celula.variante}"] = texto
        return conteudos

    async def _item_drift_zero(
        self, tenant_id: str, os_: OS, ambiente: str, actor: str
    ) -> dict[str, Any]:
        """Item 7 — drift=0 no ambiente (job on-demand §5.4.5 restrito à OS)."""
        checks = await self._drift.verificar(
            tenant_id, ambiente=ambiente, os_id=os_.id, actor=actor
        )
        com_drift = [c for c in checks if c.estado != "em_sincronia"]
        return regras.item(
            "drift_zero",
            "fail" if com_drift else "pass",
            {
                "verificados": len(checks),
                "com_drift": [{"recurso": c.recurso, "estado": c.estado} for c in com_drift],
            },
        )

    async def _item_seed_dry_run(
        self, recursos: list[dict[str, Any]], hash_jgc: str
    ) -> dict[str, Any]:
        """Item 8 — seed sintética validada contra o schema da DE de entrada (DRY-RUN:
        nenhuma linha é gravada; a seed usa contato sintético, jamais PII — §10.2)."""
        entradas = [
            r
            for r in recursos
            if r["tipo_sfmc"] == "eventDefinition" and r["payload"].get("dataExtensionName")
        ]
        if not entradas:
            return regras.item(
                "seed_dry_run", "fail", {"detalhe": "grafo sem entrySource com deRef (§5.2)."}
            )
        seed = {"SubscriberKey": f"seed-{chave_journey(hash_jgc)}"}
        detalhes: list[dict[str, Any]] = []
        status = "pass"
        for entrada in entradas:
            de_ref = str(entrada["payload"]["dataExtensionName"])
            real = await self._sfmc.obter_data_extension(de_ref)
            if real is None:
                detalhes.append(
                    {
                        "de": de_ref,
                        "status": "warn",
                        "detalhe": "dry-run adiado: DE criada no apply",
                    }
                )
                status = "fail" if status == "fail" else "warn"
                continue
            colunas = {c.get("name") for c in (real.get("fields") or [])}
            fora_do_schema = sorted(campo for campo in seed if campo not in colunas)
            if fora_do_schema:
                detalhes.append(
                    {"de": de_ref, "status": "fail", "campos_fora_do_schema": fora_do_schema}
                )
                status = "fail"
            else:
                detalhes.append({"de": de_ref, "status": "pass", "seed": seed})
        return regras.item("seed_dry_run", status, {"entradas": detalhes})

    # ------------------------------------------------------------------- privados
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

    def _evento(self, os_: OS, tipo: str, payload: dict[str, Any], actor: str) -> None:
        self._repo.adicionar_evento(
            EventoDominio(
                tenant_id=os_.tenant_id,
                os_id=os_.id,
                type=tipo,
                payload=payload,
                actor=actor,
                via_ai=False,  # §5.4: pré-voo 100% determinístico
                created_at=self._relogio.agora(),
            )
        )
