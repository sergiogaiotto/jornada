"""Seeds do Ateliê (M12 · §11.4: "agentes+skills v1, 3 casos golden por agente" +
"políticas v1").

Idempotente e local (sem rede): agentes = roster com SKILL.md em `agents/skills/`
(§7.1 — o disco era a fonte da verdade até o M12; as seeds espelham exatamente essas
versões v1 como PUBLICADAS no banco) + o `guard` determinístico (§7.2 — sem skill,
NÃO invoca LLM) + as 5 TRIAGENS do §7.2 (A18: uma por célula IPO da esteira; triagem
não tem SKILL.md no disco, a v1.0 canônica é escrita aqui); golden dataset =
`mocks/seeds/harness_cases.json` (§4.1 `harness_case`). Assim o GO (§8-M4-A2) congela
do banco os MESMOS valores do disco e `test_M4` permanece válido. `semear_politicas`
(M12 parte 2) espelha a política v1 do domínio como linha PUBLICADA de `policy_versao`
(§4.1) — mesma versão/conteúdo do fallback do GO.

A18 (achado do UAT, Ateliê em produção com "0 triagens" e "— sem run"): a guarda
antiga era global ("já tem agente? não faz nada"), então um banco semeado por um
deploy ANTERIOR nunca recebia roster novo. Agora a guarda é por ENTIDADE (ids uuid5
determinísticos + `adicionar_*` que faz upsert por id no SQL): re-semear CONVERGE o
roster sem duplicar nada, e `_semear_harness_runs` fecha o quadro do demo com um run
VERDE por agente-chave sobre a v1.0 semeada — marcado `origem: "seed"`, sem LLM.
"""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from application.ports.repositorio_atelie import RepositorioAtelie
from application.ports.repositorio_plataforma import RepositorioPlataforma
from domain.atelie import harness as regras_harness
from domain.atelie.modelos import (
    DIMENSOES_PADRAO,
    Agente,
    HarnessCase,
    HarnessRun,
    SkillVersao,
)
from domain.atelie.skill_parser import parse_skill_md
from domain.governanca.modelos import PolicyVersao
from domain.governanca.politicas import POLITICA_PUBLICADA

SKILLS_DIR = Path(__file__).resolve().parents[1] / "agents" / "skills"
CASOS_PADRAO = Path(__file__).resolve().parents[2] / "mocks" / "seeds" / "harness_cases.json"

VERSAO_TRIAGEM = "1.0"

# --- A18 · as 5 TRIAGENS do roster §7.2 ("triagem_* (5) | 20b | por esteira |
# roteamento + checklist da célula IPO"). Uma por célula da Esteira de Produção; o
# corpo da skill é curto e diz o que a camada faz — rotear e conferir, nunca executar
# a tarefa do especialista nem decidir portão (§1.1.3: decisão é humana).
TRIAGENS: tuple[dict[str, Any], ...] = (
    {
        "celula": "intake",
        "titulo": "Intake",
        "etapa": "briefing",
        "rotas": ("consultor",),
        "checklist": (
            "objetivo, público e oferta declarados pelo solicitante",
            "verba e janela dentro da vigência da oferta",
            "os 14 campos do briefing sem lacuna silenciosa",
        ),
    },
    {
        "celula": "audiencia",
        "titulo": "Audiência",
        "etapa": "audiencia",
        "rotas": ("engineer", "guard"),
        "checklist": (
            "cada coluna do SQL com evidência no dicionário de dados",
            "as 7 listas de exclusão presentes no WHERE",
            "opt-in por canal e volume estimado registrados",
        ),
    },
    {
        "celula": "criativo",
        "titulo": "Criativos",
        "etapa": "criativos",
        "rotas": ("visual", "copy", "content"),
        "checklist": (
            "KV master aprovado antes da matriz canal×variante",
            "limites por canal (e-mail, push, SMS, WhatsApp) respeitados",
            "linguagem sem promessa que a oferta não sustenta",
        ),
    },
    {
        "celula": "jornada",
        "titulo": "Jornada",
        "etapa": "jornada",
        "rotas": ("flow",),
        "checklist": (
            "grafo JGC sem nó órfão e com braços somando 100%",
            "holdout presente quando há experimento pré-registrado",
            "waits e quiet hours dentro da janela da campanha",
        ),
    },
    {
        "celula": "operacao",
        "titulo": "Operação",
        "etapa": "disparo",
        "rotas": ("guard",),
        "checklist": (
            "pré-voo verde e aprovação humana registrada antes do disparo",
            "plano do compilador revisado, com os avisos destrutivos lidos",
            "tarifário e verba conferidos contra o previsto do ensaio",
        ),
    },
)

# --- A18 · runs de VITRINE do harness (§11.4) — nota BASE por dimensão (§7.3) de cada
# agente-chave. Banda 90–97 e todas ≥ 90: coerente com o portão §7.1 ("score ≥ 90 POR
# dimensão"), que é o que sustenta a v1.0 já nascer `publicada` nas seeds. `sync` está
# na lista do roster §7.2 e entra sozinho no dia em que ganhar SKILL.md no disco — sem
# agente ou sem golden dataset, o run NÃO é fabricado (nada de QA inventado).
NOTAS_HARNESS_SEED: dict[str, dict[str, int]] = {
    "consultor": {"correcao": 95, "evidencia": 93, "compliance": 96, "formato": 94},
    "engineer": {"correcao": 96, "evidencia": 94, "compliance": 96, "formato": 93},
    "flow": {"correcao": 94, "evidencia": 92, "compliance": 95, "formato": 96},
    "copy": {"correcao": 93, "evidencia": 91, "compliance": 96, "formato": 95},
    "sync": {"correcao": 95, "evidencia": 93, "compliance": 96, "formato": 92},
}
NOTA_SEED_PADRAO = 93  # dimensão fora do quadro acima (§4.1 permite outras por caso)
SAIDA_SEED = "(seed §11.4 — saída não regravada; rode o harness para julgar o texto atual)"


def _uuid_seed(rotulo: str) -> uuid.UUID:
    """Id DETERMINÍSTICO das seeds (A15): uuid5(NAMESPACE_URL, 'jornada/<rotulo>') —
    restart re-semeia com os MESMOS ids (links do T16 nunca quebram)."""
    return uuid.uuid5(uuid.NAMESPACE_URL, f"jornada/{rotulo}")


def semear_atelie(
    repositorio: RepositorioAtelie,
    *,
    tenant_id: str,
    agora: datetime,
    skills_dir: Path = SKILLS_DIR,
    casos_path: Path = CASOS_PADRAO,
) -> None:
    """Semeia agentes + skills v1 publicadas + golden cases + triagens + runs de seed.

    A guarda rápida é de COMPLETUDE (A18), não de "banco vazio": com o roster inteiro
    presente sai na hora (esta função roda em toda requisição do Ateliê); faltando
    qualquer nome, converge entidade a entidade — tudo com id uuid5, nada duplica.
    """
    if _nomes_do_roster(skills_dir) <= {a.nome for a in repositorio.listar_agentes(tenant_id)}:
        return
    casos_por_agente = _carregar_casos(casos_path)
    for arquivo in sorted(skills_dir.glob("*.skill.md")):
        agente = _semear_agente_publicado(
            repositorio,
            tenant_id=tenant_id,
            agora=agora,
            skill_md=arquivo.read_text(encoding="utf-8"),
        )
        _semear_casos_golden(repositorio, agente, casos_por_agente.get(agente.nome, []))
    # guard: determinístico (§7.2) — existe no roster, mas NÃO tem skill nem harness.
    guard = Agente(
        id=_uuid_seed("agente/guard"),
        tenant_id=tenant_id,
        nome="guard",
        camada="especialista",
        etapa_workflow="audiencia",
        modelo_perfil=None,
        deterministico=True,
    )
    if repositorio.obter_agente(tenant_id, guard.id) is None:
        repositorio.adicionar_agente(guard)
    for celula in TRIAGENS:  # A18: as 5 triagens do §7.2 (skill v1.0 publicada)
        _semear_agente_publicado(
            repositorio,
            tenant_id=tenant_id,
            agora=agora,
            skill_md=skill_md_triagem(celula),
        )
    _semear_harness_runs(repositorio, agora=agora)


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
            id=_uuid_seed(f"policy/v{POLITICA_PUBLICADA['versao']}"),
            tenant_id=tenant_id,
            versao=int(POLITICA_PUBLICADA["versao"]),
            conteudo=dict(POLITICA_PUBLICADA["conteudo"]),
            estado="publicada",
            publicada_em=agora,
        )
    )


def skill_md_triagem(celula: dict[str, Any]) -> str:
    """SKILL.md canônico §7.1 de uma triagem — front-matter na forma do SDD (pares
    `chave: valor` separados por 2+ espaços) + corpo curto: roteamento + checklist da
    célula IPO, com o que falta virando PENDÊNCIA humana (nunca suposição do 20b)."""
    itens = "\n".join(f"- {item}" for item in celula["checklist"])
    rotas = " | ".join(f'"{rota}"' for rota in (*celula["rotas"], "humano"))
    return (
        "---\n"
        f"name: triagem_{celula['celula']}      version: {VERSAO_TRIAGEM}"
        "      camada: triagem\n"
        f"modelo_perfil: 20b        etapa: {celula['etapa']}\n"
        "exige_evidencia: false    max_retries: 2\n"
        "saida: {formato: json}\n"
        "---\n"
        f"Você é a TRIAGEM da célula {celula['titulo']} da Esteira de Produção "
        "(plataforma Jornada).\n"
        "Você ROTEIA e CONFERE: nunca executa a tarefa do especialista, nunca decide\n"
        "portão e nunca completa por conta própria o que o material não trouxer.\n"
        "\n"
        "Checklist da célula:\n"
        f"{itens}\n"
        "\n"
        "Item sem evidência no material recebido é `ok: false` e vira PENDÊNCIA para um\n"
        "humano resolver — nada avança por suposição sua.\n"
        "\n"
        "Responda EXCLUSIVAMENTE com JSON neste formato:\n"
        f'{{"rota": {rotas},\n'
        ' "checklist": [{"item": "<item do checklist>", "ok": true|false}],\n'
        ' "pendencias": ["<o que falta, quando faltar>"]}\n'
    )


# ------------------------------------------------------------------ privados do módulo
def _nomes_do_roster(skills_dir: Path) -> set[str]:
    """Nomes esperados no roster SEM abrir arquivo (o agente é o stem de
    `<nome>.skill.md`) — só a guarda rápida usa isto; a semeadura em si lê e valida o
    front-matter (§7.1), então um stem divergente no máximo re-converge à toa."""
    return (
        {arquivo.name.removesuffix(".skill.md") for arquivo in skills_dir.glob("*.skill.md")}
        | {"guard"}
        | {f"triagem_{celula['celula']}" for celula in TRIAGENS}
    )


def _semear_agente_publicado(
    repositorio: RepositorioAtelie, *, tenant_id: str, agora: datetime, skill_md: str
) -> Agente:
    """Agente + skill v1 PUBLICADA a partir de um SKILL.md canônico (§7.1). Idempotente
    por id uuid5: o que já está no banco NÃO é reescrito (edição do operador vence)."""
    parseada = parse_skill_md(skill_md)
    agente = Agente(
        id=_uuid_seed(f"agente/{parseada.nome}"),
        tenant_id=tenant_id,
        nome=parseada.nome,
        camada=parseada.camada,
        etapa_workflow=parseada.etapa or None,
        modelo_perfil=parseada.modelo_perfil,
        deterministico=False,
    )
    if repositorio.obter_agente(tenant_id, agente.id) is None:
        repositorio.adicionar_agente(agente)
    skill_id = _id_skill_seed(parseada.nome, parseada.versao)
    if repositorio.obter_skill(skill_id) is None:
        repositorio.adicionar_skill(
            SkillVersao(
                id=skill_id,
                agente_id=agente.id,
                versao=parseada.versao,
                skill_md=skill_md,
                execution_profile=parseada.execution_profile(),
                bases_rag=list(parseada.bases_rag),
                estado="publicada",  # baseline v1 do §11.4 (o portão vale para as próximas)
                publicada_em=agora,
            )
        )
    return agente


def _semear_casos_golden(
    repositorio: RepositorioAtelie, agente: Agente, casos: list[dict[str, Any]]
) -> None:
    """3 casos golden por agente-chave (§11.4) — idempotente por id uuid5."""
    existentes = {caso.id for caso in repositorio.listar_harness_cases(agente.id)}
    for indice, caso in enumerate(casos, start=1):
        caso_id = _uuid_seed(f"harness-case/{agente.nome}/{indice}")
        if caso_id in existentes:
            continue
        repositorio.adicionar_harness_case(
            HarnessCase(
                id=caso_id,
                agente_id=agente.id,
                input=caso["input"],
                esperado=caso["esperado"],
                dimensoes=list(caso.get("dimensoes") or DIMENSOES_PADRAO),
            )
        )


def _semear_harness_runs(repositorio: RepositorioAtelie, *, agora: datetime) -> None:
    """A18: um `harness_run` VERDE de seed por agente-chave sobre a v1.0 semeada.

    O run é VITRINE (`origem: "seed"`) — nenhum LLM roda aqui —, mas é consistente com
    o domínio: notas por caso → `regras_harness.consolidar` (o MESMO consolidador do
    serviço) e `skill_md_hash` do texto semeado, de modo que o portão §8-M12-A1 aceita
    esse run como o que sustenta a v1.0 publicada. Sem agente ou sem golden dataset o
    run não é criado — QA não se fabrica (§1.3.5).
    """
    for nome, notas_base in NOTAS_HARNESS_SEED.items():
        agente = repositorio.obter_agente_por_nome(nome)
        if agente is None:
            continue  # agente-chave ainda sem SKILL.md no disco (ex.: `sync` §7.2)
        skills = repositorio.listar_skills(agente.id)
        skill = next((s for s in skills if s.id == _id_skill_seed(nome, s.versao)), None)
        if skill is None:
            continue
        casos = repositorio.listar_harness_cases(agente.id)
        run_id = _uuid_seed(f"harness-run/{nome}@{skill.versao}")
        if not casos or any(r.id == run_id for r in repositorio.listar_harness_runs(skill.id)):
            continue
        avaliacoes = [
            {
                "case_id": str(caso.id),
                "dimensoes": list(caso.dimensoes),
                "notas": {
                    dimensao: _nota_seed(
                        notas_base.get(dimensao, NOTA_SEED_PADRAO), indice, len(casos)
                    )
                    for dimensao in caso.dimensoes
                },
                "saida": SAIDA_SEED,
            }
            for indice, caso in enumerate(casos)
        ]
        consolidado = regras_harness.consolidar(avaliacoes)
        repositorio.adicionar_harness_run(
            HarnessRun(
                id=run_id,
                skill_versao_id=skill.id,
                resultados={
                    "casos": avaliacoes,
                    "score_por_dimensao": consolidado["score_por_dimensao"],
                    "dimensoes_reprovadas": consolidado["dimensoes_reprovadas"],
                    "skill_md_hash": regras_harness.hash_skill_md(skill.skill_md),
                    "origem": "seed",  # A18: run de vitrine (§11.4), não julgamento novo
                },
                score=consolidado["score"],
                passou=consolidado["passou"],
                created_at=agora,
            )
        )
        if skill.harness_score is None:  # o chip do roster T16 lê daqui
            skill.harness_score = consolidado["score"]
            repositorio.salvar_skill(skill)


def _nota_seed(base: int, indice: int, total: int) -> float:
    """Nota do caso: base do agente com ±1 caso a caso (média = a base) e clamp na
    banda 90–97 — variação plausível sem nunca cruzar o piso do portão (§7.1)."""
    return round(min(97.0, max(90.0, base + indice - (total - 1) / 2)), 2)


def _id_skill_seed(nome: str, versao: str) -> uuid.UUID:
    return _uuid_seed(f"skill/{nome}@{versao}")


def _carregar_casos(caminho: Path) -> dict[str, list[dict[str, Any]]]:
    if not caminho.exists():
        return {}
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    casos = dados.get("casos")
    return casos if isinstance(casos, dict) else {}
