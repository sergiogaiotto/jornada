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
from application.ports.publicacoes_ia import RepositorioPoliticaIa
from application.ports.repositorio_atelie import RepositorioAtelie
from application.ports.repositorio_plataforma import RepositorioPlataforma
from domain.custo.tarifas import TARIFAS_VIGENTES
from domain.governanca.politicas import POLITICA_SEED
from domain.ia_responsavel.politica import politica_ia_seed

SKILLS_DIR = Path(__file__).resolve().parents[1] / "agents" / "skills"
TARIFARIO_VIGENTE_ID = "tarifario-2026-v1"  # seed §11.4 (email/push/sms/whatsapp)

# Versão RESERVADA do default conservador de IA Responsável (§10.2). Publicação começa
# em 1 (`max(existentes)+1`), então 0 nunca colide com uma versão que alguém assinou.
#
# Isto conserta, no módulo novo, o defeito que `ports/publicacoes.py` documenta e não
# pode mais corrigir no M12: lá o seed também é "v1", igual à primeira publicação de um
# tenant, e só a `origem` distingue as duas. Aqui o NÚMERO sozinho já é honesto — v0 é,
# por construção, "ninguém publicou nada; isto é o de fábrica". A `origem` continua
# viajando junto porque é ela que a tela e o ledger citam.
VERSAO_DEFAULT_IA = 0


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

    def politica_ia_publicada(self, tenant_id: str | None = None) -> dict[str, Any]:
        """DEFAULT conservador de IA Responsável (§10.2) — o governo do primeiro boot.

        **É aqui que o default mora em runtime**, e não em `politica_ia` semeada: a
        semente é do domínio (`politica_ia_seed`, função pura), este adapter é o único
        que a materializa, e nenhum serviço a conhece (guarda-corpo de CI do F03).

        Deliberadamente NÃO existe `semear_politicas_ia` espelhando `semear_politicas`
        do M12. Semear criaria uma linha `estado='publicada'` sem autor humano — a tela
        do DPO mostraria "v1, publicada", a auditoria perguntaria "quem autorizou?" e a
        resposta seria "o boot da aplicação". Para uma política que responde pelo
        Art. 20 da LGPD isso é pior que não ter linha: é assinatura falsa. Sem linha, a
        tela diz a verdade — *vigora o default de fábrica, ninguém publicou ainda*.
        """
        return self.politica_ia_default()

    def politica_ia_default(self) -> dict[str, Any]:
        """O conservador de fábrica, materializado da semente do domínio (§10.2)."""
        return {
            "versao": VERSAO_DEFAULT_IA,
            "estado": "publicada",  # governa de fato; não é rascunho de ninguém
            "conteudo": politica_ia_seed(),  # estrutura NOVA a cada chamada (nunca mutável global)
            "origem": ORIGEM_SEED,
            "autor_nome": None,
            "publicado_por_nome": None,
            "publicada_em": None,
            "motivo": None,
        }

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
        politicas_ia: RepositorioPoliticaIa | None = None,
    ) -> None:
        self._repo = repositorio
        self._fallback = fallback or PublicacoesLocais()
        self._politicas = politicas
        self._politicas_ia = politicas_ia

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

    def politica_ia_publicada(self, tenant_id: str | None = None) -> dict[str, Any]:
        """Política de IA Responsável PUBLICADA do tenant; sem linha → default de fábrica.

        O fallback é explícito na resposta (`origem`), nunca silencioso — é a lição do
        achado crítico da onda 3. E o corte é por TENANT: `politica_ia_publicada_atual`
        filtra pelo tenant recebido, então tenant B nunca é governado pelo aperto que o
        tenant A publicou; ele cai no default, com `origem=seed` dizendo isso.
        """
        atual = (
            self._politicas_ia.politica_ia_publicada_atual(tenant_id)
            if self._politicas_ia is not None
            else None
        )
        if atual is None:
            return self._fallback.politica_ia_publicada(tenant_id)
        return {
            "versao": atual.versao,
            "estado": atual.estado,
            "conteudo": dict(atual.conteudo),
            "origem": ORIGEM_PUBLICADA,
            "autor_nome": atual.autor_nome,
            "publicado_por_nome": atual.publicado_por_nome,
            "publicada_em": atual.publicada_em,
            "motivo": atual.motivo,
        }

    def politica_ia_default(self) -> dict[str, Any]:
        return self._fallback.politica_ia_default()

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
        politicas_ia=cast(RepositorioPoliticaIa, repositorio),
    )
