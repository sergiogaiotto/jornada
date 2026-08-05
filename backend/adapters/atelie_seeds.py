"""Seeds do Ateliê (M12 · §11.4: "agentes+skills v1, 3 casos golden por agente" +
"políticas v1").

Idempotente e local (sem rede): agentes = roster com SKILL.md em `agents/skills/`
(§7.1 — o disco era a fonte da verdade até o M12; as seeds espelham exatamente essas
versões v1 como PUBLICADAS no banco) + o `guard` determinístico (§7.2 — sem skill,
NÃO invoca LLM); golden dataset = `mocks/seeds/harness_cases.json` (§4.1
`harness_case`). Assim o GO (§8-M4-A2) congela do banco os MESMOS valores do disco e
`test_M4` permanece válido. `semear_politicas` (M12 parte 2) espelha a política v1 do
domínio como linha PUBLICADA de `policy_versao` (§4.1) — mesma versão/conteúdo do
fallback do GO.
"""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from application.ports.repositorio_atelie import RepositorioAtelie
from application.ports.repositorio_plataforma import RepositorioPlataforma
from domain.atelie.modelos import DIMENSOES_PADRAO, Agente, HarnessCase, SkillVersao
from domain.atelie.skill_parser import parse_skill_md
from domain.governanca.modelos import PolicyVersao
from domain.governanca.politicas import POLITICA_PUBLICADA

SKILLS_DIR = Path(__file__).resolve().parents[1] / "agents" / "skills"
CASOS_PADRAO = Path(__file__).resolve().parents[2] / "mocks" / "seeds" / "harness_cases.json"


def semear_atelie(
    repositorio: RepositorioAtelie,
    *,
    tenant_id: str,
    agora: datetime,
    skills_dir: Path = SKILLS_DIR,
    casos_path: Path = CASOS_PADRAO,
) -> None:
    """Semeia agentes + skills v1 publicadas + golden cases; no-op se já semeado."""
    if repositorio.listar_agentes(tenant_id):
        return
    casos_por_agente = _carregar_casos(casos_path)
    for arquivo in sorted(skills_dir.glob("*.skill.md")):
        texto = arquivo.read_text(encoding="utf-8")
        parseada = parse_skill_md(texto)
        agente = Agente(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            nome=parseada.nome,
            camada=parseada.camada,
            etapa_workflow=parseada.etapa or None,
            modelo_perfil=parseada.modelo_perfil,
            deterministico=False,
        )
        repositorio.adicionar_agente(agente)
        repositorio.adicionar_skill(
            SkillVersao(
                id=uuid.uuid4(),
                agente_id=agente.id,
                versao=parseada.versao,
                skill_md=texto,
                execution_profile=parseada.execution_profile(),
                bases_rag=list(parseada.bases_rag),
                estado="publicada",  # baseline v1 do §11.4 (o portão vale para as próximas)
                publicada_em=agora,
            )
        )
        for caso in casos_por_agente.get(parseada.nome, []):
            repositorio.adicionar_harness_case(
                HarnessCase(
                    id=uuid.uuid4(),
                    agente_id=agente.id,
                    input=caso["input"],
                    esperado=caso["esperado"],
                    dimensoes=list(caso.get("dimensoes") or DIMENSOES_PADRAO),
                )
            )
    # guard: determinístico (§7.2) — existe no roster, mas NÃO tem skill nem harness.
    repositorio.adicionar_agente(
        Agente(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            nome="guard",
            camada="especialista",
            etapa_workflow="audiencia",
            modelo_perfil=None,
            deterministico=True,
        )
    )


def semear_politicas(
    repositorio: RepositorioPlataforma, *, tenant_id: str, agora: datetime
) -> None:
    """Semeia a política v1 PUBLICADA (§11.4) em `policy_versao`; no-op se já semeada.

    Mesmos versão/conteúdo do fallback `PublicacoesLocais` — o GO (§8-M4-A2) congela
    `policy_version=1` com ou sem as seeds; drafts novos nascem v2+."""
    if repositorio.listar_policies(tenant_id):
        return
    repositorio.adicionar_policy(
        PolicyVersao(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            versao=int(POLITICA_PUBLICADA["versao"]),
            conteudo=dict(POLITICA_PUBLICADA["conteudo"]),
            estado="publicada",
            publicada_em=agora,
        )
    )


def _carregar_casos(caminho: Path) -> dict[str, list[dict[str, Any]]]:
    if not caminho.exists():
        return {}
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    casos = dados.get("casos")
    return casos if isinstance(casos, dict) else {}
