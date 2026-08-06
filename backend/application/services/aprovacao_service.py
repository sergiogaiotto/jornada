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

C03 (A5 — emenda 2026-08-06): o fluxo público do link mágico NÃO depende de `X-Tenant`.
O token é a credencial E o escopo: `_por_token` deriva o tenant do pacote (token →
aprovação → snapshot → OS). O header segue aceito e, quando presente, é conferido.

A6 (§10.5 — emenda 2026-08-06, UAT #5 achado 2): "criador ≠ aprovador" passa a EXISTIR
em código. O link mágico nasce ENDEREÇADO — `criar_link_magico` exige `aprovador_email`,
recusa (409) quando ele é o `criado_por` do snapshot e confere o papel contra o roster
quando o e-mail é de um usuário do sistema. `decidir` não aceita mais identidade pelo
corpo: o actor da decisão é o e-mail congelado na emissão (mesma doutrina do C03 — o que
o cliente declara é asserção a CONFERIR, nunca fonte da verdade).

E03 (§10.5 — frente 3, UAT #5 pós-onda 1): o TOKEN deixa de ser credencial e vira
PONTEIRO. O furo que o A6/E02b não fechava: `POST /snapshots/{id}/link-magico` devolve o
token em claro a quem emite, e `decidir` era anônimo — logo quem emitia continuava de
posse da credencial do aprovador e podia decidir por ele em outra aba. Com login real
(sessão do §8-M0), a identidade de quem decide passa a vir da SESSÃO e é conferida contra
o `aprovador_email` congelado na emissão — por `_mesma_conta` (igualdade EXATA), e NÃO
pela `_chave_identidade` que a segregação do E02b usa: aquela alarga o casamento para
recusar mais, e alargar do lado que CONCEDE é escalação de privilégio (ver a função):

· `payload_aprovacao` e `decidir` exigem `sessao_email` (a rota já exige sessão) —
  não existe mais caminho anônimo para o pacote nem para a decisão;
· sessão ≠ destinatário do link ⇒ `AcaoNaoPermitida` (403) SEM nomear o aprovador;
· `criar_link_magico` recusa e-mail SEM CONTA no sistema (409): sem camada de e-mail, o
  aprovador precisa de conta para logar — falhar na emissão (onde o emissor age) é melhor
  que entregar um link que morre na decisão. De quebra fecha o buraco de "e-mail de fora
  pula a checagem de alçada", porque `papeis_aprovador is None` deixa de ser tolerado.
"""

import hashlib
import secrets
import uuid
from datetime import timedelta
from typing import Any

from application.ports.clock import ClockPort
from application.ports.publicacoes import PublicacoesPort, politica_vigente
from application.ports.repositorio_aprovacao import RepositorioAprovacao
from domain.campanha.erros import (
    AcaoNaoPermitida,
    CodigoDuplicado,
    EstadoInvalido,
    NaoEncontrado,
)
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
from domain.governanca.politicas import faixa_alcada
from domain.governanca.snapshot import hash_composto
from domain.jornada.modelos import JornadaVersao
from domain.simulacao.priors import PRIORS_DEFAULT

VALIDADE_LINK_HORAS_DEFAULT = 72

# Estados dos portões (T9): pendente = falta insumo; vermelho bloqueia publish (M9)
VERDE, VERMELHO, PENDENTE = "verde", "vermelho", "pendente"


# ------------------------------------------------------------- helpers puros/compartilhados
def _email_normalizado(valor: str | None) -> str:
    """Forma canônica para COMPARAR e-mails (§10.5/A6): sem espaços de borda, caixa baixa.

    Só normaliza — a validação de formato mora na borda (Pydantic em api/v1/portoes.py)
    e a de vazio/`@` em `criar_link_magico`, que é a fronteira de segurança de verdade.
    Sem isso `Analista@Dev.Jornada.Local ` driblaria a segregação por diferença de caixa.
    """
    return (valor or "").strip().lower()


def _chave_identidade(valor: str | None) -> str:
    """Chave da PESSOA por trás do e-mail — usada só para SEGREGAR (§10.5/A6).

    `_email_normalizado` casa caixa e espaço, mas não subendereçamento: em qualquer
    servidor de correio corrente `analista+aprova@dominio` cai na MESMA caixa que
    `analista@dominio`, então bastaria um `+tag` para o criador emitir o link mágico
    para si próprio. Aqui o rótulo depois do `+` é descartado antes de comparar.

    Só ALARGA o conjunto barrado — é comparação de segurança, e errar para o lado de
    recusar custa um link a reemitir. O endereço GRAVADO segue sendo o normalizado, que
    é o que o destinatário de fato usa; esta chave nunca é persistida nem exibida.

    NUNCA use esta chave para CONCEDER (autorizar, casar sessão com destinatário): do
    lado que concede, o mesmo alargamento vira escalação de privilégio — `aprovador+qa@x`
    é uma CONTA distinta, com papéis próprios. Para conceder existe `_mesma_conta`.
    """
    normalizado = _email_normalizado(valor)
    local, arroba, dominio = normalizado.partition("@")
    if not arroba:
        return normalizado
    return f"{local.partition('+')[0]}@{dominio}"


def _mesma_conta(um: str | None, outro: str | None) -> bool:
    """Esta sessão é a do aprovador designado? (§10.5/E03 — a régua que CONCEDE.)

    Igualdade EXATA do e-mail normalizado, e não a `_chave_identidade` da segregação —
    de propósito, porque as duas perguntas têm o sinal do erro invertido:

    · **Recusar** (E02b, `criar_link_magico`): "estas duas identidades podem ser a mesma
      pessoa?" Alargar é conservador — barrar demais custa um link a reemitir.
    · **Conceder** (E03, aqui): "esta sessão É a conta a quem o link foi endereçado?"
      Alargar aqui não barra gente demais, AUTORIZA gente demais — é escalação de
      privilégio, e o alargamento é justamente o `+tag`.

    O ataque que esta função fecha (achado da auditoria da frente 3): `aprovador+qa@x` é
    uma CONTA distinta — login próprio, senha própria, papéis próprios. Com a comparação
    por chave, a sessão dela decidia um link endereçado a `aprovador@x`, tornando
    decorativa a alçada conferida na emissão (§11.4) e carimbando `decidido_por` com o
    e-mail do inocente. Nada se perde no caminho legítimo: desde o E03 o link só nasce
    endereçado a um e-mail que TEM conta, e é o e-mail da conta que a sessão apresenta —
    as duas pontas são a mesma string normalizada.

    Vazio de qualquer lado é `False` — sem identidade não há casamento (falha fechada).
    """
    conta_um, conta_outro = _email_normalizado(um), _email_normalizado(outro)
    return bool(conta_um) and conta_um == conta_outro


def _papeis_aptos(faixa: dict[str, Any], politica: dict[str, Any]) -> set[str]:
    """Papéis que PODEM aprovar a faixa (§11.4 `alcadas` + §10.5).

    `alcadas` é uma ESCADA de escalonamento — quem responde pela faixa de R$ 1M também
    responde pela de R$ 100k, senão o `aprovador` seria barrado numa campanha barata
    justamente por ter alçada maior. Vale, então, o papel da faixa e o de toda faixa
    ACIMA dela; `admin` passa sempre, como em `require_role` (§8-M0).
    """
    teto = float(faixa["ate"])
    aptos = {str(f["papel"]) for f in (politica.get("alcadas") or []) if float(f["ate"]) >= teto}
    return aptos | {"admin"}


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
    def __init__(
        self,
        repositorio: RepositorioAprovacao,
        relogio: ClockPort,
        publicacoes: PublicacoesPort,
    ) -> None:
        self._repo = repositorio
        self._relogio = relogio
        self._publicacoes = publicacoes  # política VIGENTE do banco (achado 8 UAT #5)

    def _politica(self, os_: OS) -> dict[str, Any]:
        """`conteudo` da política publicada do tenant da OS (§4.1 `policy_versao`).

        Era `POLITICA_PUBLICADA["conteudo"]`, a constante compilada: publicar alçadas
        novas em T16 não mudava a faixa que este serviço devolvia (achado 8 UAT #5).
        """
        return politica_vigente(self._publicacoes, os_.tenant_id)

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
                "id": str(experimento.id),
                "n_minimo": experimento.n_minimo,
                "motivo": "Rode o Ensaio Geral (§6) para validar o poder do experimento.",
            }
        poder = jornada.simulacao.get("poder") or {}
        if not poder.get("aplicavel"):
            return {
                "estado": PENDENTE,
                "id": str(experimento.id),
                "n_minimo": experimento.n_minimo,
                "motivo": "Simulação corrente anterior ao pré-registro — re-simule.",
            }
        estado = VERDE if poder.get("portao") == VERDE else VERMELHO
        return {
            "estado": estado,
            "id": str(experimento.id),  # T15: alvo de POST /experimentos/{id}/apurar
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
        faixa = faixa_alcada(custo, self._politica(os_))
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
        politica = self._politica(os_)
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
        faixa = faixa_alcada(custo, self._politica(os_))
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
        self,
        repositorio: RepositorioAprovacao,
        relogio: ClockPort,
        web_base_url: str,
        publicacoes: PublicacoesPort,
    ) -> None:
        super().__init__(repositorio, relogio, publicacoes)
        self._web_base_url = web_base_url.rstrip("/")

    def _politica_do_pacote(self, os_: OS) -> dict[str, Any]:
        """Política que o pacote assina — a versão CONGELADA no GO (§8-M4-A2), não a
        publicada de hoje.

        Achado 8 do UAT #5: `validacao_service` congelava `frozen.policy_version` do
        BANCO e o snapshot gravava `politica.versao` da CONSTANTE — o mesmo artefato
        assinado com duas versões diferentes, e o hash composto (§4.1) carimbando a
        errada. Fonte única agora: `os.frozen`, escrito pelo GO. Se a política do tenant
        avançou desde o GO, a OS em voo segue na versão congelada (§8-M12-A2) e quem
        denuncia o desencontro é o relatório de policy drift — não o silêncio de um
        snapshot que troca de política sozinho.

        A ORIGEM congelada viaja junto (`frozen.policy_origem`) porque o número é
        ambíguo: tenant sem `semear_politicas` é governado pelo SEED §11.4 e congela
        "1"; a primeira política que ele publica pela T16 também nasce v1. Buscar só
        pelo número traria do banco um conteúdo que NUNCA governou esta OS — o achado
        8 outra vez, agora por colisão de numeração.
        """
        frozen = os_.frozen or {}
        congelada = frozen.get("policy_version")
        if congelada is None:  # sem GO não há congelamento: assina a vigente do tenant
            vigente = self._publicacoes.politica_publicada(os_.tenant_id)
            return {"versao": vigente["versao"], "conteudo": dict(vigente["conteudo"])}
        politica = self._publicacoes.politica_versionada(
            int(congelada), os_.tenant_id, origem=frozen.get("policy_origem")
        )
        if politica is None:
            raise PreRequisitoAusente(
                f"Política v{int(congelada)} congelada no GO desta OS não existe mais como "
                "versão publicada do tenant — sem ela o pacote não tem o que assinar "
                "(§8-M4-A2/§4.1). Refaça o GO para congelar a política vigente."
            )
        return {"versao": int(congelada), "conteudo": dict(politica["conteudo"])}

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
            "politica": self._politica_do_pacote(os_),
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
        aprovador_email: str,
        papeis_aprovador: tuple[str, ...] | None = None,
        validade_horas: int = VALIDADE_LINK_HORAS_DEFAULT,
        actor: str,
    ) -> dict[str, Any]:
        """Token ÚNICO retornado uma só vez; persiste apenas o sha256 (`token_hash`).
        Alçada = papel da faixa da política para o custo congelado no snapshot.

        A6 (§10.5): o link nasce ENDEREÇADO. É AQUI que a segregação de funções é
        checada, porque aqui existe sessão autenticada e o `criado_por` do snapshot está
        à mão — no `decidir` só existe o token. Três recusas, todas 409:
        · `aprovador_email` == `criado_por` do snapshot ⇒ auto-aprovação (o furo do UAT #5);
        · snapshot sem `criado_por` ⇒ não dá para conferir, então não se emite (falha alto);
        · e-mail do roster (§8-M0) sem o papel da faixa ⇒ alçada de fachada.

        `papeis_aprovador` vem da borda (api/v1/portoes.py sabe do roster; a camada de
        aplicação não importa `app.*`). `None` = e-mail SEM CONTA no sistema.

        E03 (§10.5 — frente 3): `None` deixa de ser tolerado e vira recusa (409). Antes o
        aprovador podia ser um e-mail qualquer de fora, porque o token era a credencial;
        agora quem decide precisa de SESSÃO, então sem conta o link nasceria morto. Duas
        consequências, ambas boas: a falha acontece na EMISSÃO, com o emissor na frente da
        tela e o admin a um pedido de distância (não há e-mail para convidar — §8-M0); e o
        veredito de alçada deixa de ser pulável — bastava endereçar o link a um e-mail de
        fora para a checagem de papel virar no-op.
        """
        snapshot, os_ = self._snapshot_da_os(tenant_id, snapshot_id)
        custo = float(snapshot.conteudo["componentes"]["custo"]["previsto_p50"])
        faixa = faixa_alcada(custo, self._politica(os_))
        if faixa is None:
            raise ForaDeAlcada(
                f"Custo do snapshot (R$ {custo:.2f}) acima da maior faixa de alçada — "
                "sem papel apto a aprovar (§11.4)."
            )
        aprovador = _email_normalizado(aprovador_email)
        partes = aprovador.split("@")
        if len(partes) != 2 or not all(partes):
            raise EstadoInvalido(
                "`aprovador_email` inválido — informe o e-mail de quem vai aprovar; o link "
                "mágico é endereçado e o token vale como credencial dele (§10.5)."
            )
        criador = _email_normalizado(snapshot.conteudo.get("criado_por"))
        if not criador:
            raise EstadoInvalido(
                "Snapshot sem `criado_por` registrado — sem ele não há como conferir "
                "criador ≠ aprovador (§10.5). Monte um snapshot novo antes de emitir o link."
            )
        # comparação pela CHAVE da pessoa, não pelo texto: `+tag` cai na mesma caixa
        if _chave_identidade(aprovador) == _chave_identidade(criador):
            raise EstadoInvalido(
                f"{aprovador} montou este snapshot e não pode aprová-lo: criador ≠ aprovador "
                "é checagem server-side (§10.5). Emita o link para outra pessoa."
            )
        # …e nem o EMISSOR pode endereçar o link a si mesmo (emenda E02b — UAT #5 pós-onda 1).
        # A primeira versão desta guarda só olhava o `criado_por` do snapshot, que é apenas quem
        # apertou `POST /snapshots` — ação de um clique disponível a qualquer Escritor. Bastava o
        # líder que desenhou a jornada pedir ao analista para empacotar e depois emitir o link
        # para si mesmo: 201 na emissão, 200 na decisão, §10.5 evaporada com o controle "no ar".
        # `actor` é o portador autenticado desta requisição — a identidade que o `decidir` não tem.
        if _chave_identidade(aprovador) == _chave_identidade(_email_normalizado(actor)):
            raise EstadoInvalido(
                f"{aprovador} está emitindo este link para si mesmo: quem emite não aprova "
                "(§10.5). Emita para o aprovador designado."
            )
        papel_exigido = str(faixa["papel"])
        aptos = _papeis_aptos(faixa, self._politica(os_))
        if papeis_aprovador is None:  # E03 (§10.5): sem conta, sem link
            raise EstadoInvalido(
                f"{aprovador} não é usuário do sistema e a decisão exige sessão autenticada "
                "(§10.5/§8-M0): o link mágico aponta para o pacote, não vale como credencial. "
                "Peça ao admin para criar a conta do aprovador e emita o link depois."
            )
        if not (aptos & set(papeis_aprovador)):
            raise ForaDeAlcada(
                f"{aprovador} é usuário do sistema com papéis {sorted(papeis_aprovador)}, e a "
                f"faixa de custo deste snapshot exige `{papel_exigido}` ou acima "
                f"({sorted(aptos)} — §11.4/§10.5)."
            )
        token = secrets.token_urlsafe(32)
        aprovacao = Aprovacao(
            id=uuid.uuid4(),
            snapshot_id=snapshot.id,
            token_hash=_hash_token(token),
            expira_em=self._relogio.agora() + timedelta(hours=validade_horas),
            alcada=papel_exigido,
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
                # A6: o CARIMBO do destinatário — lido de volta por `_destinatario_do_link`
                # na hora de decidir. E-mail em `domain_event` é a prática já vigente aqui
                # (`actor` é e-mail desde o M1); §10.2 proíbe PII de CONTATO em prompt/log/
                # `telemetry_event`, não a identidade de quem age na trilha de auditoria.
                "aprovador_email": aprovador,
            },
            actor,
        )
        return {
            "aprovacao_id": str(aprovacao.id),
            "snapshot_id": str(snapshot.id),
            "token": token,  # única vez em claro (A3) — nunca persistido/logado
            "url": f"{self._web_base_url}/aprovacao/{token}",  # rota standalone §12
            "alcada": aprovacao.alcada,
            "aprovador_email": aprovador,  # a quem o link foi endereçado (§10.5)
            "expira_em": aprovacao.expira_em.isoformat(),
        }

    # ------------------------------------------------- GET /aprovacao/{token}
    def payload_aprovacao(
        self,
        token: str,
        *,
        tenant_id: str | None = None,
        sessao_email: str,
        sessao_nome: str | None = None,
    ) -> dict[str, Any]:
        """Página standalone (§8-M8): resumo, waterfall, criativos, replay do previsto,
        hash. Link expirado e não decidido → 410.

        C03: `tenant_id` segue sem vir de header — mas agora vem da SESSÃO (a rota passa
        `usuario.tenant_id`), que é a mesma doutrina levada ao seu limite: o escopo nunca
        é asserção do cliente.

        E03 (§10.5): `sessao_email` é OBRIGATÓRIO — não há mais leitura anônima. O pacote
        carrega dados de campanha e, pelo achado 9 do UAT #5, PII vinda do briefing; um
        token de 72h numa URL (histórico, referer, print no WhatsApp) não é controle de
        acesso para isso. Quem PODE ler é qualquer sessão do tenant dono do pacote — são
        os mesmos dados que essa pessoa já lê pelas rotas da OS —, e `_por_token` recusa
        (404) o token de outro tenant. Quem pode DECIDIR é só o destinatário: o bloco
        `sessao.pode_decidir` diz isso à UI para ela não oferecer um botão que dará 403.
        """
        aprovacao, snapshot, os_ = self._por_token(token, tenant_id)
        invalidar_aprovacoes_por_custo(self._repo, os_, self._relogio)  # A4 na página
        if aprovacao.decisao is None and self._relogio.agora() > aprovacao.expira_em:
            raise LinkExpirado("Link mágico expirado — solicite um novo (§8-M8-A3).")
        componentes = snapshot.conteudo["componentes"]
        destinatario = self._destinatario_do_link(os_, aprovacao)  # A6 (§10.5)
        return {
            "os": {"codigo": os_.codigo, "nome": os_.nome, "fase": os_.fase},
            "snapshot": {
                "id": str(snapshot.id),
                "hash": snapshot.hash,
                "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
            },
            "alcada": aprovacao.alcada,
            "aprovador_email": destinatario,  # A6 (§10.5)
            # E03: quem está lendo, e se essa pessoa é quem pode decidir (a UI usa para
            # não oferecer botão que dará 403). `pode_decidir` é a MESMA comparação do
            # `decidir` — se divergirem, a tela mente; por isso saem da mesma função.
            "sessao": {
                "email": _email_normalizado(sessao_email),
                "nome": sessao_nome,
                "pode_decidir": _mesma_conta(sessao_email, destinatario),
            },
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
        token: str,
        *,
        tenant_id: str | None = None,
        sessao_email: str,
        decisao: str,
        ressalvas: list[str],
        decidido_por: str | None,
        ip: str | None,
        device: str | None,
    ) -> dict[str, Any]:
        """A3: uso ÚNICO (decisão registrada encerra o link), expira, registra
        ip/device; ressalvas viram pendências automáticas (bloqueantes, origem
        `aprovacao:{id}`). Aprovado* marca a versão do twin como `aprovado`.

        C03: `tenant_id` é OPCIONAL — o tenant sai do próprio token (ver `_por_token`).

        A6 (§10.5): a IDENTIDADE do aprovador NÃO vem do corpo. O actor da decisão é o
        e-mail carimbado na emissão do link; `decidido_por` sobrevive apenas como asserção
        a conferir (mesma doutrina que o C03 aplicou ao `X-Tenant`) e divergiu → 409, para
        que uma tentativa de forjar identidade apareça na cara do chamador em vez de sumir
        num descarte silencioso.

        E03 (§10.5): o A6 congelou A QUEM o link foi endereçado, mas quem APRESENTAVA o
        token seguia anônimo — e o token em claro volta para as mãos de quem emite. Agora
        a decisão exige SESSÃO e a sessão tem que ser a do destinatário: posse do token
        deixa de ser poder de decidir. O 403 é deliberadamente MUDO sobre quem é o
        aprovador — quem está com um token que não é seu não ganha o e-mail de brinde.

        Ordem importa: a identidade é conferida ANTES do estado do link (usado/expirado/
        invalidado). Assim o portador indevido recebe sempre o mesmo 403 e não consegue
        usar as respostas como oráculo do estado do pacote.
        """
        aprovacao, snapshot, os_ = self._por_token(token, tenant_id)
        aprovador = self._destinatario_do_link(os_, aprovacao)
        if aprovador is None:
            raise EstadoInvalido(
                "Link mágico sem destinatário carimbado (emitido antes da segregação §10.5) — "
                "gere um link novo nomeando o aprovador."
            )
        if not _mesma_conta(sessao_email, aprovador):
            raise AcaoNaoPermitida(
                "Esta decisão pertence ao aprovador designado no pacote e a sessão atual não "
                "é a dele — ter o link não dá direito de decidir (§10.5). Entre com a conta "
                "do aprovador ou peça um link novo endereçado a você."
            )
        invalidar_aprovacoes_por_custo(self._repo, os_, self._relogio)
        if aprovacao.invalidada_em is not None:
            raise AprovacaoInvalidada(
                aprovacao.invalidada_motivo or "Aprovação invalidada — snapshot novo obrigatório."
            )
        if aprovacao.decisao is not None:
            raise LinkJaUtilizado("Link mágico já utilizado — a decisão é de uso único (§8-M8-A3).")
        if self._relogio.agora() > aprovacao.expira_em:
            raise LinkExpirado("Link mágico expirado — solicite um novo (§8-M8-A3).")
        if decidido_por is not None and _email_normalizado(decidido_por) != aprovador:
            raise EstadoInvalido(
                "`decidido_por` diverge do aprovador para quem o link foi emitido — a "
                "identidade vem do token, nunca do corpo da requisição (§10.5)."
            )
        if decisao not in DECISOES:
            raise RessalvasObrigatorias(f"Decisão inválida: {decisao!r} (§4.1 `aprovacao`).")
        if decisao == "aprovado_ressalvas" and not [r for r in ressalvas if r.strip()]:
            raise RessalvasObrigatorias("`aprovado_ressalvas` exige ao menos uma ressalva (A3).")
        if decisao != "aprovado_ressalvas" and ressalvas:
            raise RessalvasObrigatorias(
                "Ressalvas só acompanham a decisão `aprovado_ressalvas` (A3)."
            )

        agora = self._relogio.agora()
        actor = aprovador  # A6: quem RECEBEU o link, não quem o corpo declarou ser
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
        # ip/device continuam na trilha (A3); `decidido_por` agora é o e-mail congelado (A6).
        # `sessao_email` (E03) é o e-mail AUTENTICADO que apertou o botão: casa com o
        # congelado pela chave da pessoa, mas pode diferir no rótulo (`+tag`) — e é ele que
        # prova que houve sessão, não posse de token. Guardar os dois é o que permite ler a
        # trilha depois e saber que a decisão veio de alguém logado (§10.2/§2.3).
        aprovacao.decidido_meta = {
            "ip": ip,
            "device": device,
            "decidido_por": aprovador,
            "sessao_email": _email_normalizado(sessao_email),
        }
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
    def _destinatario_do_link(self, os_: OS, aprovacao: Aprovacao) -> str | None:
        """E-mail CONGELADO na emissão do link mágico (A6 §10.5), já normalizado.

        A fonte é o evento `aprovacao.link_criado` — a trilha de auditoria do §2.3, que
        é append-only e viaja no outbox junto com o resto da governança. O carimbo é um
        FATO da emissão ("a quem esta credencial foi entregue"), não um estado mutável da
        linha; e `aprovacao` (§4.1) não tem coluna para ele. A coluna dedicada
        (`aprovacao.aprovador_email`) é a evolução natural e está proposta na emenda —
        até lá a leitura é por evento, que já é durável nos dois adapters.

        Link emitido ANTES desta emenda não tem carimbo ⇒ `None`, e `decidir` recusa:
        um link a regerar custa menos que uma auto-aprovação silenciosa.
        """
        alvo = str(aprovacao.id)
        eventos = self._repo.listar_eventos(os_id=os_.id, tipo="aprovacao.link_criado")
        for evento in reversed(eventos):  # o mais recente do MESMO link
            if evento.payload.get("aprovacao_id") == alvo:
                return _email_normalizado(evento.payload.get("aprovador_email")) or None
        return None

    def _snapshot_da_os(self, tenant_id: str, snapshot_id: uuid.UUID) -> tuple[Snapshot, OS]:
        snapshot = self._repo.obter_snapshot(snapshot_id)
        os_ = self._repo.obter_os(tenant_id, snapshot.os_id) if snapshot is not None else None
        if snapshot is None or os_ is None:  # escopo de tenant via OS (§4.1)
            raise NaoEncontrado(f"Snapshot {snapshot_id} não encontrado no tenant {tenant_id!r}.")
        return snapshot, os_

    def _por_token(
        self, token: str, tenant_id: str | None = None
    ) -> tuple[Aprovacao, Snapshot, OS]:
        """Resolve o link mágico a partir do TOKEN — que é a credencial (A3).

        C03 (UAT #3): o tenant é DERIVADO do próprio token (token → aprovação →
        snapshot → OS → `os_.tenant_id`), nunca exigido do cliente. O aprovador é
        externo: abre a URL do e-mail, sem SPA e sem header `X-Tenant`. Fazer o fluxo
        standalone depender de um header do app acoplava-o ao app — e quebrava em
        qualquer cliente que não fosse a SPA (e-mail, integração, curl).

        Quando o chamador ANUNCIA um tenant (a SPA continua mandando `X-Tenant`), ele
        é tratado como asserção a conferir: divergiu do tenant real do pacote, o token
        é tratado como inválido — 404 sem vazar a existência do link, mesmo padrão de
        antes. Ou seja: o header deixou de ser obrigatório sem virar buraco de escopo.
        """
        aprovacao = self._repo.obter_aprovacao_por_token_hash(_hash_token(token))
        if aprovacao is None:
            raise TokenInvalido("Link de aprovação inválido.")
        snapshot = self._repo.obter_snapshot(aprovacao.snapshot_id)
        os_ = self._repo.obter_os_por_id(snapshot.os_id) if snapshot is not None else None
        if snapshot is None or os_ is None:
            raise TokenInvalido("Link de aprovação inválido.")
        if tenant_id is not None and os_.tenant_id != tenant_id:
            raise TokenInvalido("Link de aprovação inválido.")
        return aprovacao, snapshot, os_


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
