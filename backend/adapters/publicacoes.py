"""Adapters de publicações — implementam PublicacoesPort (§2.1) para o GO (§8-M4-A2)
e para a política vigente de TODOS os portões (achado 8 do UAT #5).

`PublicacoesLocais`: versões publicadas ATUAIS de agentes = front-matter dos SKILL.md
em `agents/skills/` (§7.1); política = seed v1 do domínio (§11.4 — FALLBACK, nunca
fonte da verdade quando há banco); tarifário vigente = id fixo do seed (§11.4 — CRUD
chega com o taxímetro do M7).
`PublicacoesAtelie` (M12): lê as versões publicadas do BANCO do Ateliê
(`skill_versao` §4.1) e a política publicada do tenant (`policy_versao`), com fallback
para o disco/seed enquanto as seeds não rodaram — as seeds espelham exatamente as
versões do disco, então o GO congela os MESMOS valores nas duas fontes (test_M4-A2
permanece válido). Trocar adapter não toca domínio nem serviços (hexagonal §2.1).

`publicacoes_vigentes(repositorio)` é a fábrica ÚNICA usada pelas rotas: antes cada
router montava a sua (audiencia.py montava `PublicacoesLocais`, que ignora o banco —
era por ali que a política publicada deixava de governar o holdout).
"""

from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from agents.consultor import carregar_skill
from application.ports.publicacoes import ORIGEM_PUBLICADA, ORIGEM_SEED
from application.ports.repositorio_atelie import RepositorioAtelie
from application.ports.repositorio_plataforma import RepositorioPlataforma
from domain.custo.tarifas import TARIFAS_VIGENTES
from domain.governanca.politicas import POLITICA_SEED

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

    def politica_publicada(self, tenant_id: str | None = None) -> dict[str, Any]:
        """Seed §11.4 (sem banco não há tenant a distinguir — §3 single-tenant em dev)."""
        return {**POLITICA_SEED, "origem": ORIGEM_SEED}

    def politica_versionada(
        self, versao: int, tenant_id: str | None = None, *, origem: str | None = None
    ) -> dict[str, Any] | None:
        """Só conhece a v1 do seed — versão de banco não existe sem banco."""
        if int(versao) != int(POLITICA_SEED["versao"]):
            return None
        return {**POLITICA_SEED, "origem": ORIGEM_SEED}

    def tarifario_id(self) -> str:
        return TARIFARIO_VIGENTE_ID

    def tarifas_vigentes(self) -> dict[str, Decimal]:
        return dict(TARIFAS_VIGENTES)  # seed §11.4 (`tarifa_canal` §4.1)


class PublicacoesAtelie:
    """PublicacoesPort sobre o banco do Ateliê/plataforma (M12) — as versões publicadas
    ATUAIS de `skill_versao` e a política publicada ATUAL de `policy_versao` (§4.1, M12
    parte 2); banco vazio (seeds ainda não rodaram) → fallback disco/seed (MESMOS
    valores — a seed v1 espelha o fallback). Tarifário segue no fallback (CRUD fora do
    escopo v1 do M12)."""

    def __init__(
        self,
        repositorio: RepositorioAtelie,
        fallback: PublicacoesLocais | None = None,
        politicas: RepositorioPlataforma | None = None,
    ) -> None:
        self._repo = repositorio
        self._fallback = fallback or PublicacoesLocais()
        self._politicas = politicas

    def versoes_agentes(self) -> dict[str, str]:
        versoes = self._repo.versoes_skills_publicadas()
        return versoes or self._fallback.versoes_agentes()

    def politica_publicada(self, tenant_id: str | None = None) -> dict[str, Any]:
        atual = (
            self._politicas.politica_publicada_atual(tenant_id)
            if self._politicas is not None
            else None
        )
        if atual is None:
            return self._fallback.politica_publicada(tenant_id)
        return {
            "versao": atual.versao,
            "estado": atual.estado,
            "conteudo": dict(atual.conteudo),
            "origem": ORIGEM_PUBLICADA,
        }

    def politica_versionada(
        self, versao: int, tenant_id: str | None = None, *, origem: str | None = None
    ) -> dict[str, Any] | None:
        """Linha PUBLICADA daquela versão no tenant (§8-M4-A2: a congelada no GO).

        Draft nunca conta: o que a OS congelou foi uma versão publicada.

        `origem=ORIGEM_SEED` NÃO consulta o banco. Só `default_tenant` recebe
        `semear_politicas` (§11.4), então um tenant novo é governado pelo seed e o GO
        congela `policy_version=1` vindo dele; a PRIMEIRA política que esse tenant
        publica pela T16 nasce `max(existentes)+1 = 1` — mesmo número, outro conteúdo.
        Sem esse desvio o pacote assinaria a v1 do banco como se fosse a que governou a
        OS: exatamente o achado 8 (duas fontes para o mesmo carimbo), só que por colisão
        de numeração. `origem=None` (OS anterior ao campo) mantém banco→seed, que é a
        única informação que ela tem."""
        if origem == ORIGEM_SEED:
            return self._fallback.politica_versionada(versao, tenant_id, origem=origem)
        if self._politicas is not None and tenant_id is not None:
            for policy in self._politicas.listar_policies(tenant_id):
                if int(policy.versao) == int(versao) and policy.estado == "publicada":
                    return {
                        "versao": policy.versao,
                        "estado": policy.estado,
                        "conteudo": dict(policy.conteudo),
                        "origem": ORIGEM_PUBLICADA,
                    }
        if origem == ORIGEM_PUBLICADA:
            return None  # o GO viu uma linha publicada e ela sumiu: erro, não fallback
        return self._fallback.politica_versionada(versao, tenant_id, origem=origem)

    def tarifario_id(self) -> str:
        return self._fallback.tarifario_id()

    def tarifas_vigentes(self) -> dict[str, Decimal]:
        return self._fallback.tarifas_vigentes()


_FALLBACK_DISCO = PublicacoesLocais()


def publicacoes_vigentes(repositorio: object) -> PublicacoesAtelie:
    """Fábrica ÚNICA das rotas: publicações/política do BANCO, fallback seed §11.4.

    O repositório da app (`app.state.repositorio_os`) implementa todas as portas na
    MESMA instância (tipagem estrutural §2.1) — os casts só informam o mypy. Existe
    para não haver dois jeitos de montar a fonte da política: era assim que
    `api/v1/audiencia.py` acabava com `PublicacoesLocais` (constante) enquanto
    `api/v1/validacao.py` lia o banco.
    """
    return PublicacoesAtelie(
        cast(RepositorioAtelie, repositorio),
        fallback=_FALLBACK_DISCO,
        politicas=cast(RepositorioPlataforma, repositorio),
    )
