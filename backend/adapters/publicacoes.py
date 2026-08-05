"""Adapter local de publicações — implementa PublicacoesPort (§2.1) para o GO (§8-M4-A2).

Versões publicadas ATUAIS de agentes = front-matter dos SKILL.md em `agents/skills/`
(§7.1 — enquanto o Ateliê/M12 não versiona em banco, o disco é a fonte da verdade);
política publicada = v1 do domínio (seed §11.4); tarifário vigente = id fixo do seed
(§11.4 — CRUD chega com o taxímetro do M7). Trocar por leitura de banco não toca
domínio nem serviços (hexagonal §2.1).
"""

from pathlib import Path
from typing import Any

from agents.consultor import carregar_skill
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
