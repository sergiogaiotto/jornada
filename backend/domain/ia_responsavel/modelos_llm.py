"""(f) MODELOS PERMITIDOS por agente — enforcement do parâmetro `modelos_permitidos`.

O roster §7.2 já declara um perfil por agente (`engineer: 120b`, `ajuda: 20b`...), mas
essa declaração vive no front-matter do SKILL.md: quem edita a skill troca o perfil, e
nada além da revisão de código percebe. Para um módulo de IA Responsável isso é pouco —
"qual modelo pode ver o dado deste tenant" é pergunta de governança, não de autoria de
skill.

Aqui a lista vira política do TENANT: a skill continua pedindo o perfil que quiser, mas
quem autoriza é a política publicada. Default = o próprio roster §7.2 (`PERFIL_DO_ROSTER`),
então a v1 não muda nada e o aperto é um ato explícito.

Nome do módulo é `modelos_llm.py` e não `modelos.py` porque, por convenção do projeto,
`modelos.py` em um contexto de domínio é o arquivo de ENTIDADES (§4.1) — que aqui existe
com esse mesmo nome.
"""

from typing import Any

from domain.ia_responsavel.erros import ModeloNaoPermitido
from domain.ia_responsavel.politica import PERFIL_DO_ROSTER


def perfis_permitidos(agente: str, conteudo: dict[str, Any]) -> tuple[str, ...]:
    """Perfis autorizados para o agente; cai no roster §7.2 quando a política cala.

    Agente ausente da política E do roster devolve `()` — nada autorizado. Isso é
    deliberado: um agente novo, que ninguém declarou em lugar nenhum, não deve ganhar
    acesso a modelo por omissão. O erro aparece na primeira chamada, que é quando o
    autor ainda lembra do que fez.
    """
    bloco = conteudo.get("modelos_permitidos") if isinstance(conteudo, dict) else None
    if isinstance(bloco, dict) and agente in bloco:
        perfis = bloco[agente]
        if isinstance(perfis, list):
            return tuple(p for p in perfis if isinstance(p, str))
    return PERFIL_DO_ROSTER.get(agente, ())


def perfil_autorizado(agente: str, perfil: str, conteudo: dict[str, Any]) -> bool:
    return perfil in perfis_permitidos(agente, conteudo)


def exigir_perfil_autorizado(agente: str, perfil: str, conteudo: dict[str, Any]) -> None:
    """Levanta `ModeloNaoPermitido` se o perfil não estiver liberado para o agente.

    Forma imperativa para o serviço chamar imediatamente antes de `LLMPort.chat` — a
    checagem precisa acontecer no ponto da chamada, não no carregamento da skill, senão
    um caminho que monte o perfil dinamicamente escapa do portão.
    """
    if not perfil_autorizado(agente, perfil, conteudo):
        permitidos = perfis_permitidos(agente, conteudo)
        raise ModeloNaoPermitido(
            f"A política de IA Responsável não autoriza o perfil {perfil!r} para o agente "
            f"{agente!r} (permitidos: {', '.join(permitidos) or 'nenhum'}). "
            "A chamada ao modelo não foi feita.",
            agente=agente,
            perfil=perfil,
        )
