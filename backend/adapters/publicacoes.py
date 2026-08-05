"""Adapters de publicações — implementam PublicacoesPort (§2.1) para o GO (§8-M4-A2).

`PublicacoesLocais`: versões publicadas ATUAIS de agentes = front-matter dos SKILL.md
em `agents/skills/` (§7.1); política publicada = v1 do domínio (seed §11.4);
tarifário vigente = id fixo do seed (§11.4 — CRUD chega com o taxímetro do M7).
`PublicacoesAtelie` (M12): lê as versões publicadas do BANCO do Ateliê
(`skill_versao` §4.1) com fallback para o disco enquanto as seeds não rodaram — as
seeds espelham exatamente as versões do disco, então o GO congela os MESMOS valores
nas duas fontes (test_M4-A2 permanece válido). Trocar adapter não toca domínio nem
serviços (hexagonal §2.1).
"""

from decimal import Decimal
from pathlib import Path
from typing import Any

from agents.consultor import carregar_skill
from application.ports.repositorio_atelie import RepositorioAtelie
from application.ports.repositorio_plataforma import RepositorioPoliticas
from domain.custo.tarifas import TARIFAS_VIGENTES
from domain.governanca.politicas import POLITICA_PUBLICADA

SKILLS_DIR = Path(__file__).resolve().parents[1] / "agents" / "skills"
TARIFARIO_VIGENTE_ID = "tarifario-2026-v1"  # seed §11.4 (email/push/sms/whatsapp)


class PublicacoesLocais:
    def __init__(self, skills_dir: Path = SKILLS_DIR) -> None:
        self._skills_dir = skills_dir

    def versoes_agentes(self) -> dict[str, str]:
        versoes: dict[str, str] = {}
        for arquivo in sorted(self._skills_dir.glob("*.skill.md")):
            skill = carregar_skill(arquivo)
            versoes[skill.nome] = skill.versao
        return versoes

    def politica_publicada(self) -> dict[str, Any]:
        return dict(POLITICA_PUBLICADA)

    def tarifario_id(self) -> str:
        return TARIFARIO_VIGENTE_ID

    def tarifas_vigentes(self) -> dict[str, Decimal]:
        return dict(TARIFAS_VIGENTES)  # seed §11.4 (`tarifa_canal` §4.1)


class PublicacoesAtelie:
    """PublicacoesPort sobre o banco do Ateliê (M12) — o GO congela as versões
    publicadas ATUAIS de `skill_versao` e a política publicada ATUAL de
    `policy_versao` (§4.1, M12 parte 2); banco vazio (seeds ainda não rodaram) →
    fallback disco/domínio (MESMOS valores — a seed v1 espelha o fallback).
    Tarifário segue no fallback (CRUD fora do escopo v1 do M12). Dev é
    single-tenant (§3 DEFAULT_TENANT)."""

    def __init__(
        self,
        repositorio: RepositorioAtelie,
        fallback: PublicacoesLocais | None = None,
        politicas: RepositorioPoliticas | None = None,
    ) -> None:
        self._repo = repositorio
        self._fallback = fallback or PublicacoesLocais()
        self._politicas = politicas

    def versoes_agentes(self) -> dict[str, str]:
        versoes = self._repo.versoes_skills_publicadas()
        return versoes or self._fallback.versoes_agentes()

    def politica_publicada(self) -> dict[str, Any]:
        atual = self._politicas.politica_publicada_atual() if self._politicas is not None else None
        if atual is None:
            return self._fallback.politica_publicada()
        return {"versao": atual.versao, "estado": atual.estado, "conteudo": dict(atual.conteudo)}

    def tarifario_id(self) -> str:
        return self._fallback.tarifario_id()

    def tarifas_vigentes(self) -> dict[str, Decimal]:
        return self._fallback.tarifas_vigentes()
