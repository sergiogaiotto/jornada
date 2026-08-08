"""Casos de uso do M11 · Otimização/Retro/Calibração T15 (SDD §8-M11) — via ports (§2.1).

- `propostas` (GET /os/{id}/propostas): PROPOR é a única ação autônoma do optimize
  (§8-M11) — sem proposta pendente, o agente propõe grafos candidatos; o CÓDIGO valida
  (§5.3), calcula o diff (domain/jornada/diff.py), PRÉ-SIMULA o impacto via
  SimuladorService (`ensaiar_grafo` §6 — nada persiste) e ranqueia por
  lift×esforço×risco (ranking.py). Hub LLM fora → degrada para a lista existente
  (leitura nunca quebra; caminho crítico segue sem LLM §10.6).
- `aprovar` (POST /propostas/{id}/aprovar): gera NOVA `jornada_versao` (rascunho, sem
  simulação/previsto) — mini-ciclo M8→M9 expresso: simular → congelar previsto →
  snapshot NOVO → link mágico (nova aprovação EXPRESSA) → plan/apply. Nada é
  publicado pelo agente (§1.1.3). Aprovação vira aprendizado ACEITO.
- `rejeitar`: motivo OBRIGATÓRIO — vira SINAL (aprendizado status `sinal`) que
  alimenta o prompt do optimize na próxima rodada (§8-M11: "motivo vira sinal").
- `apurar` (POST /experimentos/{id}/apurar): ANTI-PEEKING (A1) — janela começa na
  primeira exposição (`sent` ENS) e dura `janela_dias`; antes do fim → 425 Too Early
  e NENHUM lift é calculado. Depois: lift em pp com IC95 (apuracao.py — mesmo z do
  §6) e `significativo` SÓ com IC excluindo zero (A2); resultado persistido em
  `experimento.resultado` (§4.1 {lift, ic95, significativo, roas}). Significativo ⇒
  aprendizado PROMOVIDO + ingestão (STUB) na base RAG `resultados` (A3).
- `clonar_com_aprendizados`: nova OS herdando aprendizados ACEITOS/PROMOVIDOS
  (`herdado_de` aponta a origem) + priors VIGENTES (última `calibracao_prior`
  publicada; fallback PRIORS_DEFAULT v1) — A3.
- `ServicoCalibracao` (CalibrateService §8-M11): compara previsto congelado ×
  realizado por OS, propõe priors novos (razão clampada — calibracao.py) com
  BACKTEST OBRIGATÓRIO; só publica (versionado em `calibracao_prior`) se o erro
  melhora. ZERO LLM em apuração/clone/calibração (§10.6).
"""

import json
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol, cast

from agents import otimizacao as agente_optimize
from application.ports.clock import ClockPort
from application.ports.embedding import EmbeddingPort
from application.ports.llm import LLMIndisponivel, LLMPort
from application.ports.observabilidade import TracerPort
from application.ports.publicacoes import PublicacoesPort, politica_vigente
from application.ports.publicacoes_ia import PublicacoesIaPort
from application.ports.repositorio_otimizacao import RepositorioOtimizacao
from application.services import portao_ia
from application.services.simulador_service import ServicoSimulador
from domain.agentes.modelos import AgenteEvidence, Invocacao, agente_uuid
from domain.campanha.erros import EstadoInvalido, NaoEncontrado
from domain.campanha.modelos import OS, EventoDominio
from domain.custo.tarifas import TARIFAS_VIGENTES
from domain.experimento import apuracao
from domain.experimento.modelos import Experimento, experimento_travado
from domain.governanca.modelos import Snapshot
from domain.intake.janela import janela_oferta_dias
from domain.jornada import taximetro
from domain.jornada.canonico import hash_jgc, normalizar_grafo
from domain.jornada.diff import diff_grafos
from domain.jornada.erros import GrafoInvalido
from domain.jornada.modelos import JornadaVersao
from domain.jornada.validacao import validar_grafo
from domain.lancamento.modelos import Launch
from domain.otimizacao import calibracao as regras_calibracao
from domain.otimizacao import ranking
from domain.otimizacao.erros import (
    ApuracaoAntesDaJanela,
    BacktestReprovado,
    ExperimentoJaApurado,
    MotivoObrigatorio,
    PropostaJaDecidida,
    SaidaDoOptimizeInvalida,
    SemDadosParaCalibrar,
)
from domain.otimizacao.modelos import (
    STATUS_HERDAVEIS,
    Aprendizado,
    CalibracaoPrior,
    PropostaOtimizacao,
)
from domain.simulacao.erros import SimulacaoAusente
from domain.simulacao.priors import PRIORS_DEFAULT

BASE_RAG_RESULTADOS = "resultados"  # §8-M11-A3: aprendizados promovidos entram aqui
_LIMITE_OS_CALIBRACAO = 500


class _RepositorioComLaunches(Protocol):
    """`listar_launches` é da porta do M10, mas a calibração precisa dela para usar a
    MESMA régua do monitor (§8-M10). O repositório é UM objeto que implementa todas as
    portas (tipagem estrutural §2.1) — este Protocol só informa o mypy no cast."""

    def listar_launches(self, snapshot_id: uuid.UUID) -> list[Launch]: ...


def priors_vigentes(
    repositorio: RepositorioOtimizacao, tenant_id: str, tipo_campanha: str | None = None
) -> dict[str, Any]:
    """Última `calibracao_prior` PUBLICADA do tenant (§4.1); sem publicação →
    `PRIORS_DEFAULT` v1 (priors.py) — mesma regra do simulador (§6)."""
    publicadas = [
        c
        for c in repositorio.listar_calibracoes(tenant_id, tipo_campanha)
        if c.publicada_em is not None
    ]
    return publicadas[-1].priors if publicadas else PRIORS_DEFAULT


class _Base:
    def __init__(
        self,
        repositorio: RepositorioOtimizacao,
        relogio: ClockPort,
        publicacoes: PublicacoesPort,
    ) -> None:
        self._repo = repositorio
        self._relogio = relogio
        self._publicacoes = publicacoes  # política VIGENTE do banco (achado 8 UAT #5)

    def _politica(self, os_: OS) -> dict[str, Any]:
        """`conteudo` da política publicada do tenant da OS (§4.1 `policy_versao`).

        O M11 propõe E re-valida a proposta contra a política; com a constante, a
        proposta era julgada por uma política que ninguém podia mudar (achado 8).
        """
        return politica_vigente(self._publicacoes, os_.tenant_id)

    def _os(self, tenant_id: str, os_id: uuid.UUID) -> OS:
        os_ = self._repo.obter_os(tenant_id, os_id)
        if os_ is None:
            raise NaoEncontrado(f"OS {os_id} não encontrada no tenant {tenant_id!r}.")
        return os_

    def _evento(
        self,
        tenant_id: str,
        os_id: uuid.UUID | None,
        tipo: str,
        payload: dict[str, Any],
        actor: str,
        *,
        via_ai: bool = False,
    ) -> None:
        self._repo.adicionar_evento(
            EventoDominio(
                tenant_id=tenant_id,
                os_id=os_id,
                type=tipo,
                payload=payload,
                actor=actor,
                via_ai=via_ai,
                created_at=self._relogio.agora(),
            )
        )


# ============================================================ Otimização/Retro (T15)
class ServicoOtimizacao(_Base):
    def __init__(
        self,
        repositorio: RepositorioOtimizacao,
        relogio: ClockPort,
        llm: LLMPort,
        tracer: TracerPort,
        publicacoes: PublicacoesPort,
        publicacoes_ia: PublicacoesIaPort,
        simulador: ServicoSimulador,
        embedding: EmbeddingPort | None = None,
    ) -> None:
        super().__init__(repositorio, relogio, publicacoes)
        self._llm = llm
        self._tracer = tracer
        # Política de IA PUBLICADA (§10.2). OBRIGATÓRIO, sem default: o optimize é o
        # único agente que chama o LLM por conta própria, e foi justamente por aqui que
        # os quatro parâmetros continuaram inertes depois da fiação dos outros seis
        # serviços — um default `None` deixaria o portão voltar a ser opcional em
        # silêncio, que é a forma do achado 8 do UAT #5.
        self._publicacoes_ia = publicacoes_ia
        self._simulador = simulador
        self._embedding = embedding  # A11: melhor esforço na promoção (§8-M11-A3)

    # ------------------------------------------------------ GET /os/{id}/propostas
    def propostas(
        self, tenant_id: str, os_id: uuid.UUID, *, portador_id: uuid.UUID
    ) -> dict[str, Any]:
        """Propostas do optimize (§8-M11): pendentes existentes são retornadas como
        estão (decidir é humano); sem pendentes, o agente PROPÕE (única ação autônoma)
        — cada candidata é validada, diffada, PRÉ-SIMULADA e ranqueada por código."""
        os_ = self._os(tenant_id, os_id)
        pendentes = self._repo.listar_propostas(os_.id, estado="proposta")
        if pendentes:
            return {
                "os_id": str(os_.id),
                "propostas": [_proposta_out(p) for p in _rankeadas(pendentes)],
                "geradas_agora": False,
                "avisos": [],
            }
        base = self._jornada_base_simulada(os_.id)
        # §10.2 (C02) · o SINAL é texto livre digitado por gente: `motivo` de rejeição
        # (`POST /propostas/{id}/rejeitar`) vira `Aprendizado(status='sinal')` e volta
        # aqui, direto para o prompt e para o ledger. Sem `sanear`, um CPF digitado na
        # justificativa saía da plataforma em claro — e a política do DPO que mandava
        # BLOQUEAR cartão/CPF não governava esta rota.
        portao = portao_ia.de(  # política PUBLICADA + gasto do teto (J02)
            self._publicacoes_ia,
            tenant_id,
            gasto_tokens=portao_ia.gasto_do_dia(self._repo, self._relogio, tenant_id),
        )
        sinais = [
            portao.sanear(a.texto)
            for a in self._repo.listar_aprendizados(os_id=os_.id, status="sinal")
        ]
        skill = agente_optimize.carregar()
        politica = self._politica(os_)
        mensagens = agente_optimize.montar_mensagens(
            skill,
            grafo_atual=base.grafo,
            p50_atual=_p50s(base.simulacao or {}),
            sinais=sinais,
            quiet_hours=politica.get("quiet_hours"),
        )
        inicio = self._relogio.agora()
        # (f) §7.2: perfil do roster CONFERIDO contra a política antes da chamada.
        portao.autorizar_modelo(skill.nome, skill.modelo_perfil)
        try:
            texto, tokens_uso = self._llm.chat(mensagens, perfil=skill.modelo_perfil)
        except LLMIndisponivel as exc:  # leitura degrada — nunca 503 num GET (§10.6)
            return {
                "os_id": str(os_.id),
                "propostas": [],
                "geradas_agora": False,
                "degradado": True,
                "avisos": [f"Hub LLM indisponível — modo degradado (§10.6): {exc}"],
            }
        fim = self._relogio.agora()
        saida = agente_optimize.interpretar_saida(texto)
        if not saida.propostas:  # guarda-corpo §1.3.5: nada é inventado
            detalhe = f" Resposta do agente: {saida.resposta}" if saida.resposta else ""
            raise SaidaDoOptimizeInvalida(
                "Optimize não devolveu proposta utilizável (JSON malformado ou sem "
                f"`propostas` — §7.2).{detalhe}"
            )
        experimento = self._repo.experimento_da_os(os_.id)
        parametros = (base.simulacao or {}).get("parametros") or {}
        criadas: list[PropostaOtimizacao] = []
        avisos: list[dict[str, Any]] = []
        janela_dias = janela_oferta_dias(os_.briefing)  # J04: mesma régua do save/M7
        for bruta in saida.propostas:
            grafo = _normalizar_meta(bruta.grafo, os_)
            erros = validar_grafo(
                grafo,
                experimento_travado=experimento_travado(experimento),
                politica=politica,
                janela_oferta_dias=janela_dias,
            )
            if erros:  # candidata inválida é DESCARTADA com evidência (nada é salvo)
                avisos.append({"titulo": bruta.titulo, "descartada_por": erros})
                continue
            criadas.append(self._montar_proposta(os_, base, bruta, grafo, parametros))
        invocacao = self._registrar_invocacao(
            os_,
            skill,
            input={"jornada_base_id": str(base.id), "sinais": sinais},
            output={
                "propostas": [str(p.id) for p in criadas],
                "descartadas": len(avisos),
                "resumo": saida.resumo,
            },
            portador_id=portador_id,
            inicio=inicio,
            fim=fim,
            portao=portao,
            tokens=tokens_uso,
        )
        self._evento(
            os_.tenant_id,
            os_.id,
            "proposta.criada",
            {
                "invocacao_id": str(invocacao.id),
                "propostas": [str(p.id) for p in criadas],
                "jornada_base_id": str(base.id),
            },
            actor="agente:optimize",
            via_ai=True,
        )
        return {
            "os_id": str(os_.id),
            "propostas": [_proposta_out(p) for p in _rankeadas(criadas)],
            "geradas_agora": True,
            "resumo": saida.resumo,
            "avisos": avisos,
        }

    # ---------------------------------------------- POST /propostas/{id}/aprovar
    def aprovar(self, tenant_id: str, proposta_id: uuid.UUID, *, actor: str) -> dict[str, Any]:
        """Aprovar proposta (§8-M11): gera NOVA versão do twin (rascunho — SEM
        simulação/previsto) e dispara o mini-ciclo M8→M9 expresso: a nova versão gera
        OUTRO hash ⇒ snapshot novo ⇒ nova aprovação EXPRESSA (link mágico) antes de
        qualquer apply (§5.4.4). Vira aprendizado ACEITO."""
        proposta, os_ = self._proposta_do_tenant(tenant_id, proposta_id)
        if proposta.estado != "proposta":
            raise PropostaJaDecidida(
                f"Proposta já {proposta.estado} — decisão é de uso único (§1.1.3)."
            )
        experimento = self._repo.experimento_da_os(os_.id)
        politica = self._politica(os_)
        erros = validar_grafo(  # re-valida: o estado da OS pode ter mudado desde a proposta
            proposta.grafo_proposto,
            experimento_travado=experimento_travado(experimento),
            politica=politica,
            janela_oferta_dias=janela_oferta_dias(os_.briefing),  # J04 — mesma régua
        )
        if erros:
            raise GrafoInvalido(erros)
        agora = self._relogio.agora()
        # Emenda I03: a versão nasce com o grafo em ordem canônica (nodes/edges por id)
        # — o hash normaliza sozinho, mas o COMPILADOR itera o grafo armazenado; grafo
        # torto persistido = activities fora de ordem = falso `alterar` no plan.
        grafo_canonico = normalizar_grafo(proposta.grafo_proposto)
        custo, _, _ = self._taximetro(grafo_canonico, os_.id)
        jornada = JornadaVersao(
            id=uuid.uuid4(),
            os_id=os_.id,
            versao=self._repo.proxima_versao(os_.id),
            grafo=grafo_canonico,
            hash=hash_jgc(grafo_canonico),
            premissas=[f"origem: proposta do optimize {proposta.id} — {proposta.titulo}"],
            custo_projetado=float(custo),
        )
        self._repo.adicionar_jornada(jornada)
        proposta.estado = "aprovada"
        proposta.decidido_por = actor
        proposta.decidido_em = agora
        proposta.jornada_gerada_id = jornada.id
        self._repo.salvar_proposta(proposta)
        aprendizado = self._aprendizado(
            os_,
            origem="proposta_aprovada",
            status="aceito",
            texto=f"{proposta.titulo} — {proposta.motivacao}".strip(" —"),
            meta={"proposta_id": str(proposta.id), "impacto": proposta.impacto},
        )
        self._evento(
            os_.tenant_id,
            os_.id,
            "proposta.aprovada",
            {
                "proposta_id": str(proposta.id),
                "jornada_id": str(jornada.id),
                "versao": jornada.versao,
                "aprendizado_id": str(aprendizado.id),
            },
            actor,
        )
        self._evento(
            os_.tenant_id,
            os_.id,
            "jornada.versao_criada",
            {"jornada_id": str(jornada.id), "versao": jornada.versao, "hash": jornada.hash},
            actor,
        )
        return {
            "proposta": _proposta_out(proposta),
            "jornada": {
                "id": str(jornada.id),
                "versao": jornada.versao,
                "hash": jornada.hash,
                "estado": jornada.estado,  # rascunho — nada publicado (§1.1.3)
                "custo_projetado": jornada.custo_projetado,
            },
            "mini_ciclo": {  # §8-M11: mini-ciclo M8→M9 expresso
                "aprovacao_expressa_necessaria": True,
                "passos": [
                    f"POST /jornadas/{jornada.id}/simular",
                    f"POST /jornadas/{jornada.id}/congelar-previsto",
                    "POST /snapshots (hash novo — o anterior não vale §1.1.1)",
                    "POST /snapshots/{id}/link-magico → decisão expressa (T10)",
                    "POST /snapshots/{id}/plan|apply (M9: exige a NOVA aprovação)",
                ],
            },
        }

    # --------------------------------------------- POST /propostas/{id}/rejeitar
    def rejeitar(
        self, tenant_id: str, proposta_id: uuid.UUID, *, motivo: str, actor: str
    ) -> dict[str, Any]:
        """Rejeitar proposta (§8-M11): motivo OBRIGATÓRIO — vira SINAL (aprendizado
        `sinal`) que o optimize recebe na próxima geração (não re-propor o rejeitado)."""
        proposta, os_ = self._proposta_do_tenant(tenant_id, proposta_id)
        if proposta.estado != "proposta":
            raise PropostaJaDecidida(
                f"Proposta já {proposta.estado} — decisão é de uso único (§1.1.3)."
            )
        if not motivo.strip():
            raise MotivoObrigatorio("Rejeição exige motivo (§8-M11: o motivo vira sinal).")
        agora = self._relogio.agora()
        proposta.estado = "rejeitada"
        proposta.motivo_rejeicao = motivo.strip()
        proposta.decidido_por = actor
        proposta.decidido_em = agora
        self._repo.salvar_proposta(proposta)
        aprendizado = self._aprendizado(
            os_,
            origem="proposta_rejeitada",
            status="sinal",
            texto=motivo.strip(),
            meta={"proposta_id": str(proposta.id), "titulo": proposta.titulo},
        )
        self._evento(
            os_.tenant_id,
            os_.id,
            "proposta.rejeitada",
            {
                "proposta_id": str(proposta.id),
                "motivo": proposta.motivo_rejeicao,
                "aprendizado_id": str(aprendizado.id),
            },
            actor,
        )
        return {"proposta": _proposta_out(proposta), "sinal": {"id": str(aprendizado.id)}}

    # ------------------------------------------ POST /experimentos/{id}/apurar
    def apurar(self, tenant_id: str, experimento_id: uuid.UUID, *, actor: str) -> dict[str, Any]:
        """Apuração (§8-M11) — ZERO LLM (§10.6). ANTI-PEEKING (A1): 425 antes do fim
        da janela (primeira exposição + `janela_dias`), sem calcular NADA. Depois:
        lift pp + IC95 (mesmo z do §6) e `significativo` só com IC excluindo zero
        (A2); resultado imutável em `experimento.resultado` (§4.1)."""
        experimento, os_ = self._experimento_do_tenant(tenant_id, experimento_id)
        if experimento.estado == "apurado":
            raise ExperimentoJaApurado(
                "Experimento já apurado — o resultado registrado é imutável "
                "(anti-p-hacking §8-M11)."
            )
        agora = self._relogio.agora()
        ens = [e for e in self._repo.listar_telemetria(os_.id) if e.fonte != "extract"]
        sents = [e for e in ens if e.tipo == "sent"]
        if not sents:  # janela nem começou: nenhuma exposição registrada
            raise ApuracaoAntesDaJanela(
                "Apuração antes da janela (§8-M11-A1): nenhuma exposição (`sent`) "
                "registrada — a janela pré-registrada começa no primeiro disparo."
            )
        inicio_janela = min(e.ts for e in sents)
        fim_janela = apuracao.fim_da_janela(inicio_janela, experimento.janela_dias)
        if agora < fim_janela:
            if experimento.estado != "em_apuracao":  # janela correndo (§4.1)
                experimento.estado = "em_apuracao"
                self._repo.salvar_experimento(experimento)
            raise ApuracaoAntesDaJanela(
                f"Apuração antes da janela (§8-M11-A1): a janela de "
                f"{experimento.janela_dias} dia(s) termina em {fim_janela.isoformat()} "
                "— anti-peeking: nenhum lift é calculado antes disso.",
                fim_janela=fim_janela,
            )

        conv_tratado = 0
        conv_holdout = 0
        for evento in ens:
            if evento.tipo != "conversion":
                continue
            if (evento.payload or {}).get("grupo") == "holdout":
                conv_holdout += 1
            else:
                conv_tratado += 1
        n_tratado = len({e.contato_hash for e in sents if e.contato_hash})
        n_holdout = apuracao.n_holdout_proporcional(n_tratado, float(experimento.holdout_pct))
        lift = apuracao.lift_com_ic(conv_tratado, conv_holdout, n_tratado, n_holdout)
        custo_real = self._custo_realizado(sents)
        ticket = self._ticket_congelado(os_)
        receita = round(conv_tratado * ticket, 2)
        roas = round(receita / custo_real, 4) if custo_real > 0 else None
        resultado: dict[str, Any] = {  # forma §4.1: {lift, ic95, significativo, roas}
            "lift": lift["lift_pp"],
            "ic95": lift["ic95_pp"],
            "significativo": lift["significativo"],
            "roas": roas,
            "detalhe": {
                **{k: v for k, v in lift.items() if k not in ("lift_pp", "ic95_pp")},
                "janela": {
                    "inicio": inicio_janela.isoformat(),
                    "fim": fim_janela.isoformat(),
                    "dias": experimento.janela_dias,
                },
                "custo_realizado": custo_real,
                "receita": receita,
                "ticket_medio": ticket,
            },
        }
        experimento.resultado = resultado
        experimento.estado = "apurado"
        self._repo.salvar_experimento(experimento)
        self._evento(
            os_.tenant_id,
            os_.id,
            "experimento.apurado",
            {
                "experimento_id": str(experimento.id),
                "lift": resultado["lift"],
                "ic95": resultado["ic95"],
                "significativo": resultado["significativo"],
            },
            actor,
        )
        aprendizado = self._aprendizado_da_apuracao(os_, experimento, resultado)
        return {
            "experimento_id": str(experimento.id),
            "estado": experimento.estado,
            "resultado": resultado,
            "aprendizado": {"id": str(aprendizado.id), "status": aprendizado.status},
        }

    # ------------------------------------- POST /os/{id}/clonar-com-aprendizados
    def clonar_com_aprendizados(
        self,
        tenant_id: str,
        os_id: uuid.UUID,
        *,
        nome: str | None,
        tshirt: str | None,
        created_by: uuid.UUID,
        actor: str,
    ) -> dict[str, Any]:
        """Clone (§8-M11-A3): nova OS (fase `pensada`, briefing copiado) herdando os
        aprendizados ACEITOS/PROMOVIDOS (`herdado_de` = OS origem) + priors VIGENTES
        (última `calibracao_prior` publicada — o Ensaio Geral da nova OS já os usa)."""
        origem = self._os(tenant_id, os_id)
        agora = self._relogio.agora()
        # achado 22/UAT5: sequencial DENTRO do tenant (o clone nasce no tenant da origem)
        sequencial = self._repo.proximo_sequencial_os(agora.year, origem.tenant_id)
        codigo = f"OS-{agora.year}-{sequencial:04d}"
        nova = OS(
            id=uuid.uuid4(),
            tenant_id=origem.tenant_id,
            codigo=codigo,
            nome=nome or f"{origem.nome} (retro)",
            tshirt=tshirt or origem.tshirt,
            fase="pensada",
            briefing=json.loads(json.dumps(origem.briefing or {})),
            frozen=None,
            created_by=created_by,
            created_at=agora,
            updated_at=agora,
        )
        self._repo.adicionar_os(nova)
        herdaveis = [
            a
            for a in self._repo.listar_aprendizados(os_id=origem.id)
            if a.status in STATUS_HERDAVEIS
        ]
        herdados: list[Aprendizado] = []
        for aprendizado in herdaveis:
            copia = Aprendizado(
                id=uuid.uuid4(),
                tenant_id=nova.tenant_id,
                os_id=nova.id,
                origem=aprendizado.origem,
                status=aprendizado.status,
                texto=aprendizado.texto,
                meta={**aprendizado.meta, "herdado": True},
                herdado_de=origem.id,
                created_at=agora,
            )
            self._repo.adicionar_aprendizado(copia)
            herdados.append(copia)
        priors = priors_vigentes(self._repo, nova.tenant_id)
        self._evento(
            nova.tenant_id,
            nova.id,
            "os.clonada_com_aprendizados",
            {
                "origem_os_id": str(origem.id),
                "origem_codigo": origem.codigo,
                "aprendizados_herdados": len(herdados),
                "priors_versao": priors.get("versao"),
            },
            actor,
        )
        return {
            "os": {
                "id": str(nova.id),
                "codigo": nova.codigo,
                "nome": nova.nome,
                "tshirt": nova.tshirt,
                "fase": nova.fase,
            },
            "origem": {"id": str(origem.id), "codigo": origem.codigo},
            "herdados": {
                "aprendizados": [
                    {
                        "id": str(a.id),
                        "origem": a.origem,
                        "status": a.status,
                        "texto": a.texto,
                        "herdado_de": str(origem.id),
                    }
                    for a in herdados
                ],
                "priors": priors,
            },
        }

    # ----------------------------------------------------------------- privados
    def _jornada_base_simulada(self, os_id: uuid.UUID) -> JornadaVersao:
        """Última versão do twin COM simulação (§6) — base do diff/impacto; sem ela
        não há régua para pré-simular proposta (409)."""
        for jornada in reversed(self._repo.listar_jornadas(os_id)):
            if jornada.simulacao:
                return jornada
        raise SimulacaoAusente(
            "OS sem versão simulada — rode o Ensaio Geral (§6) antes de pedir "
            "propostas: o impacto é pré-simulado sobre a régua corrente (§8-M11)."
        )

    def _montar_proposta(
        self,
        os_: OS,
        base: JornadaVersao,
        bruta: agente_optimize.PropostaBruta,
        grafo: dict[str, Any],
        parametros: dict[str, Any],
    ) -> PropostaOtimizacao:
        """Diff + impacto PRÉ-SIMULADO (mesma seed/params da simulação base — §8-M11)
        + ranking lift×esforço×risco; tudo determinístico (§10.6)."""
        diff = diff_grafos(base.grafo, grafo)
        ensaio = self._simulador.ensaiar_grafo(
            os_.tenant_id,
            os_.id,
            grafo,
            seed=int(parametros.get("seed", 42)),
            runs=int(parametros.get("runs", 500)),
            n_personas=int(parametros.get("n_personas", 10_000)),
        )
        base_p50 = _p50s(base.simulacao or {})
        proposto_p50 = _p50s(ensaio)
        deltas = {
            metrica: round(float(proposto_p50[metrica]) - float(base_p50[metrica]), 4)
            if isinstance(proposto_p50.get(metrica), int | float)
            and isinstance(base_p50.get(metrica), int | float)
            else None
            for metrica in base_p50
        }
        esforco = ranking.esforco_do_diff(diff)
        risco = ranking.risco_da_proposta(
            semaforo=str(ensaio.get("semaforo", "vermelho")),
            delta_custo_p50=float(deltas.get("custo") or 0.0),
            altera_entrada=_altera_entrada(base.grafo, diff),
        )
        score = ranking.score_da_proposta(
            conversoes_base_p50=float(base_p50.get("conversoes") or 0.0),
            conversoes_proposto_p50=float(proposto_p50.get("conversoes") or 0.0),
            esforco=esforco,
            risco=risco,
        )
        proposta = PropostaOtimizacao(
            id=uuid.uuid4(),
            os_id=os_.id,
            jornada_base_id=base.id,
            titulo=bruta.titulo,
            motivacao=bruta.motivacao,
            grafo_proposto=grafo,
            diff=diff,
            impacto={
                "base": base_p50,
                "proposto": proposto_p50,
                "deltas": deltas,
                "semaforo_proposto": ensaio.get("semaforo"),
                "parametros": ensaio.get("parametros"),
            },
            esforco=esforco,
            risco=risco,
            score=score,
            created_at=self._relogio.agora(),
        )
        self._repo.adicionar_proposta(proposta)
        return proposta

    def _taximetro(self, grafo: dict[str, Any], os_id: uuid.UUID) -> tuple[Any, Any, Any]:
        """Mesma régua do M7-A2: volume = líquido do último segmento recontado."""
        segmentos = [
            s for s in self._repo.listar_segmentos(os_id) if s.contagem_liquida is not None
        ]
        volume = int(segmentos[-1].contagem_liquida or 0) if segmentos else 0
        return taximetro.calcular(grafo, volume_entrada=volume, tarifas=TARIFAS_VIGENTES)

    def _custo_realizado(self, sents: list[Any]) -> float:
        """Σ sents × tarifa vigente por canal (Decimal — dinheiro nunca em float)."""
        total = Decimal(0)
        for evento in sents:
            total += TARIFAS_VIGENTES.get(evento.canal or "", Decimal(0))
        return float(total)

    def _ticket_congelado(self, os_: OS) -> float:
        """Ticket médio da régua congelada (snapshot.previsto §1.1.2); fallback:
        previsto da versão → briefing → prior default (nunca inventa outro valor)."""
        for snapshot in reversed(self._repo.listar_snapshots(os_.id)):
            ticket = ((snapshot.previsto or {}).get("parametros") or {}).get("ticket_medio")
            if ticket:
                return float(ticket)
        for jornada in reversed(self._repo.listar_jornadas(os_.id)):
            ticket = ((jornada.previsto or jornada.simulacao or {}).get("parametros") or {}).get(
                "ticket_medio"
            )
            if ticket:
                return float(ticket)
        briefing = os_.briefing or {}
        if briefing.get("ticket_medio"):
            return float(briefing["ticket_medio"])
        return float(PRIORS_DEFAULT["ticket_medio"])

    def _aprendizado_da_apuracao(
        self, os_: OS, experimento: Experimento, resultado: dict[str, Any]
    ) -> Aprendizado:
        """Resultado vira aprendizado; SIGNIFICATIVO ⇒ PROMOVIDO + ingestão (STUB) na
        base RAG `resultados` (§8-M11-A3)."""
        significativo = bool(resultado["significativo"])
        texto = (
            f"Experimento da {os_.codigo}: lift {resultado['lift']}pp "
            f"(IC95 {resultado['ic95']}), significativo={significativo}, "
            f"ROAS realizado={resultado['roas']}."
        )
        aprendizado = self._aprendizado(
            os_,
            origem="experimento",
            status="promovido" if significativo else "aceito",
            texto=texto,
            meta={"experimento_id": str(experimento.id), "resultado": resultado},
        )
        if significativo:  # A11: embedding melhor-esforço; a apuração (§10.6, zero
            # hub no caminho crítico) NUNCA falha por RAG — sem vetor a linha fica
            # no fallback e o `rag reindex` (§7.4) completa depois.
            self._repo.adicionar_evidencia(
                AgenteEvidence(
                    id=uuid.uuid4(),
                    tenant_id=os_.tenant_id,
                    base=BASE_RAG_RESULTADOS,
                    ref=f"aprendizado:{aprendizado.id}",
                    chunk=texto,
                    meta={
                        "os_codigo": os_.codigo,
                        "experimento_id": str(experimento.id),
                        "lift": resultado["lift"],
                        "ic95": resultado["ic95"],
                    },
                    embedding=self._embed_melhor_esforco(texto),
                )
            )
            self._evento(
                os_.tenant_id,
                os_.id,
                "aprendizado.promovido",
                {"aprendizado_id": str(aprendizado.id), "base": BASE_RAG_RESULTADOS},
                actor="sistema",
            )
        return aprendizado

    def _embed_melhor_esforco(self, texto: str) -> list[float] | None:
        """Vetor do chunk promovido quando o hub responde; QUALQUER falha → None
        (caminho determinístico da apuração jamais depende do hub — §10.6)."""
        if self._embedding is None or not self._embedding.disponivel():
            return None
        try:
            return self._embedding.embed([texto])[0]
        except Exception:  # noqa: BLE001 — robustez: RAG nunca derruba a apuração
            return None

    def _aprendizado(
        self, os_: OS, *, origem: str, status: str, texto: str, meta: dict[str, Any]
    ) -> Aprendizado:
        aprendizado = Aprendizado(
            id=uuid.uuid4(),
            tenant_id=os_.tenant_id,
            os_id=os_.id,
            origem=origem,
            status=status,
            texto=texto,
            meta=meta,
            created_at=self._relogio.agora(),
        )
        self._repo.adicionar_aprendizado(aprendizado)
        return aprendizado

    def _proposta_do_tenant(
        self, tenant_id: str, proposta_id: uuid.UUID
    ) -> tuple[PropostaOtimizacao, OS]:
        proposta = self._repo.obter_proposta(proposta_id)
        os_ = self._repo.obter_os(tenant_id, proposta.os_id) if proposta is not None else None
        if proposta is None or os_ is None:  # tenant errado não vaza existência
            raise NaoEncontrado(f"Proposta {proposta_id} não encontrada no tenant {tenant_id!r}.")
        return proposta, os_

    def _experimento_do_tenant(
        self, tenant_id: str, experimento_id: uuid.UUID
    ) -> tuple[Experimento, OS]:
        experimento = self._repo.obter_experimento(experimento_id)
        os_ = self._repo.obter_os(tenant_id, experimento.os_id) if experimento is not None else None
        if experimento is None or os_ is None:
            raise NaoEncontrado(
                f"Experimento {experimento_id} não encontrado no tenant {tenant_id!r}."
            )
        return experimento, os_

    def _registrar_invocacao(
        self,
        os_: OS,
        skill: Any,
        *,
        input: dict[str, Any],
        output: dict[str, Any],
        portador_id: uuid.UUID,
        inicio: datetime,
        fim: datetime,
        portao: portao_ia.PortaoIa,
        tokens: int | None = None,
    ) -> Invocacao:
        """Ledger via_ai (§4.1) + evento `agent.invoked` + trace Langfuse (§10.8).

        `portao` é obrigatório e sem default (§10.4): a retenção é decidida na
        GRAVAÇÃO, não na leitura. Um default aqui gravaria prompt e resposta em claro
        para quem publicou `reter_prompt=false`, e nenhuma tela mostraria a diferença.
        """
        invocacao = Invocacao(
            id=uuid.uuid4(),
            tenant_id=os_.tenant_id,
            os_id=os_.id,
            agente_id=agente_uuid(skill.nome),
            skill_versao=skill.versao,
            usuario_portador=portador_id,
            input=portao.reter_input({"os_id": str(os_.id), **input}),
            output=portao.reter_output(output),
            evidencias=[],
            tokens=tokens,  # I04: usage do provedor — §10.8
            latencia_ms=int((fim - inicio).total_seconds() * 1000),
            created_at=fim,
        )
        self._repo.adicionar_invocacao(invocacao)
        self._evento(
            os_.tenant_id,
            os_.id,
            "agent.invoked",
            {"invocacao_id": str(invocacao.id), "agente": skill.nome, "os_codigo": os_.codigo},
            actor=f"agente:{skill.nome}",
            via_ai=True,
        )
        self._tracer.trace(  # §10.8: fire-and-forget, trace_id = invocacao.id
            trace_id=str(invocacao.id),
            nome=f"{skill.nome}.propor",
            metadados={
                "tenant": os_.tenant_id,
                "os_id": str(os_.id),
                "agente": skill.nome,
                "skill_versao": skill.versao,
                "modelo_perfil": skill.modelo_perfil,
            },
            spans=[{"nome": "generate", "latencia_ms": invocacao.latencia_ms}],
        )
        return invocacao


# ============================================================ Calibração (CalibrateService)
class ServicoCalibracao(_Base):
    """CalibrateService (§8-M11): compara previsto×realizado, propõe priors novos e SÓ
    publica com BACKTEST aprovado — versionado em `calibracao_prior` (§4.1). O agente
    calibrate (§7.2) apenas NARRA; todo o cálculo é código determinístico (§10.6).

    Guarda-corpos do UAT5 (achado 4 — três cliques levaram `email.conversao` de 0,032
    a 0,000125 na VPS): (a) a régua é a MESMA do monitor (snapshot do LAUNCH); (b) o
    previsto é RE-PREVISTO sob os priors vigentes antes do backtest, então repetir o
    clique dá razão 1,0, reproduz a régua vigente e vira 409 idempotente em vez de
    compor; (c) o backtest exige ganho mínimo de MAPE e piso de score — previsão
    absurda não vira prior; (d) `rollback` republica os priors de qualquer versão
    anterior, inclusive a v1 `PRIORS_DEFAULT`.
    """

    # ------------------------------------------------- POST /calibracao/publicar
    def publicar(self, tenant_id: str, *, tipo_campanha: str | None, actor: str) -> dict[str, Any]:
        atuais = priors_vigentes(self._repo, tenant_id, tipo_campanha)
        casos = self._casos_previsto_realizado(tenant_id, tipo_campanha, atuais)
        if not casos:
            raise SemDadosParaCalibrar(
                "Sem OS com Previsto congelado E telemetria realizada no tenant — "
                "calibração compara previsto×realizado (§8-M11). Snapshots cuja régua "
                "de congelamento é desconhecida (Previsto sem `priors_versao`) também "
                "ficam de fora: re-simule a OS para congelar um Previsto carimbado."
            )
        razao = regras_calibracao.razao_calibracao(casos)
        novos = regras_calibracao.propor_priors(
            atuais, razao, self._proxima_versao(tenant_id, tipo_campanha)
        )
        if regras_calibracao.mesma_regua(novos, atuais):
            raise EstadoInvalido(  # idempotência: o clique repetido não compõe
                f"Calibração idempotente: razão {razao} sobre os mesmos {len(casos)} casos "
                f"reproduz as taxas da versão vigente v{int(atuais.get('versao', 1))} — "
                "nada a publicar. Rode a campanha (telemetria nova) para recalibrar, ou "
                "POST /calibracao/{versao}/rollback para voltar a uma versão anterior."
            )
        backtest = regras_calibracao.backtest(casos, razao)
        if not backtest["melhora"]:
            raise BacktestReprovado(
                f"Backtest reprovado (§8-M11: obrigatório): MAPE {backtest['mape_antigo']} → "
                f"{backtest['mape_novo']} (razão {razao}) — {backtest['motivo']}. "
                "Priors NÃO publicados."
            )
        return self._registrar(
            tenant_id,
            tipo_campanha,
            priors=novos,
            score=float(backtest["score"]),
            backtest=backtest,
            actor=actor,
            evento="calibracao.publicada",
            extra={"razao": razao, "casos": len(casos)},
        )

    # ------------------------------------------------------- GET /calibracao
    def listar(self, tenant_id: str, *, tipo_campanha: str | None) -> dict[str, Any]:
        """Histórico de priors do tenant (§4.1 `calibracao_prior`), da v1 à vigente.

        A v1 entra SINTÉTICA (`PRIORS_DEFAULT` mora em código, não na tabela) para o
        rollback ao default ser descobrível pela API — é a versão para a qual se volta
        quando uma sequência de calibrações estragou a régua.
        """
        publicadas = self._publicadas(tenant_id, tipo_campanha)
        versoes: list[dict[str, Any]] = [
            {
                "id": None,
                "versao": int(PRIORS_DEFAULT["versao"]),
                "origem": "default",
                "priors": PRIORS_DEFAULT,
                "score": None,
                "razao_aplicada": None,
                "casos": None,
                "publicada_em": None,
                "vigente": not publicadas,
            }
        ]
        versoes += [
            {
                "id": str(c.id),
                "versao": c.versao,
                "origem": (c.priors or {}).get("origem", "calibracao"),
                "priors": c.priors,
                "score": c.score,
                "razao_aplicada": (c.priors or {}).get("razao_aplicada"),
                "casos": len((c.backtest or {}).get("casos") or []),
                "publicada_em": c.publicada_em.isoformat() if c.publicada_em else None,
                "vigente": c is publicadas[-1],
            }
            for c in publicadas
        ]
        return {
            "tenant_id": tenant_id,
            "tipo_campanha": tipo_campanha,
            "vigente": versoes[-1]["versao"],
            "versoes": versoes,  # ordem crescente de versão (v1 primeiro, vigente por último)
        }

    # -------------------------------------- POST /calibracao/{versao}/rollback
    def rollback(
        self, tenant_id: str, versao_alvo: int, *, tipo_campanha: str | None, actor: str
    ) -> dict[str, Any]:
        """Republica os priors da versão `versao_alvo` como versão NOVA (append-only).

        SEM backtest: rollback não é uma hipótese nova, é o desfazer de uma publicação
        ruim — o gate é o PAPEL (líder, como todo publicar §8-M0). Funciona para a v1
        `PRIORS_DEFAULT` mesmo com N versões publicadas por cima (UAT5 achado 4).
        """
        alvo = self._priors_da_versao(tenant_id, tipo_campanha, versao_alvo)
        if alvo is None:
            raise NaoEncontrado(
                f"Versão de priors {versao_alvo} não existe no tenant {tenant_id!r}"
                f"{'' if tipo_campanha is None else f' (tipo {tipo_campanha!r})'} — "
                "veja GET /calibracao."
            )
        versao_nova = self._proxima_versao(tenant_id, tipo_campanha)
        novos = regras_calibracao.priors_de_rollback(alvo, versao_nova)
        return self._registrar(
            tenant_id,
            tipo_campanha,
            priors=novos,
            score=None,  # rollback não pontua: não há hipótese sendo testada
            backtest={"rollback_de": versao_alvo, "melhora": None, "casos": []},
            actor=actor,
            evento="calibracao.rollback",
            extra={"rollback_de": versao_alvo},
        )

    # ----------------------------------------------------------------- privados
    def _registrar(
        self,
        tenant_id: str,
        tipo_campanha: str | None,
        *,
        priors: dict[str, Any],
        score: float | None,
        backtest: dict[str, Any],
        actor: str,
        evento: str,
        extra: dict[str, Any],
    ) -> dict[str, Any]:
        """Grava a `calibracao_prior` nova + evento no ledger (§2.3) e devolve o corpo
        único das rotas de publicar/rollback."""
        agora = self._relogio.agora()
        calibracao = CalibracaoPrior(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            tipo_campanha=tipo_campanha,
            versao=int(priors["versao"]),
            priors=priors,
            score=score,
            backtest=backtest,
            publicada_em=agora,
        )
        self._repo.adicionar_calibracao(calibracao)
        self._evento(
            tenant_id,
            None,  # evento de plataforma (sem OS única — casos no backtest)
            evento,
            {
                "calibracao_id": str(calibracao.id),
                "versao": calibracao.versao,
                "tipo_campanha": tipo_campanha,
                "score": score,
                **extra,
            },
            actor,
        )
        return {
            "id": str(calibracao.id),
            "tenant_id": tenant_id,
            "tipo_campanha": tipo_campanha,
            "versao": calibracao.versao,
            "priors": priors,
            "score": score,
            "backtest": backtest,
            "publicada_em": agora.isoformat(),
        }

    def _publicadas(self, tenant_id: str, tipo_campanha: str | None) -> list[CalibracaoPrior]:
        return [
            c
            for c in self._repo.listar_calibracoes(tenant_id, tipo_campanha)
            if c.publicada_em is not None
        ]

    def _proxima_versao(self, tenant_id: str, tipo_campanha: str | None) -> int:
        anteriores = self._repo.listar_calibracoes(tenant_id, tipo_campanha)
        return max((c.versao for c in anteriores), default=int(PRIORS_DEFAULT["versao"])) + 1

    def _priors_da_versao(
        self, tenant_id: str, tipo_campanha: str | None, versao: int
    ) -> dict[str, Any] | None:
        """Priors de uma versão específica; a v1 mora em código (`PRIORS_DEFAULT`)."""
        if versao == int(PRIORS_DEFAULT["versao"]):
            return PRIORS_DEFAULT
        return next(
            (c.priors for c in self._publicadas(tenant_id, tipo_campanha) if c.versao == versao),
            None,
        )

    def _casos_previsto_realizado(
        self, tenant_id: str, tipo_campanha: str | None, vigentes: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Um caso por OS com Previsto CONGELADO (snapshot §1.1.2) e exposição real.

        Régua = a MESMA do monitor M10 (`_snapshot_de_referencia`: snapshot do LAUNCH,
        não o último snapshot com previsto) — antes do UAT5 as duas divergiam na mesma
        OS (monitor 248 × calibração 20644 contra o mesmo realizado 271).

        `previsto` é o P50 congelado RE-PREVISTO sob os priors VIGENTES (§6: conversões
        são lineares na taxa); `previsto_congelado` guarda o P50 cru para auditoria.
        Sem a re-previsão o backtest compara sempre a régua congelada e nunca reprova.
        `realizado` = conversões ENS do tratado (extract é conciliação, não soma).

        OS cuja régua de congelamento é DESCONHECIDA fica de fora (`_priors_do_snapshot`
        devolve None): re-prever sob uma base chutada faz a razão oscilar (0,8 → 1,25 →
        0,8…) e cada clique publica versão nova — a mesma classe do achado 4.
        """
        casos: list[dict[str, Any]] = []
        for os_ in self._repo.listar_os(tenant_id, _LIMITE_OS_CALIBRACAO, 0):
            snapshot = self._snapshot_de_referencia(os_.id)
            if snapshot is None:
                continue
            congelado = ((snapshot.previsto or {}).get("conversoes") or {}).get("p50")
            if not congelado:
                continue
            ens = [e for e in self._repo.listar_telemetria(os_.id) if e.fonte != "extract"]
            if not any(e.tipo == "sent" for e in ens):
                continue  # campanha ainda não rodou — nada a comparar
            realizado = sum(
                1
                for e in ens
                if e.tipo == "conversion" and (e.payload or {}).get("grupo") != "holdout"
            )
            base = self._priors_do_snapshot(tenant_id, tipo_campanha, snapshot)
            if base is None:
                continue  # régua do congelamento desconhecida — ver _priors_do_snapshot
            escala = regras_calibracao.escala_entre(vigentes, base)
            casos.append(
                {
                    "os": os_.codigo,
                    "previsto_congelado": float(congelado),
                    "previsto": float(congelado) * escala,
                    "realizado": float(realizado),
                    "escala_priors": escala,
                }
            )
        return casos

    def _priors_do_snapshot(
        self, tenant_id: str, tipo_campanha: str | None, snapshot: Snapshot
    ) -> dict[str, Any] | None:
        """Priors SOB OS QUAIS o Previsto foi congelado — o simulador carimba a versão
        em `parametros.priors_versao` (simulador_service §6). É a BASE da re-previsão.

        Sem carimbo (previsto legado) ou com carimbo de versão que não existe neste
        escopo, a base é DESCONHECIDA. Nesse caso só há uma resposta honesta:
        - tenant SEM calibração publicada → a base é o `PRIORS_DEFAULT` v1 por dedução
          (não havia outra régua possível quando o Previsto foi congelado);
        - tenant COM calibração publicada → `None`, e a OS fica de fora da rodada.
          Chutar o default aqui reintroduz o achado 4 numa forma mais lenta: o P50 já
          congelado sob priors calibrados seria escalado de novo, a razão oscilaria
          entre 0,8 e 1,25 e CADA clique publicaria uma versão nova, para sempre.
        """
        versao = ((snapshot.previsto or {}).get("parametros") or {}).get("priors_versao")
        if isinstance(versao, int):
            base = self._priors_da_versao(tenant_id, tipo_campanha, versao)
            if base is not None:
                return base
        return None if self._publicadas(tenant_id, tipo_campanha) else PRIORS_DEFAULT

    def _snapshot_de_referencia(self, os_id: uuid.UUID) -> Snapshot | None:
        """MESMA régua do monitor (§8-M10 — `lancamento_service._launch_de_referencia`):
        o snapshot do último LAUNCH; sem launch, o último snapshot com Previsto.

        O repositório é um só objeto e implementa todas as portas (tipagem estrutural
        §2.1) — a porta do M11 não declara `listar_launches` (é do M10), daí o cast.
        """
        repo = cast(_RepositorioComLaunches, self._repo)
        launch_visto = False
        escolhido: Snapshot | None = None
        for candidato in self._repo.listar_snapshots(os_id):
            if repo.listar_launches(candidato.id):
                launch_visto, escolhido = True, candidato
            elif not launch_visto and candidato.previsto:
                escolhido = candidato
        return escolhido if escolhido is not None and escolhido.previsto else None


# ------------------------------------------------------------- helpers puros do módulo
def _p50s(simulacao: dict[str, Any]) -> dict[str, Any]:
    roas = simulacao.get("roas")
    return {
        "conversoes": (simulacao.get("conversoes") or {}).get("p50"),
        "custo": (simulacao.get("custo") or {}).get("p50"),
        "receita": (simulacao.get("receita") or {}).get("p50"),
        "roas": roas.get("p50") if roas else None,
        "lift_pp": (simulacao.get("lift_pp") or {}).get("p50"),
    }


def _normalizar_meta(grafo: dict[str, Any], os_: OS) -> dict[str, Any]:
    """Escopo NUNCA vem do LLM (§1.3.5): meta.osCodigo/tenant = valores da OS
    (mesmo guarda-corpo do M7).

    Emenda I03 (auditoria da onda 5): a normalização de ordem acontece AQUI, na
    ORIGEM da proposta — não só no aprovar. O motor §6 consome RNG na ordem das
    `edges` de cada nó: proposta pré-simulada torta e versão aprovada canônica
    davam P50s diferentes com a MESMA seed, quebrando a reprodutibilidade
    (M8-A1/§8-M11) que o `impacto` gravado promete — e um "grafo igual, listas
    permutadas" ganhava lift fantasma. O normalizar do aprovar vira idempotente."""
    grafo = dict(grafo)
    grafo.setdefault("jgcVersion", "1.0")
    meta = dict(grafo.get("meta") or {})
    meta["osCodigo"] = os_.codigo
    meta["tenant"] = os_.tenant_id
    meta.setdefault("reentrada", "nao")
    grafo["meta"] = meta
    return normalizar_grafo(grafo)


def _altera_entrada(grafo_base: dict[str, Any], diff: dict[str, Any]) -> bool:
    """True se o diff toca nó `entrySource` (recriar Event Source reinicia contatos
    em espera — aviso destrutivo §5.4.3 ⇒ risco maior)."""
    entradas = {
        str(n.get("id"))
        for n in grafo_base.get("nodes") or []
        if isinstance(n, dict) and n.get("type") == "entrySource"
    }
    nodes = diff.get("nodes") or {}
    tocados = set(nodes.get("alterados") or []) | set(nodes.get("removidos") or [])
    return bool(entradas & tocados)


def _rankeadas(propostas: list[PropostaOtimizacao]) -> list[PropostaOtimizacao]:
    """Ordem do painel (§8-M11): score desc; empate mantém ordem de criação."""
    return sorted(propostas, key=lambda p: -p.score)


def _proposta_out(proposta: PropostaOtimizacao) -> dict[str, Any]:
    return {
        "id": str(proposta.id),
        "os_id": str(proposta.os_id),
        "jornada_base_id": str(proposta.jornada_base_id),
        "titulo": proposta.titulo,
        "motivacao": proposta.motivacao,
        "diff": proposta.diff,
        "impacto": proposta.impacto,
        "esforco": proposta.esforco,
        "risco": proposta.risco,
        "score": proposta.score,
        "estado": proposta.estado,
        "motivo_rejeicao": proposta.motivo_rejeicao,
        "jornada_gerada_id": (
            str(proposta.jornada_gerada_id) if proposta.jornada_gerada_id else None
        ),
        "via_ai": proposta.via_ai,
        "decidido_por": proposta.decidido_por,
        "decidido_em": proposta.decidido_em.isoformat() if proposta.decidido_em else None,
        "created_at": proposta.created_at.isoformat() if proposta.created_at else None,
    }
