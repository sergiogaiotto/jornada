"""Casos de uso do M5 · Audiência (T5) + Guard + Data Cloud (T5a) — via ports (§8-M5).

- `gerar_sql` (POST /os/{id}/segmento/gerar-sql): agente engineer (LLM 120b — roster
  §7.2) gera SQL público; guarda-corpos determinísticos em agents/engineer.py; ledger
  `invocacao` (via_ai) + evento `agent.invoked` + trace Langfuse (§10.8). O Guard faz
  PRÉ-CHECK informativo (avisos); a reprovação dura acontece na certificação (A1).
- `recontar` (POST /segmentos/{id}/recontar): DRY-RUN no read model (fixtures §11) —
  waterfall + líquido + volume de abordagem por canal (A2) + frescor por fonte (A4).
- `definir_holdout` (PUT /segmentos/{id}/holdout): respeita `holdout_min` da política.
- `certificar` (POST /segmentos/{id}/certificar): GUARD DETERMINÍSTICO (zero LLM —
  §10.6 caminho crítico): varre as 7 listas + opt-in no WHERE (A1), conta suprimidos e
  emite `certificado_elegibilidade` com hash/validade (A3).
- Data Cloud (T5a — consulta, não cópia): `listar_segmentos_dc` (cache+frescor),
  `relatorio_dc` (bruto→elegível→líquido→sobreposição + volume por canal pós
  caps/quiet/colisões — colisões vêm do governor, A2), `usar_segmento_dc` (vira
  `segmento` origem data_cloud com lineage).
Eventos (§2.3): agent.invoked · segmento.recontado · segmento.holdout_definido ·
gate.passed|blocked (portão guard) · certificado.emitido · datacloud.segmento_usado.
"""

import uuid
from datetime import datetime, timedelta
from typing import Any

from agents import engineer as agente_engineer
from agents.guard import elegibilidade as guard
from application.ports.clock import ClockPort
from application.ports.datacloud import DataCloudPort
from application.ports.llm import LLMPort
from application.ports.observabilidade import TracerPort
from application.ports.publicacoes import PublicacoesPort, politica_vigente
from application.ports.publicacoes_ia import PublicacoesIaPort
from application.ports.read_model_audiencia import ReadModelAudienciaPort
from application.ports.repositorio_audiencia import RepositorioAudiencia
from application.services import portao_ia
from application.services.os_service import ServicoOs
from application.services.retriever_service import RetrieverService, evidencias_para_contexto
from domain.agentes.modelos import Invocacao, agente_uuid
from domain.audiencia import waterfall as regras
from domain.audiencia.erros import (
    CertificadoReprovado,
    SaidaDoEngineerInvalida,
    SegmentoSemSql,
)
from domain.audiencia.modelos import (
    HOLDOUT_PCT_DEFAULT,
    CertificadoElegibilidade,
    DcSegmentCache,
    Segmento,
)
from domain.campanha.erros import NaoEncontrado
from domain.campanha.modelos import OS, EventoDominio


class ServicoAudiencia:
    def __init__(
        self,
        repositorio: RepositorioAudiencia,
        relogio: ClockPort,
        servico_os: ServicoOs,
        llm: LLMPort,
        tracer: TracerPort,
        datacloud: DataCloudPort,
        read_model: ReadModelAudienciaPort,
        publicacoes: PublicacoesPort,
        publicacoes_ia: PublicacoesIaPort,
        retriever: RetrieverService | None = None,
    ) -> None:
        self._repo = repositorio
        self._relogio = relogio
        self._servico_os = servico_os
        self._llm = llm
        self._tracer = tracer
        self._datacloud = datacloud
        self._read_model = read_model
        self._publicacoes = publicacoes
        self._publicacoes_ia = publicacoes_ia  # política de IA PUBLICADA (§10.2)
        self._retriever = retriever  # A11: preparar_contexto RAG (§7.3); None → sem RAG

    # ------------------------------------------------------------ Estúdio SQL
    def gerar_sql(
        self, tenant_id: str, os_id: uuid.UUID, *, instrucoes: str, portador_id: uuid.UUID
    ) -> tuple[Segmento, agente_engineer.SaidaEngineer, list[str], Invocacao]:
        """POST /os/{id}/segmento/gerar-sql — engineer via LLMPort (§8-M5).

        §10.2 (C02): instruções saneadas na fronteira — prompt, embedding do RAG,
        `criterios_resumo` do segmento e ledger recebem só o texto sanitizado. `sanear`
        mantém o piso do C02 e passa a BLOQUEAR quando a política do tenant marcar a
        categoria detectada."""
        portao = portao_ia.de(self._publicacoes_ia, tenant_id)  # política PUBLICADA
        instrucoes = portao.sanear(instrucoes)
        os_ = self._servico_os.obter_os(tenant_id, os_id)  # NaoEncontrado → 404
        skill = agente_engineer.carregar()
        # A11 (§7.3): preparar_contexto — top-k=8 nas bases autorizadas da skill;
        # hub de embeddings fora → [] (degrade suave, o guarda-corpo exige_evidencia
        # continua valendo sobre o que o modelo citar).
        evidencias_rag = (
            self._retriever.buscar(tenant_id, instrucoes, bases=skill.bases_rag)
            if self._retriever is not None
            else []
        )
        mensagens = agente_engineer.montar_mensagens(
            skill, os_.briefing, instrucoes, evidencias_rag=evidencias_para_contexto(evidencias_rag)
        )
        inicio = self._relogio.agora()
        # (f) §7.2: perfil do roster CONFERIDO contra a política antes da chamada.
        portao.autorizar_modelo(skill.nome, skill.modelo_perfil)
        texto = self._llm.chat(mensagens, perfil=skill.modelo_perfil)  # LLMIndisponivel → 503
        fim = self._relogio.agora()
        saida = agente_engineer.interpretar_saida(texto, exige_evidencia=skill.exige_evidencia)
        if saida.sql is None:  # guarda-corpo §1.3.5: nada é inventado
            raise SaidaDoEngineerInvalida(
                "Engineer não devolveu SQL utilizável "
                "(JSON malformado, SQL vazio ou sem evidências — §7.1 exige_evidencia). "
                + (f"Resposta do agente: {saida.resposta}" if saida.resposta else "")
            )

        # Pré-check INFORMATIVO do Guard (prévia §1.1.3; a certificação reprova de fato)
        _, avisos = guard.problemas_no_sql(saida.sql)

        segmento = Segmento(
            id=uuid.uuid4(),
            os_id=os_.id,
            origem="estudio_sql",
            sql_publico=saida.sql,
            criterios_resumo=instrucoes.strip() or None,
            holdout_pct=float(self._politica(os_).get("holdout_min", HOLDOUT_PCT_DEFAULT)),
        )
        self._repo.adicionar_segmento(segmento)

        invocacao = self._registrar_invocacao(
            os_, skill, instrucoes, saida, portador_id, inicio, fim, portao
        )
        self._tracer.trace(  # §10.8: fire-and-forget, trace_id = invocacao.id
            trace_id=str(invocacao.id),
            nome="engineer.gerar_sql",
            metadados={
                "tenant": tenant_id,
                "os_id": str(os_.id),
                "agente": skill.nome,
                "skill_versao": skill.versao,
                "modelo_perfil": skill.modelo_perfil,
            },
            spans=[
                {"nome": "rag_retrieve", "evidencias": len(evidencias_rag)},  # §10.8
                {"nome": "generate", "latencia_ms": invocacao.latencia_ms},
            ],
        )
        return segmento, saida, avisos, invocacao

    def recontar(self, tenant_id: str, segmento_id: uuid.UUID, *, actor: str) -> Segmento:
        """POST /segmentos/{id}/recontar — dry-run no read model (§8-M5): waterfall +
        líquido (A2) + volume por canal + frescor por fonte (A4)."""
        segmento, os_ = self._exigir_segmento(tenant_id, segmento_id)
        contagens = self._contagens(segmento)
        agora = self._relogio.agora()

        etapas, bruto, liquido = regras.montar_waterfall(contagens)
        segmento.contagem_bruta = bruto
        segmento.contagem_liquida = liquido
        segmento.waterfall = etapas
        segmento.volume_abordagem = regras.volume_de_abordagem(
            liquido, dict(contagens.get("canais") or {})
        )
        segmento.frescor = regras.frescor_por_fonte(dict(contagens.get("frescor") or {}), agora)
        self._repo.salvar_segmento(segmento)
        self._evento(
            os_,
            "segmento.recontado",
            {
                "segmento_id": str(segmento.id),
                "bruto": bruto,
                "liquido": liquido,
                "origem": segmento.origem,
            },
            actor,
        )
        return segmento

    def definir_holdout(
        self, tenant_id: str, segmento_id: uuid.UUID, *, holdout_pct: float, actor: str
    ) -> Segmento:
        """PUT /segmentos/{id}/holdout — valida contra holdout_min da política (§4.1)."""
        segmento, os_ = self._exigir_segmento(tenant_id, segmento_id)
        holdout_min = float(self._politica(os_).get("holdout_min", HOLDOUT_PCT_DEFAULT))
        regras.validar_holdout(holdout_pct, holdout_min)  # HoldoutForaDaPolitica → 422
        segmento.holdout_pct = holdout_pct
        self._repo.salvar_segmento(segmento)
        self._evento(
            os_,
            "segmento.holdout_definido",
            {"segmento_id": str(segmento.id), "holdout_pct": holdout_pct},
            actor,
        )
        return segmento

    # ------------------------------------------------------------------ Guard
    def certificar(
        self, tenant_id: str, segmento_id: uuid.UUID, *, actor: str
    ) -> CertificadoElegibilidade:
        """POST /segmentos/{id}/certificar — GUARD DETERMINÍSTICO (zero LLM, §7.2):
        varre 7 listas + opt-in (A1) e emite certificado com hash/validade (A3)."""
        segmento, os_ = self._exigir_segmento(tenant_id, segmento_id)
        try:
            if segmento.origem == "estudio_sql":
                guard.validar_sql_de_segmentacao(segmento.sql_publico)  # A1
        except CertificadoReprovado as exc:
            self._evento(
                os_,
                "gate.blocked",
                {
                    "portao": "guard",
                    "segmento_id": str(segmento.id),
                    "listas_faltantes": exc.listas_faltantes,
                    "problemas": exc.problemas,
                },
                actor,
            )
            raise

        contagens = self._contagens(segmento)  # varredura das listas (contagens por lista)
        _, _, liquido = regras.montar_waterfall(contagens)
        agora = self._relogio.agora()
        certificado = guard.emitir_certificado(
            os_id=os_.id,
            segmento_id=segmento.id,
            sql_publico=segmento.sql_publico,
            suprimidos=regras.suprimidos_por_lista(contagens),
            liquido=liquido,
            agora=agora,
        )
        self._repo.adicionar_certificado(certificado)
        self._evento(
            os_,
            "gate.passed",
            {"portao": "guard", "segmento_id": str(segmento.id), "hash": certificado.hash},
            actor,
        )
        self._evento(
            os_,
            "certificado.emitido",
            {
                "certificado_id": str(certificado.id),
                "hash": certificado.hash,
                "liquido": certificado.liquido,
                "valido_ate": (
                    certificado.valido_ate.isoformat() if certificado.valido_ate else None
                ),
            },
            actor,
        )
        return certificado

    # ------------------------------------------------------- Data Cloud (T5a)
    def listar_segmentos_dc(self, tenant_id: str) -> list[DcSegmentCache]:
        """GET /datacloud/segmentos — consulta a porta e atualiza `dc_segment_cache`
        (cache+frescor §8-M5; consulta, não cópia)."""
        agora = self._relogio.agora()
        entradas: list[DcSegmentCache] = []
        for bruto in self._datacloud.segmentos():
            entrada = self._entrada_cache(tenant_id, bruto, agora)
            self._repo.salvar_dc_cache(entrada)
            entradas.append(entrada)
        return entradas

    def relatorio_dc(self, tenant_id: str, segmento_id: str) -> dict[str, Any]:
        """GET /datacloud/segmentos/{id}/relatorio — bruto→elegível→líquido→sobreposição
        + volume de abordagem por canal pós caps/quiet/colisões (A2) + frescor (A4)."""
        segmento = self._datacloud.segmento(segmento_id)
        relatorio = self._datacloud.relatorio(segmento_id)
        if segmento is None or relatorio is None:
            raise NaoEncontrado(f"Segmento {segmento_id!r} não existe no Data Cloud (T5a).")
        agora = self._relogio.agora()
        entrada = self._entrada_cache(tenant_id, segmento, agora)
        self._repo.salvar_dc_cache(entrada)  # consulta atualiza o cache

        contagens = {**relatorio, "bruto": int(segmento.get("membros", 0))}
        etapas, bruto, liquido = regras.montar_waterfall(contagens)
        canais = dict(contagens.get("canais") or {})
        return {
            "segmento": {
                "id": entrada.id,
                "nome": entrada.nome,
                "criterios_resumo": entrada.criterios_resumo,
                "dmos": entrada.dmos,
                "ciclo": entrada.ciclo,
                "status": entrada.status,
                "republicado_em": (
                    entrada.republicado_em.isoformat() if entrada.republicado_em else None
                ),
            },
            "funil": {
                "bruto": bruto,
                "elegivel": int(contagens.get("elegivel", bruto)),
                "liquido": liquido,
            },
            "waterfall": etapas,
            "sobreposicao": dict(contagens.get("sobreposicao") or {}),
            "volume_abordagem": regras.volume_de_abordagem(liquido, canais),
            "colisoes": regras.colisoes_por_canal(canais),  # A2: vêm do governor
            "frescor": regras.frescor_por_fonte(dict(contagens.get("frescor") or {}), agora),
        }

    def usar_segmento_dc(
        self, tenant_id: str, segmento_id: str, *, os_id: uuid.UUID, actor: str
    ) -> Segmento:
        """POST /datacloud/segmentos/{id}/usar — vira `segmento` origem data_cloud com
        lineage (dc_segment_id + critérios + contagens/frescor da consulta)."""
        os_ = self._servico_os.obter_os(tenant_id, os_id)
        relatorio = self.relatorio_dc(tenant_id, segmento_id)
        segmento = Segmento(
            id=uuid.uuid4(),
            os_id=os_.id,
            origem="data_cloud",
            dc_segment_id=segmento_id,  # lineage: consulta, não cópia (T5a)
            criterios_resumo=relatorio["segmento"]["criterios_resumo"],
            contagem_bruta=relatorio["funil"]["bruto"],
            contagem_liquida=relatorio["funil"]["liquido"],
            waterfall=relatorio["waterfall"],
            volume_abordagem=relatorio["volume_abordagem"],
            holdout_pct=float(self._politica(os_).get("holdout_min", HOLDOUT_PCT_DEFAULT)),
            frescor=relatorio["frescor"],
        )
        self._repo.adicionar_segmento(segmento)
        self._evento(
            os_,
            "datacloud.segmento_usado",
            {"segmento_id": str(segmento.id), "dc_segment_id": segmento_id},
            actor,
        )
        return segmento

    # --------------------------------------------------------------- Interno
    def _exigir_segmento(self, tenant_id: str, segmento_id: uuid.UUID) -> tuple[Segmento, OS]:
        segmento = self._repo.obter_segmento(segmento_id)
        if segmento is None or segmento.os_id is None:
            raise NaoEncontrado(f"Segmento {segmento_id} não encontrado.")
        os_ = self._servico_os.obter_os(tenant_id, segmento.os_id)  # escopo de tenant via OS
        return segmento, os_

    def _contagens(self, segmento: Segmento) -> dict[str, Any]:
        """Contagens do segmento: read model (estúdio SQL) ou relatório Data Cloud."""
        if segmento.origem == "estudio_sql":
            if not segmento.sql_publico:
                raise SegmentoSemSql(
                    f"Segmento {segmento.id} não tem sql_publico — gere o SQL antes (§8-M5)."
                )
            return self._read_model.contagens_segmentacao(segmento.sql_publico)
        detalhe = self._datacloud.segmento(segmento.dc_segment_id or "")
        relatorio = self._datacloud.relatorio(segmento.dc_segment_id or "")
        if detalhe is None or relatorio is None:
            raise NaoEncontrado(
                f"Segmento Data Cloud {segmento.dc_segment_id!r} não existe mais (T5a)."
            )
        return {**relatorio, "bruto": int(detalhe.get("membros", 0))}

    def _politica(self, os_: OS) -> dict[str, Any]:
        """`conteudo` da política publicada DO TENANT da OS (§4.1 `policy_versao`).

        O tenant é parte da pergunta (§3): sem ele, a política publicada por um tenant
        governaria o holdout do outro. O adapter cai no seed §11.4 quando o tenant
        ainda não publicou nenhuma."""
        return politica_vigente(self._publicacoes, os_.tenant_id)

    def _entrada_cache(
        self, tenant_id: str, bruto: dict[str, Any], agora: datetime
    ) -> DcSegmentCache:
        horas = float(bruto.get("republicado_ha_horas", 0.0))
        return DcSegmentCache(
            id=str(bruto.get("id")),
            tenant_id=tenant_id,
            nome=bruto.get("nome"),
            criterios_resumo=bruto.get("criterios_resumo"),
            membros=int(bruto.get("membros", 0)),
            dmos=list(bruto.get("dmos") or []),
            republicado_em=agora - timedelta(hours=horas),
            ciclo=bruto.get("ciclo"),
            status=bruto.get("status"),
            atualizado_em=agora,
        )

    def _registrar_invocacao(
        self,
        os_: OS,
        skill: Any,
        instrucoes: str,
        saida: agente_engineer.SaidaEngineer,
        portador_id: uuid.UUID,
        inicio: datetime,
        fim: datetime,
        portao: portao_ia.PortaoIa,
    ) -> Invocacao:
        """Ledger via_ai (§4.1 `invocacao`) + evento `agent.invoked` (§2.3). SEM PII,
        e com a RETENÇÃO da política (§10.4) decidindo se o texto chega a ser gravado."""
        invocacao = Invocacao(
            id=uuid.uuid4(),
            tenant_id=os_.tenant_id,
            os_id=os_.id,
            agente_id=agente_uuid(skill.nome),
            skill_versao=skill.versao,
            usuario_portador=portador_id,
            input=portao.reter_input({"os_id": str(os_.id), "instrucoes": instrucoes}),
            output=portao.reter_output(
                {
                    "sql": saida.sql,
                    "explicacao": list(saida.explicacao),
                    "evidencias": list(saida.evidencias),
                }
            ),
            # (b) §10.4: a COLUNA `evidencias` (§4.1) passa pelo portão como o resto. Ela
            # é TEXTO LIVRE (`agents/engineer.py` monta com `str(e).strip()`, e o teor
            # vem do corpus RAG), não ref versionada — sem isto o mesmo texto que sai
            # redigido do `output` voltava inteiro pela coluna vizinha.
            evidencias=portao.reter_evidencias(saida.evidencias),
            latencia_ms=int((fim - inicio).total_seconds() * 1000),
            created_at=fim,
        )
        self._repo.adicionar_invocacao(invocacao)
        self._repo.adicionar_evento(
            EventoDominio(
                tenant_id=os_.tenant_id,
                os_id=os_.id,
                type="agent.invoked",
                payload={
                    "invocacao_id": str(invocacao.id),
                    "agente": skill.nome,
                    "os_codigo": os_.codigo,
                },
                actor=f"agente:{skill.nome}",
                via_ai=True,
                created_at=fim,
            )
        )
        return invocacao

    def _evento(self, os_: OS, tipo: str, payload: dict[str, Any], actor: str) -> None:
        self._repo.adicionar_evento(
            EventoDominio(
                tenant_id=os_.tenant_id,
                os_id=os_.id,
                type=tipo,
                payload=payload,
                actor=actor,
                via_ai=False,
                created_at=self._relogio.agora(),
            )
        )
