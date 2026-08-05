"""Casos de uso do M12 (parte 1) · Ateliê T16 (SDD §8-M12, §7.1) — via ports (§2.1).

- CRUD de agentes/skills: skill nasce `draft` a partir de um SKILL.md canônico (o
  parser §7.1 valida CAMPOS — skill_parser.py); ciclo draft→em_revisao→publicada;
  só `draft` é editável (em revisão o conteúdo é imutável — o harness julga um texto
  estável).
- `rodar_harness` (POST /skills/{id}/harness): roda o GOLDEN DATASET do agente
  (`harness_case` §4.1 — 3 casos por agente-chave nas seeds §11.4): executa a skill
  candidata sobre o input de cada caso e o JUDGE (LLM 120b, rubrica fixa §7.1; em
  teste o LLMFake determinístico §1.3.5) dá nota por dimensão; o CÓDIGO consolida
  (média por dimensão, passou = todas ≥ 90 §7.1) e grava `harness_run` com
  `skill_md_hash` (amarra o run ao texto julgado). Traceado com tag `harness` (§10.8).
- `publicar` (POST /skills/{id}/publicar): portão §8-M12-A1 — exige estado
  `em_revisao` E último harness_run VERDE sobre o skill_md ATUAL; senão 409. Publicar
  NUNCA toca `os.frozen` (A2): OS em voo continua com as versões congeladas no GO
  (§8-M4-A2); OS nova congela as novas no próximo GO (PublicacoesAtelie).
- `dry_run`: lado a lado (§8-M12) — MESMA entrada na versão publicada ATUAL e na
  candidata; nada persiste; decisão é humana (§1.1.3).
- `versao_para_os`: resolução da versão efetiva por OS — frozen.agent_versions (§4.1)
  quando a OS está em voo; senão a publicada atual (base da A2).
"""

import uuid
from typing import Any

from agents.harness import judge
from application.ports.clock import ClockPort
from application.ports.llm import LLMPort
from application.ports.observabilidade import TracerPort
from application.ports.repositorio_atelie import RepositorioAtelie
from domain.atelie import harness as regras_harness
from domain.atelie.erros import (
    AgenteDuplicado,
    EstadoSkillInvalido,
    HarnessNaoAprovado,
    SemCasosGolden,
    SkillMdInvalido,
    VersaoDuplicada,
)
from domain.atelie.modelos import Agente, HarnessRun, SkillVersao
from domain.atelie.skill_parser import SkillMd, parse_skill_md
from domain.campanha.erros import NaoEncontrado
from domain.campanha.modelos import EventoDominio


class ServicoAtelie:
    def __init__(
        self,
        repositorio: RepositorioAtelie,
        relogio: ClockPort,
        llm: LLMPort,
        tracer: TracerPort,
    ) -> None:
        self._repo = repositorio
        self._relogio = relogio
        self._llm = llm
        self._tracer = tracer

    # ------------------------------------------------------------ GET/POST /agentes
    def listar_agentes(self, tenant_id: str) -> list[dict[str, Any]]:
        publicadas = self._repo.versoes_skills_publicadas()
        return [
            {
                **_agente_out(agente),
                "versao_publicada": publicadas.get(agente.nome),
                "skills": [_skill_resumo(s) for s in self._repo.listar_skills(agente.id)],
            }
            for agente in self._repo.listar_agentes(tenant_id)
        ]

    def criar_agente(
        self,
        tenant_id: str,
        *,
        nome: str,
        camada: str,
        etapa_workflow: str | None,
        modelo_perfil: str | None,
        deterministico: bool,
        actor: str,
    ) -> dict[str, Any]:
        if self._repo.obter_agente_por_nome(nome) is not None:
            raise AgenteDuplicado(f"Agente {nome!r} já existe — `agente.nome` é unique (§4.1).")
        agente = Agente(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            nome=nome,
            camada=camada,
            etapa_workflow=etapa_workflow,
            modelo_perfil=modelo_perfil,
            deterministico=deterministico,
        )
        self._repo.adicionar_agente(agente)
        self._evento(tenant_id, "agente.criado", {"agente": nome, "camada": camada}, actor)
        return {**_agente_out(agente), "versao_publicada": None, "skills": []}

    # ------------------------------------------- GET/POST /agentes/{id}/skills, PUT
    def listar_skills(self, tenant_id: str, agente_id: uuid.UUID) -> list[dict[str, Any]]:
        agente = self._agente(tenant_id, agente_id)
        return [_skill_resumo(s) for s in self._repo.listar_skills(agente.id)]

    def criar_skill(
        self, tenant_id: str, agente_id: uuid.UUID, *, skill_md: str, actor: str
    ) -> dict[str, Any]:
        agente = self._agente(tenant_id, agente_id)
        parseada = self._parse_para_agente(agente, skill_md)
        if any(s.versao == parseada.versao for s in self._repo.listar_skills(agente.id)):
            raise VersaoDuplicada(
                f"Versão {parseada.versao} já existe para {agente.nome!r} — "
                "unique(agente_id, versao) (§4.1)."
            )
        skill = SkillVersao(
            id=uuid.uuid4(),
            agente_id=agente.id,
            versao=parseada.versao,
            skill_md=skill_md,
            execution_profile=parseada.execution_profile(),
            bases_rag=list(parseada.bases_rag),
        )
        self._repo.adicionar_skill(skill)
        self._evento(
            tenant_id,
            "skill.criada",
            {"agente": agente.nome, "versao": skill.versao, "skill_id": str(skill.id)},
            actor,
        )
        return _skill_out(skill, [])

    def atualizar_skill(
        self, tenant_id: str, skill_id: uuid.UUID, *, skill_md: str, actor: str
    ) -> dict[str, Any]:
        skill, agente = self._skill_do_tenant(tenant_id, skill_id)
        if skill.estado != "draft":
            raise EstadoSkillInvalido(
                f"Skill {skill.estado} não é editável — só `draft` muda de conteúdo "
                "(em revisão o harness julga um texto estável §8-M12)."
            )
        parseada = self._parse_para_agente(agente, skill_md)
        if any(
            s.versao == parseada.versao and s.id != skill.id
            for s in self._repo.listar_skills(agente.id)
        ):
            raise VersaoDuplicada(
                f"Versão {parseada.versao} já existe para {agente.nome!r} — "
                "unique(agente_id, versao) (§4.1)."
            )
        skill.versao = parseada.versao
        skill.skill_md = skill_md
        skill.execution_profile = parseada.execution_profile()
        skill.bases_rag = list(parseada.bases_rag)
        self._repo.salvar_skill(skill)
        self._evento(
            tenant_id,
            "skill.atualizada",
            {"agente": agente.nome, "versao": skill.versao, "skill_id": str(skill.id)},
            actor,
        )
        return _skill_out(skill, self._repo.listar_harness_runs(skill.id))

    def obter_skill(self, tenant_id: str, skill_id: uuid.UUID) -> dict[str, Any]:
        skill, _ = self._skill_do_tenant(tenant_id, skill_id)
        return _skill_out(skill, self._repo.listar_harness_runs(skill.id))

    # ------------------------------------------------------ POST /skills/{id}/revisao
    def enviar_para_revisao(
        self, tenant_id: str, skill_id: uuid.UUID, *, actor: str
    ) -> dict[str, Any]:
        skill, agente = self._skill_do_tenant(tenant_id, skill_id)
        if skill.estado != "draft":
            raise EstadoSkillInvalido(
                f"Transição inválida: {skill.estado} → em_revisao — o ciclo é "
                "draft→em_revisao→publicada (§8-M12)."
            )
        skill.estado = "em_revisao"
        self._repo.salvar_skill(skill)
        self._evento(
            tenant_id,
            "skill.em_revisao",
            {"agente": agente.nome, "versao": skill.versao, "skill_id": str(skill.id)},
            actor,
        )
        return _skill_out(skill, self._repo.listar_harness_runs(skill.id))

    # ------------------------------------------------------ POST /skills/{id}/harness
    def rodar_harness(self, tenant_id: str, skill_id: uuid.UUID, *, actor: str) -> dict[str, Any]:
        """Roda o golden dataset com judge (docstring do módulo). LLM indisponível →
        `LLMIndisponivel` sobe e a API responde 503 degraded (§10.6 — harness não é
        caminho crítico)."""
        skill, agente = self._skill_do_tenant(tenant_id, skill_id)
        casos = self._repo.listar_harness_cases(agente.id)
        if not casos:
            raise SemCasosGolden(
                f"Agente {agente.nome!r} sem golden dataset (`harness_case` §4.1) — "
                "harness exige casos (seeds §11.4: 3 por agente-chave)."
            )
        perfil = str(skill.execution_profile.get("modelo_perfil") or "20b")
        corpo = parse_skill_md(skill.skill_md).corpo
        inicio = self._relogio.agora()
        avaliacoes: list[dict[str, Any]] = []
        for caso in casos:
            saida = self._llm.chat(
                judge.montar_mensagens_execucao(corpo, caso.input),
                perfil=perfil,  # type: ignore[arg-type]  # validado pelo parser §7.1
            )
            veredito = self._llm.chat(
                judge.montar_mensagens_judge(
                    entrada=caso.input,
                    esperado=caso.esperado,
                    saida=saida,
                    dimensoes=caso.dimensoes,
                ),
                perfil=judge.PERFIL_JUDGE,
            )
            avaliacoes.append(
                {
                    "case_id": str(caso.id),
                    "dimensoes": caso.dimensoes,
                    "notas": judge.interpretar_notas(veredito, caso.dimensoes),
                    "saida": saida,
                }
            )
        consolidado = regras_harness.consolidar(avaliacoes)
        fim = self._relogio.agora()
        run = HarnessRun(
            id=uuid.uuid4(),
            skill_versao_id=skill.id,
            resultados={
                "casos": avaliacoes,
                "score_por_dimensao": consolidado["score_por_dimensao"],
                "dimensoes_reprovadas": consolidado["dimensoes_reprovadas"],
                "skill_md_hash": regras_harness.hash_skill_md(skill.skill_md),
            },
            score=consolidado["score"],
            passou=consolidado["passou"],
            created_at=fim,
        )
        self._repo.adicionar_harness_run(run)
        self._evento(
            tenant_id,
            "harness.run",
            {
                "agente": agente.nome,
                "versao": skill.versao,
                "harness_run_id": str(run.id),
                "score": run.score,
                "passou": run.passou,
            },
            actor,
        )
        self._tracer.trace(  # §10.8: harness runs traceados com tag `harness`
            trace_id=str(run.id),
            nome=f"harness.{agente.nome}",
            metadados={
                "tenant": tenant_id,
                "agente": agente.nome,
                "skill_versao": skill.versao,
                "modelo_perfil": perfil,
                "tags": ["harness"],
            },
            spans=[
                {
                    "nome": "harness",
                    "casos": len(casos),
                    "latencia_ms": int((fim - inicio).total_seconds() * 1000),
                }
            ],
        )
        return _run_out(run)

    # ----------------------------------------------------- POST /skills/{id}/publicar
    def publicar(self, tenant_id: str, skill_id: uuid.UUID, *, actor: str) -> dict[str, Any]:
        """Portão §8-M12-A1 (docstring do módulo). NÃO toca `os.frozen` de nenhuma OS
        (A2): o congelado do GO permanece; só o `versoes_skills_publicadas()` muda."""
        skill, agente = self._skill_do_tenant(tenant_id, skill_id)
        if skill.estado != "em_revisao":
            raise EstadoSkillInvalido(
                f"Transição inválida: {skill.estado} → publicada — o ciclo é "
                "draft→em_revisao→publicada (§8-M12)."
            )
        runs = self._repo.listar_harness_runs(skill.id)
        ultimo = runs[-1] if runs else None
        if ultimo is None:
            raise HarnessNaoAprovado(
                "Publicar exige harness VERDE (§8-M12-A1) — nenhum harness_run "
                "registrado para esta versão; rode POST /skills/{id}/harness."
            )
        if ultimo.resultados.get("skill_md_hash") != regras_harness.hash_skill_md(skill.skill_md):
            raise HarnessNaoAprovado(
                "Harness_run obsoleto: o skill_md mudou depois do último run — "
                "rode o harness de novo sobre o texto atual (§8-M12-A1)."
            )
        if not ultimo.passou:
            raise HarnessNaoAprovado(
                f"Harness reprovado (score {ultimo.score}; dimensões < 90: "
                f"{ultimo.resultados.get('dimensoes_reprovadas')}) — publicar exige "
                "score ≥ 90 por dimensão do judge (§7.1)."
            )
        skill.estado = "publicada"
        skill.harness_score = ultimo.score
        skill.publicada_em = self._relogio.agora()
        self._repo.salvar_skill(skill)
        self._evento(
            tenant_id,
            "skill.publicada",
            {
                "agente": agente.nome,
                "versao": skill.versao,
                "skill_id": str(skill.id),
                "harness_run_id": str(ultimo.id),
                "score": ultimo.score,
            },
            actor,
        )
        return _skill_out(skill, runs)

    # ------------------------------------------------------ POST /skills/{id}/dry-run
    def dry_run(
        self, tenant_id: str, skill_id: uuid.UUID, *, entrada: dict[str, Any]
    ) -> dict[str, Any]:
        """Lado a lado (§8-M12): MESMA entrada na versão publicada ATUAL e na
        candidata. Nada persiste; nenhuma decisão automática (§1.1.3)."""
        candidata, agente = self._skill_do_tenant(tenant_id, skill_id)
        publicadas = [
            s
            for s in self._repo.listar_skills(agente.id)
            if s.estado == "publicada" and s.publicada_em is not None and s.id != candidata.id
        ]
        atual = max(publicadas, key=lambda s: s.publicada_em) if publicadas else None  # type: ignore[arg-type,return-value]
        avisos: list[str] = []
        if atual is None:
            avisos.append(
                f"Agente {agente.nome!r} sem versão publicada anterior — lado 'atual' vazio."
            )
        return {
            "agente": agente.nome,
            "entrada": entrada,
            "atual": self._executar_lado(atual, entrada),
            "candidata": self._executar_lado(candidata, entrada),
            "avisos": avisos,
        }

    # ------------------------------------------------------------ resolução por OS
    def versao_para_os(self, tenant_id: str, os_id: uuid.UUID, agente_nome: str) -> dict[str, Any]:
        """Versão EFETIVA do agente para a OS: em voo (GO executado) → a congelada em
        `os.frozen.agent_versions` (§4.1/A2); senão a publicada atual."""
        os_ = self._repo.obter_os(tenant_id, os_id)
        if os_ is None:
            raise NaoEncontrado(f"OS {os_id} não encontrada no tenant {tenant_id!r}.")
        congeladas = (os_.frozen or {}).get("agent_versions") or {}
        if agente_nome in congeladas:
            return {"agente": agente_nome, "versao": congeladas[agente_nome], "origem": "frozen"}
        return {
            "agente": agente_nome,
            "versao": self._repo.versoes_skills_publicadas().get(agente_nome),
            "origem": "publicada",
        }

    # ----------------------------------------------------------------- privados
    def _executar_lado(
        self, skill: SkillVersao | None, entrada: dict[str, Any]
    ) -> dict[str, Any] | None:
        if skill is None:
            return None
        parseada = parse_skill_md(skill.skill_md)
        saida = self._llm.chat(
            judge.montar_mensagens_execucao(parseada.corpo, entrada),
            perfil=parseada.modelo_perfil,  # type: ignore[arg-type]  # validado §7.1
        )
        return {
            "skill_id": str(skill.id),
            "versao": skill.versao,
            "estado": skill.estado,
            "saida": saida,
        }

    def _parse_para_agente(self, agente: Agente, skill_md: str) -> SkillMd:
        parseada = parse_skill_md(skill_md)
        if parseada.nome != agente.nome:
            raise SkillMdInvalido(
                f"front-matter `name: {parseada.nome}` diverge do agente "
                f"{agente.nome!r} (§7.1 — a skill pertence ao agente).",
                erros=[f"name {parseada.nome!r} != agente {agente.nome!r}"],
            )
        return parseada

    def _agente(self, tenant_id: str, agente_id: uuid.UUID) -> Agente:
        agente = self._repo.obter_agente(tenant_id, agente_id)
        if agente is None:
            raise NaoEncontrado(f"Agente {agente_id} não encontrado no tenant {tenant_id!r}.")
        return agente

    def _skill_do_tenant(self, tenant_id: str, skill_id: uuid.UUID) -> tuple[SkillVersao, Agente]:
        skill = self._repo.obter_skill(skill_id)
        agente = self._repo.obter_agente(tenant_id, skill.agente_id) if skill is not None else None
        if skill is None or agente is None:  # tenant errado não vaza existência
            raise NaoEncontrado(f"Skill {skill_id} não encontrada no tenant {tenant_id!r}.")
        return skill, agente

    def _evento(self, tenant_id: str, tipo: str, payload: dict[str, Any], actor: str) -> None:
        self._repo.adicionar_evento(
            EventoDominio(
                tenant_id=tenant_id,
                os_id=None,  # eventos de PLATAFORMA (Ateliê não é escopado a OS)
                type=tipo,
                payload=payload,
                actor=actor,
                via_ai=False,
                created_at=self._relogio.agora(),
            )
        )


# ------------------------------------------------------------- helpers puros do módulo
def _agente_out(agente: Agente) -> dict[str, Any]:
    return {
        "id": str(agente.id),
        "tenant_id": agente.tenant_id,
        "nome": agente.nome,
        "camada": agente.camada,
        "etapa_workflow": agente.etapa_workflow,
        "modelo_perfil": agente.modelo_perfil,
        "deterministico": agente.deterministico,
    }


def _skill_resumo(skill: SkillVersao) -> dict[str, Any]:
    return {
        "id": str(skill.id),
        "versao": skill.versao,
        "estado": skill.estado,
        "harness_score": skill.harness_score,
        "publicada_em": skill.publicada_em.isoformat() if skill.publicada_em else None,
    }


def _skill_out(skill: SkillVersao, runs: list[HarnessRun]) -> dict[str, Any]:
    return {
        **_skill_resumo(skill),
        "agente_id": str(skill.agente_id),
        "skill_md": skill.skill_md,
        "execution_profile": skill.execution_profile,
        "bases_rag": skill.bases_rag,
        "harness_runs": [_run_out(r) for r in runs],
    }


def _run_out(run: HarnessRun) -> dict[str, Any]:
    return {
        "id": str(run.id),
        "skill_versao_id": str(run.skill_versao_id),
        "score": run.score,
        "passou": run.passou,
        "score_por_dimensao": run.resultados.get("score_por_dimensao"),
        "dimensoes_reprovadas": run.resultados.get("dimensoes_reprovadas"),
        "casos": len(run.resultados.get("casos") or []),
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }
