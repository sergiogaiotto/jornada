"""Casos de uso do M12 (parte 2) · Políticas + Auditoria (SDD §8-M12) — via ports (§2.1).

Policy-as-code:
- `GET/POST /policies`: ciclo draft→publicada com versão SEQUENCIAL (§4.1
  `policy_versao`); conteúdo validado por código no conjunto fechado do §4.1
  (`domain/governanca/politicas.validar_conteudo` — erros ACUMULADOS → 422).
- Publicar: só draft com versão MAIOR que a publicada atual (draft obsoleto → 409);
  evento `policy.published` (§2.3). Publicar NÃO toca `os.frozen` de OS alguma —
  simetria com skills (§8-M12-A2): OS em voo segue na versão congelada no GO.
- Relatório de policy drift (§8-M12): OSs em voo (frozen + fase ≠ encerrada)
  congeladas em versão ANTIGA que VIOLARIAM a política nova — violações por código
  (`violacoes_contra_conteudo`: holdout de segmento < holdout_min novo; breakers
  congelados no armar mais frouxos que os novos). Pendências de adequação são
  OPCIONAIS (POST explícito): NÃO bloqueantes, origem `policy_drift:v{n}`, dedupe
  por origem.

Auditoria (LGPD Art. 20 — ledger `invocacao` §4.1 é a fonte):
- `GET /auditoria`: eventos do outbox `domain_event` (§2.3) com filtros
  tipo/agente/OS/via_ai; evento via_ai com `invocacao_id` carrega o DETALHE COMPLETO
  (input+evidências+output+judge+humano) — o "clicável" da T16.
- `POST /auditoria/reconstruir/{invocacao_id}`: devolve EXATAMENTE
  input/evidências/output/judge DA ÉPOCA (A3 — publicar skill nova depois não muda
  nada: o ledger é imutável); a própria reconstrução vira evento auditável.
"""

import uuid
from typing import Any

from application.ports.clock import ClockPort
from application.ports.repositorio_plataforma import RepositorioPlataforma
from application.services.os_service import ServicoOs
from domain.agentes.modelos import Invocacao, agente_uuid
from domain.campanha.erros import NaoEncontrado
from domain.campanha.modelos import EventoDominio
from domain.governanca import politicas as regras_politicas
from domain.governanca.erros import EstadoPolicyInvalido, PolicyInvalida
from domain.governanca.modelos import PolicyVersao

_LIMITE_OS_DRIFT = 1000  # varredura de OSs em voo (memória/dev §3; pagina no Postgres real)
_ESTADOS_LAUNCH_ATIVOS = ("armado", "em_rampa", "pausado_breaker")  # rampa NÃO terminal


class ServicoPlataforma:
    def __init__(
        self,
        repositorio: RepositorioPlataforma,
        relogio: ClockPort,
        servico_os: ServicoOs,
    ) -> None:
        self._repo = repositorio
        self._relogio = relogio
        self._servico_os = servico_os

    # ------------------------------------------------------------ GET/POST /policies
    def listar_policies(self, tenant_id: str) -> dict[str, Any]:
        publicada = self._repo.politica_publicada_atual(tenant_id)
        return {
            "policies": [_policy_out(p) for p in self._repo.listar_policies(tenant_id)],
            "publicada": _policy_out(publicada) if publicada is not None else None,
        }

    def criar_policy(
        self, tenant_id: str, *, conteudo: dict[str, Any], actor: str
    ) -> dict[str, Any]:
        erros = regras_politicas.validar_conteudo(conteudo)
        if erros:
            raise PolicyInvalida(
                f"Conteúdo fora do formato `policy_versao.conteudo` §4.1 — {len(erros)} erro(s).",
                erros=erros,
            )
        versao = max((p.versao for p in self._repo.listar_policies(tenant_id)), default=0) + 1
        policy = PolicyVersao(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            versao=versao,
            conteudo=dict(conteudo),
            estado="draft",
        )
        self._repo.adicionar_policy(policy)
        self._evento(
            tenant_id, "policy.criada", {"versao": versao, "policy_id": str(policy.id)}, actor
        )
        return _policy_out(policy)

    def publicar_policy(
        self, tenant_id: str, policy_id: uuid.UUID, *, actor: str
    ) -> dict[str, Any]:
        """draft→publicada (§8-M12) + evento `policy.published` (§2.3); a resposta já
        traz o relatório de policy drift sobre as OSs em voo. NÃO toca `os.frozen`."""
        policy = self._repo.obter_policy(tenant_id, policy_id)
        if policy is None:
            raise NaoEncontrado(f"Policy {policy_id} não encontrada no tenant {tenant_id!r}.")
        if policy.estado != "draft":
            raise EstadoPolicyInvalido(
                f"Transição inválida: {policy.estado} → publicada — o ciclo é "
                "draft→publicada (§8-M12)."
            )
        atual = self._repo.politica_publicada_atual(tenant_id)
        if atual is not None and policy.versao <= atual.versao:
            raise EstadoPolicyInvalido(
                f"Draft v{policy.versao} obsoleto: já existe v{atual.versao} publicada — "
                "crie um draft novo (versão é sequencial §4.1)."
            )
        policy.estado = "publicada"
        policy.publicada_em = self._relogio.agora()
        self._repo.salvar_policy(policy)
        self._evento(  # tipo mínimo do §2.3
            tenant_id,
            "policy.published",
            {"versao": policy.versao, "policy_id": str(policy.id)},
            actor,
        )
        return {**_policy_out(policy), "drift": self.relatorio_drift(tenant_id)}

    # --------------------------------------------------- relatório de policy drift
    def relatorio_drift(self, tenant_id: str) -> dict[str, Any]:
        """OSs em VOO congeladas em versão antiga que VIOLARIAM a política publicada
        ATUAL (§8-M12) — tudo código determinístico (compliance nunca é LLM)."""
        publicada = self._repo.politica_publicada_atual(tenant_id)
        if publicada is None:
            return {"policy_publicada": None, "os_em_voo": 0, "em_drift": []}
        em_voo = [
            os_
            for os_ in self._repo.listar_os(tenant_id, _LIMITE_OS_DRIFT, 0)
            if os_.frozen is not None and os_.fase != "encerrada"
        ]
        em_drift: list[dict[str, Any]] = []
        for os_ in em_voo:
            congelada = (os_.frozen or {}).get("policy_version")
            if congelada is None or int(congelada) >= publicada.versao:
                continue  # sem drift: congelada na versão atual (ou além — impossível)
            violacoes = regras_politicas.violacoes_contra_conteudo(
                holdouts=[
                    {"segmento_id": str(s.id), "holdout_pct": float(s.holdout_pct)}
                    for s in self._repo.listar_segmentos(os_.id)
                ],
                breakers_congelados=[
                    {"launch_id": str(launch.id), "breakers": launch.breakers}
                    for snapshot in self._repo.listar_snapshots(os_.id)
                    for launch in self._repo.listar_launches(snapshot.id)
                    if launch.estado in _ESTADOS_LAUNCH_ATIVOS
                ],
                conteudo=publicada.conteudo,
            )
            em_drift.append(
                {
                    "os_id": str(os_.id),
                    "codigo": os_.codigo,
                    "fase": os_.fase,
                    "policy_version_congelada": int(congelada),
                    "violacoes": violacoes,
                }
            )
        return {
            "policy_publicada": publicada.versao,
            "os_em_voo": len(em_voo),
            "em_drift": em_drift,
        }

    def abrir_pendencias_adequacao(self, tenant_id: str, *, actor: str) -> dict[str, Any]:
        """Pendências de adequação OPCIONAIS (§8-M12): para cada OS em drift COM
        violações, abre pendência NÃO bloqueante (a política nova não pode travar
        retroativamente uma OS aprovada na antiga) com origem `policy_drift:v{n}`;
        idempotente por origem (re-POST não duplica)."""
        relatorio = self.relatorio_drift(tenant_id)
        versao = relatorio["policy_publicada"]
        abertas: list[dict[str, Any]] = []
        for entrada in relatorio["em_drift"]:
            if not entrada["violacoes"]:
                continue
            origem = f"policy_drift:v{versao}"
            os_id = uuid.UUID(entrada["os_id"])
            if any(
                p.origem == origem and p.status == "aberta"
                for p in self._repo.listar_pendencias(os_id)
            ):
                continue  # dedupe: adequação desta versão já registrada
            regras = sorted({v["regra"] for v in entrada["violacoes"]})
            pendencia = self._servico_os.abrir_pendencia(
                tenant_id,
                os_id,
                titulo=f"Adequação à política v{versao}",
                tipo="issue",
                descricao=(
                    f"OS congelada na policy v{entrada['policy_version_congelada']} viola a "
                    f"v{versao} publicada: {', '.join(regras)} (relatório de policy drift §8-M12)."
                ),
                severidade="media",
                bloqueante=False,  # opcional/adequação — não trava a OS em voo
                bloqueia_etapa=None,
                accountable=None,
                origem=origem,
                via_ai=False,
                actor=actor,
            )
            abertas.append(
                {
                    "os_id": entrada["os_id"],
                    "pendencia_id": str(pendencia.id),
                    "numero": pendencia.numero,
                }
            )
        return {"policy_publicada": versao, "pendencias_abertas": abertas}

    # ---------------------------------------------------------------- GET /auditoria
    def listar_auditoria(
        self,
        tenant_id: str,
        *,
        tipo: str | None = None,
        agente: str | None = None,
        os_id: uuid.UUID | None = None,
        via_ai: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Trilha de auditoria (outbox §2.3) com filtros §8-M12: tipo/agente/OS (+
        via_ai); evento via_ai carrega o detalhe COMPLETO do ledger `invocacao`."""
        eventos = [
            e
            for e in self._repo.listar_eventos(os_id=os_id, tipo=tipo)
            if e.tenant_id == tenant_id
            and (agente is None or e.payload.get("agente") == agente)
            and (via_ai is None or e.via_ai == via_ai)
        ]
        total = len(eventos)
        pagina = eventos[offset : offset + limit]
        invocacoes = {str(i.id): i for i in self._repo.listar_invocacoes(tenant_id)}
        nomes = self._nomes_por_agente_id(tenant_id)
        saida: list[dict[str, Any]] = []
        for evento in pagina:
            item: dict[str, Any] = {
                "id": evento.id,
                "tipo": evento.type,
                "os_id": str(evento.os_id) if evento.os_id else None,
                "actor": evento.actor,
                "via_ai": evento.via_ai,
                "payload": evento.payload,
                "created_at": evento.created_at.isoformat(),
            }
            invocacao = invocacoes.get(str(evento.payload.get("invocacao_id") or ""))
            if evento.via_ai and invocacao is not None:  # o "clicável" da T16
                item["invocacao"] = _invocacao_out(invocacao, nomes)
            saida.append(item)
        return {"eventos": saida, "total": total, "limit": limit, "offset": offset}

    # ---------------------------------------- POST /auditoria/reconstruir/{invocacao}
    def reconstruir(self, tenant_id: str, invocacao_id: uuid.UUID, *, actor: str) -> dict[str, Any]:
        """Art. 20 LGPD (A3): devolve EXATAMENTE input/evidências/output/judge da
        época — o ledger `invocacao` (§4.1) é imutável; skill nova publicada depois
        não altera nada. A própria reconstrução vira evento (`auditoria.reconstruida`)."""
        invocacao = self._repo.obter_invocacao(invocacao_id)
        if invocacao is None or invocacao.tenant_id != tenant_id:  # não vaza existência
            raise NaoEncontrado(f"Invocação {invocacao_id} não encontrada no tenant {tenant_id!r}.")
        agora = self._relogio.agora()
        self._repo.adicionar_evento(
            EventoDominio(
                tenant_id=tenant_id,
                os_id=invocacao.os_id,
                type="auditoria.reconstruida",
                payload={"invocacao_id": str(invocacao.id)},
                actor=actor,
                via_ai=False,
                created_at=agora,
            )
        )
        return {
            "reconstruida_em": agora.isoformat(),
            **_invocacao_out(invocacao, self._nomes_por_agente_id(tenant_id)),
        }

    # ----------------------------------------------------------------- privados
    def _nomes_por_agente_id(self, tenant_id: str) -> dict[uuid.UUID, str]:
        """Resolve nome do agente tanto pelo id da tabela `agente` (Ateliê) quanto
        pelo uuid determinístico do ledger (`agente_uuid` — M3, antes do CRUD)."""
        nomes: dict[uuid.UUID, str] = {}
        for agente in self._repo.listar_agentes(tenant_id):
            nomes[agente.id] = agente.nome
            nomes[agente_uuid(agente.nome)] = agente.nome
        return nomes

    def _evento(self, tenant_id: str, tipo: str, payload: dict[str, Any], actor: str) -> None:
        self._repo.adicionar_evento(
            EventoDominio(
                tenant_id=tenant_id,
                os_id=None,  # eventos de PLATAFORMA (política não é escopada a OS)
                type=tipo,
                payload=payload,
                actor=actor,
                via_ai=False,
                created_at=self._relogio.agora(),
            )
        )


# ------------------------------------------------------------- helpers puros do módulo
def _policy_out(policy: PolicyVersao) -> dict[str, Any]:
    return {
        "id": str(policy.id),
        "tenant_id": policy.tenant_id,
        "versao": policy.versao,
        "estado": policy.estado,
        "conteudo": policy.conteudo,
        "publicada_em": policy.publicada_em.isoformat() if policy.publicada_em else None,
    }


def _invocacao_out(invocacao: Invocacao, nomes: dict[uuid.UUID, str]) -> dict[str, Any]:
    """Detalhe COMPLETO do ledger (§4.1 `invocacao`) — input/evidências/output/judge
    exatamente como gravados na época (Art. 20)."""
    return {
        "invocacao_id": str(invocacao.id),
        "os_id": str(invocacao.os_id) if invocacao.os_id else None,
        "agente_id": str(invocacao.agente_id) if invocacao.agente_id else None,
        "agente": nomes.get(invocacao.agente_id) if invocacao.agente_id else None,
        "skill_versao": invocacao.skill_versao,
        "usuario_portador": str(invocacao.usuario_portador),
        "input": invocacao.input,
        "evidencias": invocacao.evidencias,
        "output": invocacao.output,
        "judge": invocacao.judge,
        "aceito_por": str(invocacao.aceito_por) if invocacao.aceito_por else None,
        "aceito_em": invocacao.aceito_em.isoformat() if invocacao.aceito_em else None,
        "tokens": invocacao.tokens,
        "latencia_ms": invocacao.latencia_ms,
        "created_at": invocacao.created_at.isoformat() if invocacao.created_at else None,
    }
