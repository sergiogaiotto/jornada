"""Conteúdo da política de IA Responsável — conjunto FECHADO de campos + validação.

Mesma doutrina do M12 (`domain/governanca/politicas.py`): conteúdo versionado, campos
fechados, erros ACUMULADOS (padrão do parser §7.1). E a MESMA correção que o achado 8
do UAT #5 obrigou: `POLITICA_IA_SEED` é SEMENTE e FALLBACK, **nunca fonte da verdade em
runtime** — quem governa é a linha publicada lida por porta e injetada no serviço.
Importar esta constante dentro de `application/services/` é o bug que o achado 8
descreve; o guarda-corpo de CI (`test_nenhum_servico_importa_a_seed_direto`, em
`tests/unit/test_F03_ia_responsavel.py`) falha se isso voltar a acontecer.

## Por que o conjunto é FECHADO (e por que isso é o antídoto do achado 8)

`validar_conteudo` REJEITA campo desconhecido. Isso não é purismo de schema: é o que
impede alguém de publicar um parâmetro bonito e inerte. Enquanto o enforcement de
`teto_tokens` não existir (hoje `invocacao.tokens` é sempre NULL — ver `retencao.py` e
o relatório da onda), o campo não pode ser aceito; aceitá-lo criaria exatamente a tela
que promete governar e não governa. **Campo novo entra junto com o teste de
enforcement que prova que ele muda comportamento, nunca antes.**

## Defaults conservadores (§10.2)

O default v1 reproduz EXATAMENTE o comportamento de hoje — mascarar tudo, propor nada
automaticamente, reter pelo mesmo prazo do M12, perfis iguais ao roster §7.2. Isso é
deliberado: publicar a v1 não pode mudar o comportamento de nenhuma OS em voo. A
política nasce igual ao presente e só aperta a partir daí, por ato humano versionado.
"""

from typing import Any

# ------------------------------------------------------------------ vocabulários
# Categorias = marcadores de `domain/privacidade/mascarar.py` (fonte única §10.2).
# Não há categoria "outros": o que o mascarador não classifica não é PII para a
# plataforma, e inventar uma categoria aqui criaria regra sem detector.
CATEGORIAS_PII: tuple[str, ...] = ("cpf", "cnpj", "email", "telefone", "cartao", "documento")

# `permitir` NÃO existe de propósito. O piso do C02 (mascarar sempre) é garantia de
# contrato, não default configurável: uma política capaz de DESLIGAR o mascaramento
# transformaria a tela de IA Responsável no maior vetor de vazamento da plataforma.
# A política só APERTA — mascarar (piso de hoje) ou bloquear (impede a chamada).
ACOES_DADO: tuple[str, ...] = ("mascarar", "bloquear")

# Ações via_ai automatizáveis (LGPD Art. 20). Vocabulário FECHADO e ancorado nos
# serviços que hoje escrevem no ledger `invocacao` — cada entrada corresponde a um
# span real. Fechado porque um typo na allowlist ("jornada.ajusta") passaria batido e
# o DPO acharia que autorizou algo que segue bloqueado — falha silenciosa na direção
# errada da auditoria.
ACOES_VIA_AI: tuple[str, ...] = (
    "consultor.preencher_briefing",  # §8-M3 · consultor_service
    "audiencia.montar_sql",  # §8-M5 · audiencia_service (engineer)
    "criativo.gerar",  # §8-M6 · criativo_service
    "jornada.ajustar",  # §8-M7 · jornada_service (flow) — o "propõe, humano aplica"
    "insight.responder",  # §8-M10 · insight_service
    "otimizacao.propor",  # §8-M11 · otimizacao_service (optimize)
    "ajuda.responder",  # §8-M-Guia · ajuda_service
)

# Perfis do §3 (roteamento 120b|20b). `PerfilModelo` vive em `application/ports/llm.py`;
# domínio não importa de application (§2.1) — a tupla é a mesma por contrato.
PERFIS_MODELO: tuple[str, ...] = ("120b", "20b")

# Roster §7.2: perfil declarado por agente. É o default de `modelos_permitidos` —
# a política nasce PINANDO o roster, não abrindo tudo.
PERFIL_DO_ROSTER: dict[str, tuple[str, ...]] = {
    "consultor": ("120b",),
    "engineer": ("120b",),
    "activate": ("120b",),
    "visual": ("120b",),
    "copy": ("120b",),
    "content": ("120b",),
    "flow": ("120b",),
    "simulate": ("120b",),
    "persona": ("120b",),
    "sync": ("120b",),
    "publish": ("120b",),
    "insight": ("120b",),
    "optimize": ("120b",),
    "calibrate": ("120b",),
    "maestro": ("120b",),
    "cost": ("20b",),
    "doc": ("20b",),
    "ajuda": ("20b",),
    # guard é DETERMINÍSTICO (§7.2/§1.1.2): o veredito é código; o 20b só EXPLICA o
    # veredito já decidido. Por isso ele aparece com 20b e não com lista vazia —
    # a explicação é uma chamada legítima; a decisão nunca chega ao modelo.
    "guard": ("20b",),
    # As 5 triagens do §7.2 (emenda A18) — camada triagem, 20b.
    "triagem_intake": ("20b",),
    "triagem_audiencia": ("20b",),
    "triagem_criativo": ("20b",),
    "triagem_jornada": ("20b",),
    "triagem_operacao": ("20b",),
}

# Conjunto FECHADO. Quatro campos, não seis — e a ausência dos outros dois é a parte
# mais importante deste arquivo:
#
# * `teto_tokens`/`teto_custo` (pedido (d)) NÃO entra porque `invocacao.tokens` é
#   SEMPRE NULL: `LLMPort.chat` devolve `str` e descarta `resposta.usage`. Um teto
#   sobre uma métrica que ninguém mede não é um teto, é um número numa tela. Entra na
#   onda em que a porta passar a devolver o `usage` (detalhe no relatório).
# * `rotulo_ia` (pedido (e)) NÃO entra porque o enforcement dele é a UI marcar a saída
#   de agente em ~10 telas — arquivos fora desta frente. A regra sem as telas seria um
#   booleano que ninguém lê.
#
# Os dois voltam junto com o teste que prova que mudam comportamento. É literalmente a
# regra que o achado 8 do UAT #5 cobrou, aplicada ao próprio módulo que nasce dele.
CAMPOS_CONTEUDO: tuple[str, ...] = (
    "dados_llm",  # (a) o que pode sair para o modelo
    "retencao",  # (b) por quanto tempo prompt/resposta ficam guardados
    "decisao_automatizada",  # (c) LGPD Art. 20
    "modelos_permitidos",  # (f) roster §7.2 pinado
)

# Mesmo teto do `retencao_dias` do M12 (`domain/governanca/politicas.py`, purge §10.4).
DIAS_RETENCAO_MAX = 36500

# Sub-conjunto FECHADO do bloco `retencao`. Fechado pelo mesmo motivo que
# `CAMPOS_CONTEUDO`, e com um alvo NOMEADO: `dias_ledger`.
#
# A primeira versão deste módulo trazia `dias_ledger` "para o ledger expirar junto com o
# M12". Medido, isso era um SEGUNDO relógio de retenção: quem apaga o ledger é o
# `purge_service` (§10.4), e ele lê `retencao_dias` da política do M12 pela
# `PublicacoesPort` — provado em `tests/acceptance/test_D01_purge.py`, onde publicar
# `retencao_dias: 30` muda o que some. Nada lia `dias_ledger`. O DPO publicaria
# `dias_ledger: 30`, a tela confirmaria, e o purge seguiria apagando com 180 — o achado
# 8 do UAT #5 reencenado dentro do módulo que nasceu para acabar com ele.
#
# Retenção do ledger tem dono, e o dono é o M12. Aqui fica só `dias_trace`, que é órfão
# lá: o trace do Langfuse é diagnóstico de engenharia, não prova legal, e o `retencao_dias`
# não fala dele. Publicar `dias_ledger` agora é ERRO com mensagem que aponta o campo certo.
CAMPOS_RETENCAO: tuple[str, ...] = ("reter_prompt", "reter_resposta", "dias_trace")


def politica_ia_seed() -> dict[str, Any]:
    """Conteúdo v1 (semente/fallback) — igual ao comportamento de HOJE, por decisão.

    Função e não constante de módulo: devolve estrutura NOVA a cada chamada, então
    ninguém muta o default global sem querer (um `conteudo["retencao"]["dias_ledger"] =
    1` num teste envenenaria todos os outros).
    """
    return {
        # (a) Piso do C02 preservado: tudo mascarado, nada bloqueado ainda. O primeiro
        # aperto recomendado ao DPO é `cartao: bloquear` (cartão em briefing de
        # marketing nunca é parâmetro legítimo — é sempre erro do solicitante).
        "dados_llm": {"acoes": dict.fromkeys(CATEGORIAS_PII, "mascarar")},
        # (b) "Reter o mínimo" é o mínimo NECESSÁRIO, não zero: o Art. 20 exige
        # reconstruir a decisão automatizada (`POST /auditoria/reconstruir/{id}`
        # devolve input/evidências/output da época). Zerar o prompt cumpriria
        # minimização violando o direito à explicação.
        # O PRAZO do ledger não mora aqui: é `retencao_dias` do M12, que o purge §10.4
        # já consome (ver `CAMPOS_RETENCAO`). Aqui fica o que é decisão de IA — gravar
        # ou não o texto — e o prazo do trace, que o M12 não cobre.
        "retencao": {
            "reter_prompt": True,
            "reter_resposta": True,
            "dias_trace": 30,  # trace é diagnóstico, não prova legal: janela menor
        },
        # (c) Art. 20 conservador: allowlist VAZIA = a IA propõe, humano aplica.
        "decisao_automatizada": {"pode_aplicar_sozinho": []},
        # (f) Roster §7.2 pinado.
        "modelos_permitidos": {nome: list(perfis) for nome, perfis in PERFIL_DO_ROSTER.items()},
    }


def validar_conteudo(conteudo: Any) -> list[str]:
    """Erros ACUMULADOS do conteúdo (§7.1) — lista vazia = válido.

    Acumula em vez de abortar no primeiro erro porque quem edita isto é o DPO pela
    tela: devolver um erro por vez transformaria a publicação numa gincana.
    """
    if not isinstance(conteudo, dict) or not conteudo:
        return ["conteudo deve ser objeto não-vazio (política de IA Responsável)"]
    erros: list[str] = []
    for campo in CAMPOS_CONTEUDO:
        if campo not in conteudo:
            erros.append(f"conteudo sem campo obrigatório {campo!r}")
    for campo in conteudo:
        if campo not in CAMPOS_CONTEUDO:
            erros.append(
                f"campo desconhecido {campo!r} — conjunto FECHADO: parâmetro só entra "
                "junto com o enforcement que prova que ele muda comportamento"
            )
    erros.extend(_erros_dados_llm(conteudo.get("dados_llm")) if "dados_llm" in conteudo else [])
    erros.extend(_erros_retencao(conteudo.get("retencao")) if "retencao" in conteudo else [])
    if "decisao_automatizada" in conteudo:
        erros.extend(_erros_decisao(conteudo.get("decisao_automatizada")))
    if "modelos_permitidos" in conteudo:
        erros.extend(_erros_modelos(conteudo.get("modelos_permitidos")))
    return erros


def _erros_dados_llm(bloco: Any) -> list[str]:
    if not isinstance(bloco, dict) or not isinstance(bloco.get("acoes"), dict):
        return ["dados_llm deve ser {acoes: {categoria: mascarar|bloquear}}"]
    erros: list[str] = []
    acoes = bloco["acoes"]
    for categoria in CATEGORIAS_PII:
        if categoria not in acoes:
            erros.append(
                f"dados_llm.acoes sem a categoria {categoria!r} — todas as categorias "
                "detectáveis precisam de ação declarada (omitir é deixar buraco mudo)"
            )
    for categoria, acao in acoes.items():
        if categoria not in CATEGORIAS_PII:
            erros.append(f"dados_llm.acoes: categoria desconhecida {categoria!r} (§10.2)")
        elif acao not in ACOES_DADO:
            erros.append(
                f"dados_llm.acoes[{categoria!r}] = {acao!r} inválida — use "
                f"{' ou '.join(ACOES_DADO)}. Não existe 'permitir': o mascaramento "
                "do C02 é piso de contrato, a política só aperta."
            )
    return erros


def _erros_retencao(bloco: Any) -> list[str]:
    if not isinstance(bloco, dict):
        return [f"retencao deve ser objeto com {', '.join(CAMPOS_RETENCAO)}"]
    erros: list[str] = []
    for campo in ("reter_prompt", "reter_resposta"):
        if not isinstance(bloco.get(campo), bool):
            erros.append(f"retencao.{campo} deve ser booleano")
    valor = bloco.get("dias_trace")
    if isinstance(valor, bool) or not isinstance(valor, int) or not 1 <= valor <= DIAS_RETENCAO_MAX:
        erros.append(f"retencao.dias_trace deve ser inteiro de 1 a {DIAS_RETENCAO_MAX} (§10.4)")
    # Sub-conjunto FECHADO: sem isto, remover `dias_ledger` do seed não bastaria —
    # publicar `retencao.dias_ledger: 30` passaria calado e o DPO acreditaria ter
    # encurtado a retenção do ledger, enquanto o purge seguiria com o `retencao_dias`
    # do M12. Campo inerte precisa ser REJEITADO, não apenas não-documentado.
    for campo in bloco:
        if campo == "dias_ledger":
            erros.append(
                "retencao.dias_ledger não existe nesta política — a retenção do ledger "
                "é `retencao_dias` na política do M12, que é quem o purge §10.4 lê. "
                "Publicar aqui não mudaria nada do que é apagado."
            )
        elif campo not in CAMPOS_RETENCAO:
            erros.append(
                f"retencao: campo desconhecido {campo!r} — conjunto FECHADO: "
                f"{', '.join(CAMPOS_RETENCAO)}"
            )
    return erros


def _erros_decisao(bloco: Any) -> list[str]:
    if not isinstance(bloco, dict) or not isinstance(bloco.get("pode_aplicar_sozinho"), list):
        return ["decisao_automatizada deve ser {pode_aplicar_sozinho: [acao, ...]}"]
    return [
        f"decisao_automatizada.pode_aplicar_sozinho: ação desconhecida {acao!r} — "
        f"vocabulário fechado: {', '.join(ACOES_VIA_AI)}"
        for acao in bloco["pode_aplicar_sozinho"]
        if acao not in ACOES_VIA_AI
    ]


def _erros_modelos(bloco: Any) -> list[str]:
    if not isinstance(bloco, dict) or not bloco:
        return ["modelos_permitidos deve ser {agente: [perfil, ...]} não-vazio (roster §7.2)"]
    erros: list[str] = []
    for agente, perfis in bloco.items():
        # Agente fora do roster §7.2 é REJEITADO pelo mesmo motivo que ação fora de
        # `ACOES_VIA_AI`: um typo ("enginer") viraria entrada morta, `perfis_permitidos`
        # cairia no roster e o `engineer` seguiria liberado. O DPO acreditaria ter
        # restringido um agente que continua aberto — falha silenciosa na direção errada
        # da auditoria, que é o pior modo de errar para um controle de governança.
        if agente not in PERFIL_DO_ROSTER:
            erros.append(
                f"modelos_permitidos: agente desconhecido {agente!r} — roster §7.2: "
                f"{', '.join(sorted(PERFIL_DO_ROSTER))}"
            )
        if not isinstance(perfis, list):
            erros.append(f"modelos_permitidos[{agente!r}] deve ser lista de perfis")
            continue
        for perfil in perfis:
            if perfil not in PERFIS_MODELO:
                erros.append(
                    f"modelos_permitidos[{agente!r}]: perfil {perfil!r} inválido — "
                    f"roteamento §3 usa {' e '.join(PERFIS_MODELO)}"
                )
    return erros
