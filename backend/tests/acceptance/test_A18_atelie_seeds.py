"""A18 — o Ateliê demo não nasce vazio (achado do UAT: "0 triagens" e "— sem run").

Cobre as duas metades do achado: (1) o roster §7.2 traz as 5 TRIAGENS com skill v1.0
publicada e SKILL.md canônico §7.1; (2) cada agente-chave com golden dataset tem um
`harness_run` VERDE de seed (§11.4) — score ≥ 90 POR DIMENSÃO (§7.1), marcado
`origem: "seed"` — e o `harness_score` da skill (o chip do roster T16) preenchido.

E a causa-raiz: a semeadura convergia só em banco VAZIO, então um banco semeado por
um deploy anterior nunca recebia roster novo. Aqui a seed roda sobre banco já
populado e sobre si mesma — sem duplicar nada (ids uuid5 A15). Sem docker, sem LLM.
"""

import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from adapters.atelie_seeds import (
    NOTAS_HARNESS_SEED,
    TRIAGENS,
    semear_atelie,
)
from adapters.persistence.memoria import RepositorioOsMemoria
from domain.atelie.modelos import SCORE_MINIMO_PUBLICACAO, Agente
from domain.atelie.skill_parser import parse_skill_md

TENANT = "torre-movel"
HEADERS = {"X-Tenant": TENANT, "Authorization": "Bearer dev-analista"}
AGORA = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)

NOMES_TRIAGEM = {f"triagem_{celula['celula']}" for celula in TRIAGENS}


def _agentes(client: TestClient) -> dict[str, dict]:
    resposta = client.get("/api/v1/agentes", headers=HEADERS)
    assert resposta.status_code == 200, resposta.text
    return {a["nome"]: a for a in resposta.json()["agentes"]}


def test_A18_atelie_lista_as_5_triagens(client: TestClient) -> None:
    """T16 deixa de mostrar "0 triagens": as 5 células IPO do §7.2 no roster, camada
    triagem / perfil 20b, com a v1.0 PUBLICADA e SKILL.md canônico (§7.1)."""
    agentes = _agentes(client)
    assert NOMES_TRIAGEM <= set(agentes), f"triagens ausentes: {NOMES_TRIAGEM - set(agentes)}"
    assert len(NOMES_TRIAGEM) == 5

    for nome in sorted(NOMES_TRIAGEM):
        agente = agentes[nome]
        assert agente["camada"] == "triagem" and agente["modelo_perfil"] == "20b"  # §7.2
        assert agente["etapa_workflow"] and agente["versao_publicada"] == "1.0"
        skill_id = agente["skills"][-1]["id"]
        skill = client.get(f"/api/v1/skills/{skill_id}", headers=HEADERS)
        assert skill.status_code == 200, skill.text
        corpo = skill.json()
        assert corpo["estado"] == "publicada"
        parseada = parse_skill_md(corpo["skill_md"])  # front-matter canônico §7.1
        assert parseada.nome == nome and parseada.camada == "triagem"
        assert parseada.modelo_perfil == "20b" and parseada.saida == {"formato": "json"}
        assert "checklist" in parseada.corpo.lower()  # contrato do roster §7.2


def test_A18_harness_com_run_verde_por_agente_chave(client: TestClient) -> None:
    """T16 deixa de mostrar "— sem run": cada agente-chave COM golden dataset tem um
    run de seed verde (≥ 90 por dimensão §7.1) e o chip do roster com score."""
    agentes = _agentes(client)
    chaves = [nome for nome in NOTAS_HARNESS_SEED if nome in agentes]
    assert set(chaves) >= {"consultor", "engineer", "flow", "copy"}  # roster §7.2

    for nome in chaves:
        agente = agentes[nome]
        assert agente["skills"][-1]["harness_score"] is not None, f"{nome} sem score no roster"
        skill = client.get(f"/api/v1/skills/{agente['skills'][-1]['id']}", headers=HEADERS)
        runs = skill.json()["harness_runs"]
        assert len(runs) == 1, f"{nome}: esperado 1 run de seed, veio {len(runs)}"
        run = runs[-1]
        assert run["passou"] is True and run["dimensoes_reprovadas"] == []
        assert run["casos"] == 3  # 3 casos golden por agente-chave (§11.4)
        assert run["created_at"]
        notas = run["score_por_dimensao"]
        assert set(notas) == set(NOTAS_HARNESS_SEED[nome])
        assert all(SCORE_MINIMO_PUBLICACAO <= nota <= 97 for nota in notas.values()), notas
        assert run["score"] == agente["skills"][-1]["harness_score"]


def test_A18_run_de_seed_e_marcado_como_seed(client: TestClient, app) -> None:
    """O run de vitrine é rastreável (`origem: "seed"`) e amarrado ao texto julgado
    pelo `skill_md_hash` — nenhum LLM rodou para produzi-lo (§1.3.5)."""
    _agentes(client)  # dispara a semeadura tardia das rotas do Ateliê
    repositorio = app.state.repositorio_os
    agente = repositorio.obter_agente_por_nome("engineer")
    skill = repositorio.listar_skills(agente.id)[-1]
    run = repositorio.listar_harness_runs(skill.id)[-1]
    assert run.resultados["origem"] == "seed"
    assert run.resultados["skill_md_hash"]  # portão §8-M12-A1 aceita o run como atual
    assert all(caso["case_id"] for caso in run.resultados["casos"])


def test_A18_seeds_idempotentes_no_mesmo_repositorio() -> None:
    """Re-semear NÃO duplica: ids uuid5 (A15) + guarda por entidade. Dois boots com
    relógios diferentes deixam o mesmo roster, as mesmas skills, casos e runs."""
    repositorio = RepositorioOsMemoria()
    for horas in (0, 7):
        semear_atelie(
            repositorio,
            tenant_id=TENANT,
            agora=AGORA.replace(hour=12 + horas),
        )

    agentes = repositorio.listar_agentes(TENANT)
    nomes = [a.nome for a in agentes]
    assert len(nomes) == len(set(nomes)), f"agente duplicado: {nomes}"
    assert NOMES_TRIAGEM <= set(nomes)
    for agente in agentes:
        skills = repositorio.listar_skills(agente.id)
        assert len(skills) == len({s.id for s in skills}), f"skill duplicada em {agente.nome}"
        casos = repositorio.listar_harness_cases(agente.id)
        assert len(casos) == len({c.id for c in casos}), f"caso duplicado em {agente.nome}"
        for skill in skills:
            runs = repositorio.listar_harness_runs(skill.id)
            assert len(runs) == len({r.id for r in runs}), f"run duplicado em {agente.nome}"
            assert len(runs) <= 1


def test_A18_converge_banco_ja_semeado_por_deploy_anterior() -> None:
    """Causa-raiz do achado: com a guarda global antiga, banco COM agentes = no-op —
    o roster novo (triagens/runs) nunca chegava em produção. Agora converge."""
    repositorio = RepositorioOsMemoria()
    repositorio.adicionar_agente(  # "deploy anterior": roster incompleto no banco
        Agente(
            id=uuid.uuid5(uuid.NAMESPACE_URL, "jornada/agente/consultor"),
            tenant_id=TENANT,
            nome="consultor",
            camada="especialista",
            etapa_workflow="pedido",
            modelo_perfil="120b",
        )
    )

    semear_atelie(repositorio, tenant_id=TENANT, agora=AGORA)

    nomes = [a.nome for a in repositorio.listar_agentes(TENANT)]
    assert nomes.count("consultor") == 1  # o que já existia não duplicou
    assert NOMES_TRIAGEM <= set(nomes)  # e o roster novo entrou
    consultor = repositorio.obter_agente_por_nome("consultor")
    skill = repositorio.listar_skills(consultor.id)[-1]
    assert repositorio.listar_harness_runs(skill.id), "run de seed não convergiu"
