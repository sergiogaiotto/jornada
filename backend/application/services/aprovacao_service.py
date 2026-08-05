"""Casos de uso do M8 (parte 2) · Portões T9 + Aprovação T10 (SDD §8-M8, §4.1).

ZERO LLM em todo o caminho (§10.6): portões, alçada, hash composto e link mágico são
código determinístico. `ServicoPortoes` consolida os quatro portões (certificado M5,
experimento, custo/alçada, governor stub — pleno no M10), pré-registra experimento
(cálculo de poder/n mínimo — domain/experimento/poder.py) e envia custo à alçada
(faixas `alcadas` da política §11.4). `ServicoAprovacao` monta o snapshot (hash
composto sha256 de JGC+SQL+criativos+política+custo+experimento —
domain/governanca/snapshot.py), emite o link mágico (token retornado UMA vez; só o
sha256 persiste), serve a página standalone e registra a decisão (A3: uso único,
expira, ip/device; ressalvas viram pendências) e a invalidação por variação de custo
>10% pós-aprovação (A4: snapshot novo obrigatório).
"""

import hashlib
import secrets
import uuid
from datetime import timedelta
from typing import Any

from application.ports.clock import ClockPort
from application.ports.repositorio_aprovacao import RepositorioAprovacao
from domain.campanha.erros import CodigoDuplicado, NaoEncontrado
from domain.campanha.modelos import OS, EventoDominio, Pendencia
from domain.experimento.modelos import Experimento
from domain.experimento.poder import ALFA, PODER_ALVO, n_minimo_por_mde
from domain.governanca.erros import (
    AprovacaoInvalidada,
    ForaDeAlcada,
    HoldoutAbaixoDaPolitica,
    LinkExpirado,
    LinkJaUtilizado,
    PreRequisitoAusente,
    RessalvasObrigatorias,
    TokenInvalido,
)
from domain.governanca.modelos import DECISOES, VARIACAO_CUSTO_MAX, Aprovacao, Snapshot
from domain.governanca.politicas import POLITICA_PUBLICADA, faixa_alcada
from domain.governanca.snapshot import hash_composto
from domain.jornada.modelos import JornadaVersao
from domain.simulacao.priors import PRIORS_DEFAULT

VALIDADE_LINK_HORAS_DEFAULT = 72

# Estados dos portões (T9): pendente = falta insumo; vermelho bloqueia publish (M9)
VERDE, VERMELHO, PENDENTE = "verde", "vermelho", "pendente"


# ------------------------------------------------------------- helpers puros/compartilhados
def _jornada_corrente_simulada(
    repositorio: RepositorioAprovacao, os_id: uuid.UUID
) -> JornadaVersao | None:
    """Última versão do twin com simulação persistida (§6) — fonte do custo corrente."""
    for jornada in reversed(repositorio.listar_jornadas(os_id)):
        if jornada.simulacao:
            return jornada
    return None


def _custo_previsto(repositorio: RepositorioAprovacao, os_id: uuid.UUID) -> float | None:
    """Custo previsto corrente: P50 da última simulação; fallback taxímetro (M7)."""
    jornada = _jornada_corrente_simulada(repositorio, os_id)
    if jornada is not None and jornada.simulacao:
        return float(jornada.simulacao["custo"]["p50"])
    jornadas = repositorio.listar_jornadas(os_id)
    if jornadas and jornadas[-1].custo_projetado is not None:
        return float(jornadas[-1].custo_projetado)
    return None


def invalidar_aprovacoes_por_custo(
    repositorio: RepositorioAprovacao, os_: OS, relogio: ClockPort
) -> list[Aprovacao]:
    """A4 (§8-M8): variação de custo >10% APÓS aprovação invalida a aprovação.

    Compara o custo previsto corrente (última simulação) com o custo congelado em cada
    snapshot aprovado; acima da tolerância → `invalidada_em/motivo` (migração 0006) +
    evento `aprovacao.invalidada`. Snapshot novo passa a ser obrigatório.
    """
    custo_atual = _custo_previsto(repositorio, os_.id)
    if custo_atual is None:
        return []
    invalidadas: list[Aprovacao] = []
    for snapshot in repositorio.listar_snapshots(os_.id):
        custo_snap = (
            (snapshot.conteudo.get("componentes") or {}).get("custo", {}).get("previsto_p50")
        )
        if not custo_snap:
            continue
        variacao = abs(custo_atual - float(custo_snap)) / float(custo_snap)
        if variacao <= VARIACAO_CUSTO_MAX:
            continue
        for aprovacao in repositorio.listar_aprovacoes(snapshot.id):
            if aprovacao.decisao not in ("aprovado", "aprovado_ressalvas"):
                continue
            if aprovacao.invalidada_em is not None:
                continue
            aprovacao.invalidada_em = relogio.agora()
            aprovacao.invalidada_motivo = (
                f"Variação de custo de {variacao:.1%} (> {VARIACAO_CUSTO_MAX:.0%}) após a "
                f"aprovação (custo aprovado R$ {float(custo_snap):.2f} → corrente "
                f"R$ {custo_atual:.2f}) — snapshot novo obrigatório (§8-M8-A4)."
            )
            repositorio.salvar_aprovacao(aprovacao)
            repositorio.adicionar_evento(
                EventoDominio(
                    tenant_id=os_.tenant_id,
                    os_id=os_.id,
                    type="aprovacao.invalidada",
                    payload={
                        "aprovacao_id": str(aprovacao.id),
                        "snapshot_id": str(snapshot.id),
                        "custo_aprovado": float(custo_snap),
                        "custo_atual": custo_atual,
                        "variacao": round(variacao, 4),
                    },
                    actor="sistema",
                    via_ai=False,  # verificação determinística (§10.6)
                    created_at=relogio.agora(),
                )
            )
            invalidadas.append(aprovacao)
    return invalidadas


class _Base:
    def __init__(self, repositorio: RepositorioAprovacao, relogio: ClockPort) -> None:
        self._repo = repositorio
        self._relogio = relogio

    def _os(self, tenant_id: str, os_id: uuid.UUID) -> OS:
        os_ = self._repo.obter_os(tenant_id, os_id)
        if os_ is None:
            raise NaoEncontrado(f"OS {os_id} não encontrada no tenant {tenant_id!r}.")
        return os_

    def _evento(self, os_: OS, tipo: str, payload: dict[str, Any], actor: str) -> None:
        self._repo.adicionar_evento(
            EventoDominio(
                tenant_id=os_.tenant_id,
                os_id=os_.id,
                type=tipo,
                payload=payload,
                actor=actor,
                via_ai=False,  # portões/aprovação são determinísticos (§10.6)
                created_at=self._relogio.agora(),
            )
        )


# ==================================================================== Portões (T9)
class ServicoPortoes(_Base):
    # ---------------------------------------------------- GET /os/{id}/portoes
    def portoes(self, tenant_id: str, os_id: uuid.UUID) -> dict[str, Any]:
        """Painel T9: certificado (M5), experimento, custo/alçada, governor (stub) +
        estado da aprovação (onde a invalidação A4 é verificada/aplicada)."""
        os_ = self._os(tenant_id, os_id)
        invalidar_aprovacoes_por_custo(self._repo, os_, self._relogio)  # A4 lazy
        return {
            "os_id": str(os_.id),
            "portoes": {
                "certificado": self._portao_certificado(os_),
                "experimento": self._portao_experimento(os_),
                "custo_alcada": self._portao_custo(os_),
                "governor": self._portao_governor(os_),
            },
            "aprovacao": self._estado_aprovacao(os_),
        }

    def _portao_certificado(self, os_: OS) -> dict[str, Any]:
        """M5-A3: certificado tem hash e validade; expirado REPROVA o portão (publish
        M9 recusa)."""
        certificados = self._repo.listar_certificados(os_.id)
        if not certificados:
            return {"estado": PENDENTE, "motivo": "Sem certificado de elegibilidade (M5)."}
        cert = max(certificados, key=lambda c: c.emitido_em)
        if cert.valido_ate is not None and self._relogio.agora() > cert.valido_ate:
            return {
                "estado": VERMELHO,
                "hash": cert.hash,
                "valido_ate": cert.valido_ate.isoformat(),
                "motivo": "Certificado de elegibilidade EXPIRADO — re-certifique (M5-A3).",
            }
        return {
            "estado": VERDE,
            "hash": cert.hash,
            "liquido": cert.liquido,
            "valido_ate": cert.valido_ate.isoformat() if cert.valido_ate else None,
        }

    def _portao_experimento(self, os_: OS) -> dict[str, Any]:
        """A2 (§6 emendado): poder insuficiente na simulação ⇒ portão VERMELHO."""
        experimento = self._repo.experimento_da_os(os_.id)
        if experimento is None:
            return {"estado": PENDENTE, "motivo": "Sem experimento pré-registrado."}
        jornada = _jornada_corrente_simulada(self._repo, os_.id)
        if jornada is None or not jornada.simulacao:
            return {
                "estado": PENDENTE,
                "n_minimo": experimento.n_minimo,
                "motivo": "Rode o Ensaio Geral (§6) para validar o poder do experimento.",
            }
        poder = jornada.simulacao.get("poder") or {}
        if not poder.get("aplicavel"):
            return {
                "estado": PENDENTE,
                "n_minimo": experimento.n_minimo,
                "motivo": "Simulação corrente anterior ao pré-registro — re-simule.",
            }
        estado = VERDE if poder.get("portao") == VERDE else VERMELHO
        return {
            "estado": estado,
            "n_minimo": poder.get("n_minimo"),
            "n_disponivel": poder.get("n_disponivel"),
            "poder": poder.get("poder"),
            "motivo": None
            if estado == VERDE
            else "Poder insuficiente para o MDE pré-registrado (§8-M8-A2).",
        }

    def _portao_custo(self, os_: OS) -> dict[str, Any]:
        custo = _custo_previsto(self._repo, os_.id)
        if custo is None:
            return {"estado": PENDENTE, "motivo": "Sem custo previsto — rode o Ensaio Geral (§6)."}
        faixa = faixa_alcada(custo, POLITICA_PUBLICADA["conteudo"])
        if faixa is None:
            return {
                "estado": VERMELHO,
                "custo_previsto": custo,
                "motivo": "Custo acima da maior faixa de alçada da política (§11.4).",
            }
        envios = self._repo.listar_eventos(os_id=os_.id, tipo="custo.enviado_alcada")
        if not envios:
            return {
                "estado": PENDENTE,
                "custo_previsto": custo,
                "faixa": faixa,
                "motivo": "Custo ainda não enviado à alçada (POST /os/{id}/custo/enviar-alcada).",
            }
        custo_enviado = float(envios[-1].payload.get("custo_previsto") or 0)
        if custo_enviado and abs(custo - custo_enviado) / custo_enviado > VARIACAO_CUSTO_MAX:
            return {
                "estado": PENDENTE,
                "custo_previsto": custo,
                "faixa": faixa,
                "motivo": f"Custo variou >{VARIACAO_CUSTO_MAX:.0%} desde o envio — reenvie.",
            }
        return {
            "estado": VERDE,
            "custo_previsto": custo,
            "faixa": faixa,
            "enviado_em": envios[-1].created_at.isoformat(),
        }

    def _portao_governor(self, os_: OS) -> dict[str, Any]:
        """STUB (§8-M8): árbitro pleno de pressão cross-campanha chega com o M10; aqui
        o veredito vem da pressão de contato da última simulação (§6 governor)."""
        jornada = _jornada_corrente_simulada(self._repo, os_.id)
        if jornada is None or not jornada.simulacao:
            return {
                "estado": PENDENTE,
                "stub": True,
                "motivo": "Sem simulação — pressão de contato desconhecida.",
            }
        pressao = jornada.simulacao.get("pressao_contato") or {}
        colisao = any(canal.get("colisao_critica") for canal in pressao.values())
        motivo = "Colisão crítica: pressão acima do cap da política (§6)." if colisao else None
        return {
            "estado": VERMELHO if colisao else VERDE,
            "stub": True,
            "colisao_critica": colisao,
            "motivo": motivo,
        }

    def _estado_aprovacao(self, os_: OS) -> dict[str, Any]:
        snapshots = self._repo.listar_snapshots(os_.id)
        if not snapshots:
            return {"estado": PENDENTE, "motivo": "Sem snapshot — POST /snapshots (§8-M8)."}
        snapshot = snapshots[-1]
        aprovacoes = self._repo.listar_aprovacoes(snapshot.id)
        base = {"snapshot_id": str(snapshot.id), "snapshot_hash": snapshot.hash}
        if not aprovacoes:
            return {
                **base,
                "estado": PENDENTE,
                "motivo": "Sem link mágico — POST /snapshots/{id}/link-magico.",
            }
        aprovacao = aprovacoes[-1]
        if aprovacao.invalidada_em is not None:
            return {
                **base,
                "estado": VERMELHO,
                "decisao": aprovacao.decisao,
                "invalidada_em": aprovacao.invalidada_em.isoformat(),
                "motivo": aprovacao.invalidada_motivo,
            }
        if aprovacao.decisao is None:
            expirado = self._relogio.agora() > aprovacao.expira_em
            motivo = "Link mágico expirado — gere outro." if expirado else "Aguardando decisão."
            return {
                **base,
                "estado": PENDENTE,
                "expira_em": aprovacao.expira_em.isoformat(),
                "motivo": motivo,
            }
        if aprovacao.decisao == "reprovado":
            return {**base, "estado": VERMELHO, "decisao": "reprovado", "motivo": "Reprovado."}
        return {
            **base,
            "estado": VERDE,
            "decisao": aprovacao.decisao,
            "decidido_em": aprovacao.decidido_em.isoformat() if aprovacao.decidido_em else None,
        }

    # ------------------------------------------------------- POST /experimentos
    def pre_registrar_experimento(
        self,
        tenant_id: str,
        os_id: uuid.UUID,
        *,
        holdout_pct: float | None,
        mde_pp: float,
        janela_dias: int,
        metricas: dict[str, Any],
        actor: str,
    ) -> dict[str, Any]:
        """Pré-registro (§8-M8) com cálculo de poder: n mínimo POR BRAÇO para o MDE
        (duas proporções, α=0,05, poder 0,80 — mesmas premissas do motor §6). O
        pré-registro nasce TRAVADO (`travado_em`) — anti-p-hacking (§4.1/M11)."""
        os_ = self._os(tenant_id, os_id)
        politica = POLITICA_PUBLICADA["conteudo"]
        holdout = float(holdout_pct if holdout_pct is not None else politica["holdout_min"])
        if holdout < float(politica["holdout_min"]):
            raise HoldoutAbaixoDaPolitica(
                f"holdout_pct {holdout:.1f}% abaixo do mínimo da política "
                f"({float(politica['holdout_min']):.1f}% — §11.4)."
            )
        p_base = float(PRIORS_DEFAULT["conversao_organica"])
        n_minimo = n_minimo_por_mde(p_base, mde_pp)
        experimento = Experimento(
            id=uuid.uuid4(),
            os_id=os_.id,
            holdout_pct=holdout,
            n_minimo=n_minimo,
            mde_pp=mde_pp,
            janela_dias=janela_dias,
            metricas=metricas,
            travado_em=self._relogio.agora(),
        )
        self._repo.adicionar_experimento(experimento)
        poder: dict[str, Any] = {
            "p_base": p_base,
            "mde_pp": mde_pp,
            "alfa": ALFA,
            "poder_alvo": PODER_ALVO,
            "n_minimo_por_braco": n_minimo,
        }
        segmentos = [
            s for s in self._repo.listar_segmentos(os_.id) if s.contagem_liquida is not None
        ]
        if segmentos:
            liquido = int(segmentos[-1].contagem_liquida or 0)
            n_holdout = round(liquido * holdout / 100.0)
            poder |= {
                "n_holdout_previsto": n_holdout,
                "suficiente_previsto": n_holdout >= n_minimo,  # holdout = braço limitante
            }
        self._evento(
            os_,
            "experimento.pre_registrado",
            {"experimento_id": str(experimento.id), "n_minimo": n_minimo, "mde_pp": mde_pp},
            actor,
        )
        return {"experimento": experimento, "poder": poder}

    # ------------------------------------- POST /os/{id}/custo/enviar-alcada
    def enviar_custo_alcada(
        self, tenant_id: str, os_id: uuid.UUID, *, actor: str
    ) -> dict[str, Any]:
        """Envia o custo previsto à alçada da política (§11.4 `alcadas` [{ate, papel}])."""
        os_ = self._os(tenant_id, os_id)
        custo = _custo_previsto(self._repo, os_.id)
        if custo is None:
            raise PreRequisitoAusente(
                "Sem custo previsto — rode o Ensaio Geral (§6) antes de enviar à alçada."
            )
        faixa = faixa_alcada(custo, POLITICA_PUBLICADA["conteudo"])
        if faixa is None:
            raise ForaDeAlcada(
                f"Custo previsto R$ {custo:.2f} acima da maior faixa de alçada da política."
            )
        agora = self._relogio.agora()
        self._evento(
            os_,
            "custo.enviado_alcada",
            {"custo_previsto": custo, "faixa": faixa},
            actor,
        )
        return {
            "os_id": str(os_.id),
            "custo_previsto": custo,
            "faixa": faixa,
            "enviado_em": agora.isoformat(),
            "enviado_por": actor,
        }


# ================================================================ Aprovação (T10)
class ServicoAprovacao(_Base):
    def __init__(
        self, repositorio: RepositorioAprovacao, relogio: ClockPort, web_base_url: str
    ) -> None:
        super().__init__(repositorio, relogio)
        self._web_base_url = web_base_url.rstrip("/")

    # ---------------------------------------------------------- POST /snapshots
    def criar_snapshot(self, tenant_id: str, os_id: uuid.UUID, *, actor: str) -> Snapshot:
        """Monta o pacote imutável (§4.1): hash composto sha256 de JGC+SQL+criativos+
        política+custo+experimento; `previsto` herdado da versão (congelar-previsto)."""
        os_ = self._os(tenant_id, os_id)
        jornadas = self._repo.listar_jornadas(os_.id)
        if not jornadas:
            raise PreRequisitoAusente("OS sem versão de jornada (M7) — nada a congelar.")
        jornada = jornadas[-1]
        if not jornada.simulacao:
            raise PreRequisitoAusente(
                "Versão corrente sem simulação — o Ensaio Geral é portão obrigatório (§6)."
            )
        if not jornada.previsto:
            raise PreRequisitoAusente(
                "Previsto não congelado — POST /jornadas/{id}/congelar-previsto antes (§8-M8)."
            )
        segmentos = self._repo.listar_segmentos(os_.id)
        segmento = segmentos[-1] if segmentos else None
        criativos = sorted(
            (
                {
                    "id": str(c.id),
                    "celulas": {f"{cel.canal}:{cel.variante}": cel.estado for cel in c.celulas},
                }
                for c in self._repo.listar_criativos(os_.id)
            ),
            key=lambda c: str(c["id"]),
        )
        experimento = self._repo.experimento_da_os(os_.id)
        componentes: dict[str, Any] = {
            "jgc": {"jornada_id": str(jornada.id), "versao": jornada.versao, "hash": jornada.hash},
            "sql": segmento.sql_publico if segmento else None,
            "criativos": criativos,
            "politica": {
                "versao": POLITICA_PUBLICADA["versao"],
                "conteudo": POLITICA_PUBLICADA["conteudo"],
            },
            "custo": {"previsto_p50": float(jornada.simulacao["custo"]["p50"]), "moeda": "BRL"},
            "experimento": None
            if experimento is None
            else {
                "id": str(experimento.id),
                "holdout_pct": experimento.holdout_pct,
                "n_minimo": experimento.n_minimo,
                "mde_pp": experimento.mde_pp,
                "janela_dias": experimento.janela_dias,
            },
        }
        hash_ = hash_composto(componentes)
        existente = self._repo.obter_snapshot_por_hash(hash_)
        if existente is not None:
            raise CodigoDuplicado(
                f"Snapshot {hash_[:12]}… já existe — nada mudou desde o último pacote "
                "(snapshot é imutável por hash, §1.1.1)."
            )
        snapshot = Snapshot(
            id=uuid.uuid4(),
            os_id=os_.id,
            hash=hash_,
            conteudo={
                "componentes": componentes,
                "os": {"id": str(os_.id), "codigo": os_.codigo, "nome": os_.nome},
                "segmento": None
                if segmento is None
                else {
                    "id": str(segmento.id),
                    "contagem_liquida": segmento.contagem_liquida,
                    "waterfall": segmento.waterfall,
                    "volume_abordagem": segmento.volume_abordagem,
                },
                "criado_por": actor,
            },
            previsto=jornada.previsto,
            created_at=self._relogio.agora(),
        )
        self._repo.adicionar_snapshot(snapshot)
        self._evento(
            os_, "snapshot.created", {"snapshot_id": str(snapshot.id), "hash": hash_}, actor
        )
        return snapshot

    # -------------------------------------- POST /snapshots/{id}/link-magico
    def criar_link_magico(
        self,
        tenant_id: str,
        snapshot_id: uuid.UUID,
        *,
        validade_horas: int = VALIDADE_LINK_HORAS_DEFAULT,
        actor: str,
    ) -> dict[str, Any]:
        """Token ÚNICO retornado uma só vez; persiste apenas o sha256 (`token_hash`).
        Alçada = papel da faixa da política para o custo congelado no snapshot."""
        snapshot, os_ = self._snapshot_da_os(tenant_id, snapshot_id)
        custo = float(snapshot.conteudo["componentes"]["custo"]["previsto_p50"])
        faixa = faixa_alcada(custo, POLITICA_PUBLICADA["conteudo"])
        if faixa is None:
            raise ForaDeAlcada(
                f"Custo do snapshot (R$ {custo:.2f}) acima da maior faixa de alçada — "
                "sem papel apto a aprovar (§11.4)."
            )
        token = secrets.token_urlsafe(32)
        aprovacao = Aprovacao(
            id=uuid.uuid4(),
            snapshot_id=snapshot.id,
            token_hash=_hash_token(token),
            expira_em=self._relogio.agora() + timedelta(hours=validade_horas),
            alcada=str(faixa["papel"]),
        )
        self._repo.adicionar_aprovacao(aprovacao)
        self._evento(
            os_,
            "aprovacao.link_criado",
            {
                "aprovacao_id": str(aprovacao.id),
                "snapshot_id": str(snapshot.id),
                "alcada": aprovacao.alcada,
                "expira_em": aprovacao.expira_em.isoformat(),
            },
            actor,
        )
        return {
            "aprovacao_id": str(aprovacao.id),
            "snapshot_id": str(snapshot.id),
            "token": token,  # única vez em claro (A3) — nunca persistido/logado
            "url": f"{self._web_base_url}/aprovacao/{token}",  # rota standalone §12
            "alcada": aprovacao.alcada,
            "expira_em": aprovacao.expira_em.isoformat(),
        }

    # ------------------------------------------------- GET /aprovacao/{token}
    def payload_aprovacao(self, tenant_id: str, token: str) -> dict[str, Any]:
        """Página standalone (§8-M8): resumo, waterfall, criativos, replay do previsto,
        hash. O token é a credencial (sem login) — link expirado e não decidido → 410."""
        aprovacao, snapshot, os_ = self._por_token(tenant_id, token)
        invalidar_aprovacoes_por_custo(self._repo, os_, self._relogio)  # A4 na página
        if aprovacao.decisao is None and self._relogio.agora() > aprovacao.expira_em:
            raise LinkExpirado("Link mágico expirado — solicite um novo (§8-M8-A3).")
        componentes = snapshot.conteudo["componentes"]
        return {
            "os": {"codigo": os_.codigo, "nome": os_.nome, "fase": os_.fase},
            "snapshot": {
                "id": str(snapshot.id),
                "hash": snapshot.hash,
                "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
            },
            "alcada": aprovacao.alcada,
            "expira_em": aprovacao.expira_em.isoformat(),
            "resumo": {
                "custo": componentes["custo"],
                "politica_versao": componentes["politica"]["versao"],
                "experimento": componentes["experimento"],
                "jgc": componentes["jgc"],
            },
            "waterfall": (snapshot.conteudo.get("segmento") or {}).get("waterfall"),
            "volume_abordagem": (snapshot.conteudo.get("segmento") or {}).get("volume_abordagem"),
            "criativos": componentes["criativos"],
            "previsto": snapshot.previsto,  # replay do Previsto congelado
            "decisao": aprovacao.decisao,
            "decidido_em": aprovacao.decidido_em.isoformat() if aprovacao.decidido_em else None,
            "ressalvas": aprovacao.ressalvas,
            "invalidada": aprovacao.invalidada_em is not None,
            "invalidada_motivo": aprovacao.invalidada_motivo,
        }

    # --------------------------------------- POST /aprovacao/{token}/decidir
    def decidir(
        self,
        tenant_id: str,
        token: str,
        *,
        decisao: str,
        ressalvas: list[str],
        decidido_por: str | None,
        ip: str | None,
        device: str | None,
    ) -> dict[str, Any]:
        """A3: uso ÚNICO (decisão registrada encerra o link), expira, registra
        ip/device; ressalvas viram pendências automáticas (bloqueantes, origem
        `aprovacao:{id}`). Aprovado* marca a versão do twin como `aprovado`."""
        aprovacao, snapshot, os_ = self._por_token(tenant_id, token)
        invalidar_aprovacoes_por_custo(self._repo, os_, self._relogio)
        if aprovacao.invalidada_em is not None:
            raise AprovacaoInvalidada(
                aprovacao.invalidada_motivo or "Aprovação invalidada — snapshot novo obrigatório."
            )
        if aprovacao.decisao is not None:
            raise LinkJaUtilizado("Link mágico já utilizado — a decisão é de uso único (§8-M8-A3).")
        if self._relogio.agora() > aprovacao.expira_em:
            raise LinkExpirado("Link mágico expirado — solicite um novo (§8-M8-A3).")
        if decisao not in DECISOES:
            raise RessalvasObrigatorias(f"Decisão inválida: {decisao!r} (§4.1 `aprovacao`).")
        if decisao == "aprovado_ressalvas" and not [r for r in ressalvas if r.strip()]:
            raise RessalvasObrigatorias("`aprovado_ressalvas` exige ao menos uma ressalva (A3).")
        if decisao != "aprovado_ressalvas" and ressalvas:
            raise RessalvasObrigatorias(
                "Ressalvas só acompanham a decisão `aprovado_ressalvas` (A3)."
            )

        agora = self._relogio.agora()
        actor = decidido_por or "aprovador@link-magico"
        pendencias_criadas: list[int] = []
        registro_ressalvas: list[dict[str, Any]] = []
        for texto in [r.strip() for r in ressalvas if r.strip()]:
            numero = self._repo.proximo_numero_pendencia(os_.id)
            pendencia = Pendencia(
                id=uuid.uuid4(),
                os_id=os_.id,
                numero=numero,
                tipo="issue",
                titulo=texto,
                descricao=f"Ressalva da aprovação {aprovacao.id} (link mágico — §8-M8-A3).",
                severidade="media",
                bloqueante=True,
                bloqueia_etapa=None,
                status="aberta",
                accountable=None,
                aceite=None,
                origem=f"aprovacao:{aprovacao.id}",
                via_ai=False,
                created_at=agora,
            )
            self._repo.adicionar_pendencia(pendencia)
            self._evento(
                os_,
                "pendencia.opened",
                {
                    "pendencia_id": str(pendencia.id),
                    "numero": numero,
                    "origem": pendencia.origem,
                },
                actor,
            )
            pendencias_criadas.append(numero)
            registro_ressalvas.append({"texto": texto, "pendencia_numero": numero})

        aprovacao.decisao = decisao
        aprovacao.decidido_em = agora
        aprovacao.decidido_meta = {"ip": ip, "device": device, "decidido_por": decidido_por}
        aprovacao.ressalvas = registro_ressalvas
        self._repo.salvar_aprovacao(aprovacao)

        if decisao in ("aprovado", "aprovado_ressalvas"):
            jornada_id = uuid.UUID(snapshot.conteudo["componentes"]["jgc"]["jornada_id"])
            jornada = next(
                (j for j in self._repo.listar_jornadas(os_.id) if j.id == jornada_id), None
            )
            if jornada is not None:
                jornada.estado = "aprovado"  # §4.1 `jornada_versao.estado`
                self._repo.salvar_jornada(jornada)

        self._evento(
            os_,
            "snapshot.approved",  # §2.3 (reprovação também é decisão do pacote)
            {
                "snapshot_id": str(snapshot.id),
                "aprovacao_id": str(aprovacao.id),
                "decisao": decisao,
                "pendencias_criadas": pendencias_criadas,
            },
            actor,
        )
        return {
            "id": str(aprovacao.id),
            "snapshot_id": str(snapshot.id),
            "alcada": aprovacao.alcada,
            "decisao": decisao,
            "decidido_em": agora.isoformat(),
            "decidido_meta": aprovacao.decidido_meta,
            "ressalvas": registro_ressalvas,
            "pendencias_criadas": pendencias_criadas,
        }

    # ----------------------------------------------------------------- privados
    def _snapshot_da_os(self, tenant_id: str, snapshot_id: uuid.UUID) -> tuple[Snapshot, OS]:
        snapshot = self._repo.obter_snapshot(snapshot_id)
        os_ = self._repo.obter_os(tenant_id, snapshot.os_id) if snapshot is not None else None
        if snapshot is None or os_ is None:  # escopo de tenant via OS (§4.1)
            raise NaoEncontrado(f"Snapshot {snapshot_id} não encontrado no tenant {tenant_id!r}.")
        return snapshot, os_

    def _por_token(self, tenant_id: str, token: str) -> tuple[Aprovacao, Snapshot, OS]:
        aprovacao = self._repo.obter_aprovacao_por_token_hash(_hash_token(token))
        if aprovacao is None:
            raise TokenInvalido("Link de aprovação inválido.")
        snapshot = self._repo.obter_snapshot(aprovacao.snapshot_id)
        os_ = self._repo.obter_os(tenant_id, snapshot.os_id) if snapshot is not None else None
        if snapshot is None or os_ is None:  # tenant errado não vaza existência (404)
            raise TokenInvalido("Link de aprovação inválido.")
        return aprovacao, snapshot, os_


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
