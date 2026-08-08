"""Casos de uso da política de IA Responsável (§10.2, F03) — via ports (§2.1).

Três operações, nenhuma delas com LLM em caminho de veredito (§1.1.3 — compliance é
código): listar as versões do tenant, ler a VIGENTE, e PUBLICAR uma versão nova.

## De onde vem a política aqui dentro

Deste arquivo **não sai um único import da semente do domínio**. A vigente chega pela
`PublicacoesIaPort` (`self._publicacoes`), e o formulário nasce do
`politica_ia_default()` da mesma porta. O guarda-corpo de CI
(`test_nenhum_servico_importa_a_seed_direto`, em `tests/unit/test_F03_ia_responsavel.py`)
quebra se alguém trouxer a constante para cá — que é como o achado 8 do UAT #5 nasceu:
tela publicando no banco, portão lendo constante compilada.

O que ESTE módulo importa do domínio são VOCABULÁRIOS FECHADOS e a validação
(`validar_conteudo`) — o mesmo que `plataforma_service` faz com `domain.governanca.
politicas`. Vocabulário não é estado: é o contrato que diz quais campos existem.

## Publicar é um ato só (e por que não há draft nesta frente)

O M12 tem ciclo `draft → publicada` com duas rotas. Aqui a publicação é UMA rota, e a
linha nasce `publicada` com `autor_*` e `publicado_por_*` preenchidos com a MESMA
pessoa. Isso não finge segregação de funções: registra o fato de que uma pessoa fez os
dois atos, e um auditor lê os dois campos e vê que são iguais. O par existe separado na
entidade (`domain/ia_responsavel/modelos.py`) porque o dia em que o rascunho de política
de IA entrar, os campos já estão lá para contar a história certa — mas inventar hoje um
estado `draft` que ninguém revisa criaria cerimônia sem revisor, que é a versão
burocrática do mesmo teatro que este módulo existe para combater.

## `motivo` é obrigatório

Não é campo de conveniência: uma política de privacidade que muda sem justificativa
escrita é exatamente o que uma auditoria pede para ver e não encontra. A recusa é 422 —
o mesmo canal de erro do conteúdo inválido.
"""

import uuid
from datetime import datetime
from typing import Any

from application.ports.clock import ClockPort
from application.ports.publicacoes_ia import (
    ORIGEM_SEED,
    PublicacoesIaPort,
    RepositorioPoliticaIa,
)
from domain.campanha.modelos import EventoDominio
from domain.ia_responsavel import (
    ACOES_VIA_AI,
    CATEGORIAS_PII,
    DETECCAO_DA_CATEGORIA,
    NATUREZA_CONTEXTO,
    NATUREZA_FORMA,
    PERFIL_DO_ROSTER,
    PoliticaIa,
    PoliticaIaInvalida,
    validar_conteudo,
)
from domain.ia_responsavel.teto import teto_tokens_diario

# Rótulos das categorias de PII para a tela do DPO. Vivem aqui (application) e não no
# domínio porque são APRESENTAÇÃO: mudar "cartao" para "Cartão de crédito" não muda
# regra nenhuma. O que o domínio não pode perder é a chave técnica — e ela continua
# vindo de `CATEGORIAS_PII`, então uma categoria nova sem rótulo aparece com a própria
# chave em vez de sumir da tela.
_ROTULO_PII: dict[str, str] = {
    "cpf": "CPF",
    "cnpj": "CNPJ",
    "email": "E-mail",
    "telefone": "Telefone",
    "cartao": "Cartão de crédito",
    "documento": "Documento (identificador longo)",
    # Titular identificado (onda 3c). Sem estes rótulos a tela mostrava a CHAVE crua
    # (`data_nascimento`) para cinco das onze categorias — o fallback de `_ROTULO_PII`
    # impede que sumam, não as torna legíveis.
    "nome": "Nome do titular",
    "endereco": "Endereço",
    "cep": "CEP",
    "data_nascimento": "Data de nascimento",
    "rg": "RG",
}

# Como a categoria é detectada, em português do DPO (F04). É APRESENTAÇÃO: a natureza em
# si (`forma`/`contexto`) e os buracos concretos vêm do domínio, junto do detector; aqui
# fica só a frase que explica a natureza na tela.
#
# A frase de `contexto` diz a coisa desconfortável na cara: escolher `bloquear` numa
# categoria de contexto só bloqueia quando a detecção dispara. Sem isso a tela continua
# dizendo "INTERROMPE a chamada" com a mesma firmeza para `cpf` (que sempre dispara) e
# para `nome` (que dispara às vezes) — e a firmeza igual sobre confianças diferentes é a
# forma que o achado 8 assume aqui.
_NATUREZA_ROTULO: dict[str, str] = {
    NATUREZA_FORMA: "detecta por forma",
    NATUREZA_CONTEXTO: "detecta por contexto — cobertura parcial",
}
_NATUREZA_TEXTO: dict[str, str] = {
    NATUREZA_FORMA: (
        "O formato basta para reconhecer o dado, e onde ele é ambíguo há um código que "
        "confirma (dígito verificador de CPF/CNPJ, Luhn do cartão). O que tem a forma é "
        "encontrado sempre, no texto livre e nos campos."
    ),
    NATUREZA_CONTEXTO: (
        "Este dado NÃO tem formato próprio: o que o denuncia é como ele aparece escrito "
        "(a palavra que vem antes, a maiúscula, a pontuação). A cobertura é PARCIAL e os "
        "buracos abaixo são conhecidos — nesses casos o dado sai em claro, e escolher "
        "“bloquear” não interrompe chamada nenhuma, porque não houve detecção."
    ),
}

_MOTIVO_MIN = 5


class ServicoIaResponsavel:
    def __init__(
        self,
        repositorio: RepositorioPoliticaIa,
        relogio: ClockPort,
        publicacoes: PublicacoesIaPort,
    ) -> None:
        self._repo = repositorio
        self._relogio = relogio
        self._publicacoes = publicacoes

    # ------------------------------------------------------------------- leituras
    def listar(self, tenant_id: str) -> dict[str, Any]:
        """Histórico de versões do tenant + a vigente (com origem) — a tela inteira."""
        return {
            "politicas": [_politica_out(p) for p in self._repo.listar_politicas_ia(tenant_id)],
            "vigente": self.vigente(tenant_id),
        }

    def vigente(self, tenant_id: str) -> dict[str, Any]:
        """A política que GOVERNA agora + o que cada parâmetro faz, em português.

        `origem` viaja sempre: `seed` = default de fábrica, ninguém publicou;
        `policy_versao` = linha assinada por um humano deste tenant. A tela mostra a
        diferença porque a diferença é o que uma auditoria pergunta.
        """
        publicada = dict(self._publicacoes.politica_ia_publicada(tenant_id))
        conteudo = dict(publicada.get("conteudo") or {})
        default = self._publicacoes.politica_ia_default()
        return {
            **publicada,
            "publicada_em": _iso(publicada.get("publicada_em")),
            "nunca_publicada": publicada.get("origem") == ORIGEM_SEED,
            "efeitos": efeitos_em_portugues(conteudo),
            # O conservador de fábrica acompanha SEMPRE a resposta: é o preenchimento
            # inicial do formulário e a régua contra a qual o DPO lê o que está valendo.
            "default_conservador": default.get("conteudo") or {},
            "vocabulario": _vocabulario(),
        }

    # ----------------------------------------------------------------- publicação
    def publicar(
        self,
        tenant_id: str,
        *,
        conteudo: dict[str, Any],
        motivo: str,
        autor_id: uuid.UUID,
        autor_nome: str,
    ) -> dict[str, Any]:
        """Publica uma versão nova (§10.2) — o ato que MUDA o governo da plataforma.

        Ordem deliberada: valida o conteúdo ANTES de calcular a versão. Numerar primeiro
        e falhar depois deixaria buracos na sequência a cada tentativa malsucedida, e
        sequência de política com buracos é a primeira coisa que um auditor pergunta.
        """
        erros = validar_conteudo(conteudo)
        if not motivo or len(motivo.strip()) < _MOTIVO_MIN:
            erros = [
                f"motivo: obrigatório e com pelo menos {_MOTIVO_MIN} caracteres — "
                "mudança de política de privacidade sem justificativa escrita é o que "
                "uma auditoria pede para ver e não encontra",
                *erros,
            ]
        if erros:
            raise PoliticaIaInvalida(
                f"Conteúdo fora do conjunto FECHADO da política de IA Responsável — "
                f"{len(erros)} erro(s).",
                erros=erros,
            )
        agora = self._relogio.agora()
        versao = max((p.versao for p in self._repo.listar_politicas_ia(tenant_id)), default=0) + 1
        politica = PoliticaIa(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            versao=versao,
            conteudo=dict(conteudo),
            estado="publicada",
            autor_id=autor_id,
            autor_nome=autor_nome,
            criada_em=agora,
            publicada_em=agora,
            publicado_por_id=autor_id,
            publicado_por_nome=autor_nome,
            motivo=motivo.strip(),
        )
        self._repo.adicionar_politica_ia(politica)
        self._repo.adicionar_evento(
            EventoDominio(
                tenant_id=tenant_id,
                os_id=None,  # política de PLATAFORMA: não é escopada a OS (nem congelada)
                type="politica_ia.publicada",
                payload={
                    "versao": versao,
                    "politica_id": str(politica.id),
                    "motivo": politica.motivo,
                    # Diferenças em relação ao conservador, no corpo do evento: quem lê a
                    # trilha de auditoria não deveria ter de baixar dois JSONs e comparar
                    # à mão para saber o que foi afrouxado.
                    "apertos": _apertos(
                        dict(self._publicacoes.politica_ia_default().get("conteudo") or {}),
                        dict(conteudo),
                    ),
                },
                actor=autor_nome,
                via_ai=False,
                created_at=agora,
            )
        )
        return self.vigente(tenant_id)


# ------------------------------------------------------------- helpers puros do módulo
def _politica_out(politica: PoliticaIa) -> dict[str, Any]:
    return {
        "id": str(politica.id),
        "tenant_id": politica.tenant_id,
        "versao": politica.versao,
        "estado": politica.estado,
        "conteudo": politica.conteudo,
        "autor_nome": politica.autor_nome,
        "publicado_por_nome": politica.publicado_por_nome,
        "criada_em": _iso(politica.criada_em),
        "publicada_em": _iso(politica.publicada_em),
        "motivo": politica.motivo,
    }


def _iso(valor: Any) -> str | None:
    return valor.isoformat() if isinstance(valor, datetime) else (valor if valor else None)


def _categoria_out(categoria: str) -> dict[str, Any]:
    """Uma linha do seletor de PII: chave técnica, rótulo e a CONFIANÇA do detector."""
    deteccao = DETECCAO_DA_CATEGORIA[categoria]
    return {
        "chave": categoria,
        "rotulo": _ROTULO_PII.get(categoria, categoria),
        "natureza": deteccao.natureza,
        "natureza_rotulo": _NATUREZA_ROTULO[deteccao.natureza],
        "natureza_texto": _NATUREZA_TEXTO[deteccao.natureza],
        "exemplo_detectado": deteccao.detecta,
        "limites": [
            {"texto": limite.texto, "exemplo": limite.exemplo, "chave": limite.chave}
            for limite in deteccao.limites
        ],
    }


def _vocabulario() -> dict[str, Any]:
    """Conjuntos FECHADOS servidos ao formulário — a UI não redigita vocabulário.

    Se a tela mantivesse a própria lista de categorias/ações/agentes, ela divergiria do
    domínio na primeira mudança e o DPO veria um formulário que oferece opções que o
    servidor rejeita (ou, pior, esconde opções que existem).

    Cada categoria viaja com a NATUREZA da detecção e, quando há, os LIMITES do detector
    (F04). Pelo mesmo motivo: escritos no React, os buracos envelhecem na primeira mexida
    em `mascarar.py` e a tela passa a mentir na direção contrária — avisando de um buraco
    já fechado, ou calando sobre um novo. Aqui eles descem do domínio, onde um teste roda
    o detector sobre o exemplo de cada limite a cada CI.
    """
    return {
        "categorias_pii": [_categoria_out(c) for c in CATEGORIAS_PII],
        "acoes_dado": ["mascarar", "bloquear"],
        "acoes_via_ai": list(ACOES_VIA_AI),
        "agentes": {nome: list(perfis) for nome, perfis in PERFIL_DO_ROSTER.items()},
    }


def _efeito_da_categoria(categoria: str, acao: Any) -> str:
    """A frase de efeito de UMA categoria — com a ressalva de confiança quando cabe.

    Toda frase deste módulo começa com "detectado": era um advérbio invisível quando as
    seis categorias originais eram todas de FORMA (detectar era garantido). Com as de
    CONTEXTO, "detectado" virou a palavra que carrega o risco inteiro, e dizer
    "INTERROMPE a chamada" com a mesma firmeza para `cpf` e para `nome` é prometer ao
    DPO uma cobertura que só uma das duas tem. A ressalva desfaz isso na mesma frase —
    não numa nota de rodapé que ninguém lê (F04).
    """
    rotulo = _ROTULO_PII.get(categoria, categoria)
    if acao == "bloquear":
        frase = f"{rotulo} detectado INTERROMPE a chamada ao modelo: o texto não sai do perímetro."
    else:
        frase = f"{rotulo} sai mascarado (o modelo recebe o marcador, nunca o valor real)."
    if DETECCAO_DA_CATEGORIA[categoria].natureza == NATUREZA_CONTEXTO:
        frase += (
            " Detecção por CONTEXTO: vale quando o dado aparece de forma reconhecível — "
            "o formulário abaixo lista os casos em que ele sai em claro."
        )
    return frase


def efeitos_em_portugues(conteudo: dict[str, Any]) -> list[dict[str, Any]]:
    """Tradução do `conteudo` vigente em frases de EFEITO, para o DPO ler sem código.

    Regra de redação: cada frase descreve o que ACONTECE na plataforma, no presente do
    indicativo — "a chamada ao modelo é interrompida", não "recomenda-se bloquear".
    Parâmetro cujo efeito não dá para escrever assim é parâmetro que não governa, e
    parâmetro que não governa não entra no conjunto fechado (é a régua de `politica.py`).
    """
    acoes = dict((conteudo.get("dados_llm") or {}).get("acoes") or {})
    retencao = dict(conteudo.get("retencao") or {})
    automatizaveis = list(
        (conteudo.get("decisao_automatizada") or {}).get("pode_aplicar_sozinho") or []
    )
    modelos = dict(conteudo.get("modelos_permitidos") or {})
    teto_diario = teto_tokens_diario(conteudo)  # (d) J02 — None = sem teto

    bloqueadas = [c for c in CATEGORIAS_PII if acoes.get(c) == "bloquear"]
    return [
        {
            "parametro": "dados_llm",
            "titulo": "Dados que podem sair para o modelo",
            "resumo": (
                f"{len(bloqueadas)} de {len(CATEGORIAS_PII)} categorias BLOQUEIAM a chamada; "
                "as demais saem mascaradas."
                if bloqueadas
                else "Todas as categorias saem MASCARADAS — nenhuma chamada é bloqueada."
            ),
            "itens": [
                {
                    "chave": categoria,
                    "rotulo": _ROTULO_PII.get(categoria, categoria),
                    "valor": acoes.get(categoria, "—"),
                    "efeito": _efeito_da_categoria(categoria, acoes.get(categoria)),
                }
                for categoria in CATEGORIAS_PII
            ],
        },
        {
            "parametro": "retencao",
            "titulo": "Retenção de prompt, resposta e trace",
            "resumo": (
                "Prompt e resposta são gravados no ledger (Art. 20 exige reconstruir a decisão)."
                if retencao.get("reter_prompt") and retencao.get("reter_resposta")
                else "Parte do texto NÃO é gravada — a reconstrução do Art. 20 fica "
                "incompleta para essas invocações."
            ),
            "itens": [
                {
                    "chave": "reter_prompt",
                    "valor": retencao.get("reter_prompt"),
                    "efeito": (
                        "O prompt enviado ao modelo é gravado no ledger `invocacao`."
                        if retencao.get("reter_prompt")
                        else "O prompt NÃO é gravado: `POST /auditoria/reconstruir` "
                        "devolverá a decisão sem o texto de entrada."
                    ),
                },
                {
                    "chave": "reter_resposta",
                    "valor": retencao.get("reter_resposta"),
                    "efeito": (
                        "A resposta do modelo é gravada no ledger `invocacao`."
                        if retencao.get("reter_resposta")
                        else "A resposta NÃO é gravada: a reconstrução mostra o que foi "
                        "perguntado, não o que o modelo respondeu."
                    ),
                },
                {
                    "chave": "dias_trace",
                    "valor": retencao.get("dias_trace"),
                    "efeito": (
                        f"O trace de diagnóstico expira em {retencao.get('dias_trace')} dia(s). "
                        "O PRAZO DO LEDGER não é definido aqui: é `retencao_dias` na política "
                        "do M12, que é quem o purge (§10.4) lê."
                    ),
                },
            ],
        },
        {
            "parametro": "decisao_automatizada",
            "titulo": "Decisão automatizada (LGPD Art. 20)",
            "resumo": (
                "Nenhuma ação é aplicada pela IA sozinha: a IA PROPÕE e um humano aplica."
                if not automatizaveis
                else f"{len(automatizaveis)} de {len(ACOES_VIA_AI)} ações são aplicadas pela "
                "IA SEM revisão humana."
            ),
            "itens": [
                {
                    "chave": acao,
                    "valor": acao in automatizaveis,
                    "efeito": (
                        "A IA APLICA sozinha — não há revisão humana antes do efeito."
                        if acao in automatizaveis
                        else "A IA PROPÕE; um humano aplica."
                    ),
                }
                for acao in ACOES_VIA_AI
            ],
        },
        {
            "parametro": "modelos_permitidos",
            "titulo": "Modelos permitidos por agente",
            "resumo": (
                f"{sum(1 for perfis in modelos.values() if not perfis)} agente(s) sem nenhum "
                f"perfil autorizado (não chamam modelo); {len(modelos)} agentes declarados."
            ),
            "itens": [
                {
                    "chave": agente,
                    "valor": list(perfis),
                    "efeito": (
                        f"Chamada de {agente} com perfil fora de {', '.join(perfis)} é RECUSADA."
                        if perfis
                        else f"{agente} não pode chamar modelo nenhum."
                    ),
                }
                for agente, perfis in sorted(modelos.items())
            ],
        },
        {
            "parametro": "teto_tokens",
            "titulo": "Teto de consumo de tokens (por tenant, por dia UTC)",
            "resumo": (
                f"Chamadas de IA deste tenant PARAM (429) quando o gasto MEDIDO do dia "
                f"atinge {teto_diario} tokens; o orçamento reinicia à meia-noite UTC."
                if teto_diario is not None
                else "Sem teto: nenhum limite de consumo — o comportamento de sempre."
            ),
            "itens": [
                {
                    "chave": "tokens_por_dia",
                    "valor": teto_diario,
                    "efeito": (
                        (
                            f"A chamada que encontrar o gasto do dia >= {teto_diario} é "
                            "recusada ANTES de custar (429); a que começou abaixo do teto "
                            "completa. LIMITE DECLARADO: o teto governa o gasto MEDIDO — "
                            "linha de ledger sem usage do provedor conta 0, então tenant "
                            "atrás de proxy que suprime usage tem teto inaplicável na "
                            "prática."
                        )
                        if teto_diario is not None
                        else (
                            "Nenhuma chamada é recusada por consumo. Para ligar, publique "
                            "um inteiro positivo — o enforcement mora no mesmo portão dos "
                            "modelos (autorizar_modelo), coberto pelo vigia de CI."
                        )
                    ),
                }
            ],
        },
    ]


def _apertos(default: dict[str, Any], novo: dict[str, Any]) -> dict[str, Any]:
    """O que a versão publicada muda em relação ao conservador de fábrica.

    Vai para o payload do evento de auditoria. Só três eixos, os que respondem a
    "isto ficou mais frouxo?": categorias que deixaram de bloquear não existem (o
    default não bloqueia nada), então o sinal relevante é o INVERSO — quem passou a
    ser automatizado sem humano e quem deixou de ser retido.
    """
    acoes_novo = dict((novo.get("dados_llm") or {}).get("acoes") or {})
    ret_default = dict(default.get("retencao") or {})
    ret_novo = dict(novo.get("retencao") or {})
    return {
        "bloqueiam_llm": sorted(c for c, a in acoes_novo.items() if a == "bloquear"),
        "automatizadas_sem_humano": sorted(
            (novo.get("decisao_automatizada") or {}).get("pode_aplicar_sozinho") or []
        ),
        "retencao_afrouxada": sorted(
            campo
            for campo in ("reter_prompt", "reter_resposta")
            if ret_default.get(campo) and not ret_novo.get(campo)
        ),
    }
