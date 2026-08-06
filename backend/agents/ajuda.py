"""Agente ajuda (M-Guia — chat "IA, me ajude com esta página"; perfil 20b §3:
resumos/da UI) — lado determinístico.

Carrega o SKILL.md canônico (parser §7.1 compartilhado) e monta as mensagens de
chat: o CONTEXTO é o conteúdo do guia da página enviado pelo FRONT (fonte única em
`frontend/src/guia/conteudo.ts` — duplicar no back seria drift; a API valida o
tamanho ≤ 8k chars). O histórico é o da sessão do navegador (nada persistido além
do ledger `invocacao`). Guarda-corpo de PII (§10.2): o serviço mascara pergunta E
histórico com o sanitizador único (`domain.privacidade`, C02) ANTES de montar estas
mensagens — nem o prompt nem o ledger veem CPF/telefone/e-mail em claro. A recusa de
assunto fora da plataforma é instrução da skill (o chat é informativo: nenhuma ação
executa a partir dele).
"""

import json
from pathlib import Path

from agents.consultor import Skill, carregar_skill

SKILL_PATH = Path(__file__).resolve().parent / "skills" / "ajuda.skill.md"

# Contexto (conteúdo do guia da página) — limite do contrato §8-M-Guia
LIMITE_CONTEXTO = 8000

# papel do histórico do front → role OpenAI-style
_ROLES = {"usuario": "user", "ia": "assistant"}


def carregar() -> Skill:
    """SKILL.md do ajuda (§7.1) — cacheado pelo parser compartilhado."""
    return carregar_skill(SKILL_PATH)


def montar_mensagens(
    skill: Skill,
    *,
    pagina: str,
    contexto: str,
    historico: list[dict[str, str]],
    pergunta: str,
) -> list[dict[str, str]]:
    """Mensagens OpenAI-style: system = skill; contexto do guia da página como
    primeira mensagem de usuário; histórico da sessão intercalado; pergunta ao
    final. Nenhum dado bruto da plataforma — só o conteúdo DIDÁTICO do guia."""
    abertura = {
        "pagina": pagina,
        "contexto_do_guia": contexto,
        "instrucao": (
            "Responda só sobre a plataforma Jornada, com foco nesta página, "
            "usando o contexto_do_guia acima."
        ),
    }
    mensagens: list[dict[str, str]] = [
        {"role": "system", "content": skill.corpo},
        {"role": "user", "content": json.dumps(abertura, ensure_ascii=False)},
    ]
    for msg in historico:
        role = _ROLES.get(msg.get("papel", ""), "user")
        mensagens.append({"role": role, "content": msg.get("texto", "")})
    mensagens.append({"role": "user", "content": pergunta})
    return mensagens
