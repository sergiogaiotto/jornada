"""Unit do sanitizador ESTRUTURAL (§10.2 — `domain/privacidade/sanitizar.py`).

O `mascarar_pii` já tem o seu unit (test_mascarar.py). Aqui o que está sob prova é a
propagação por ÁRVORE, que é o que a plataforma realmente entrega a destinos externos:
`conteudo` do pedido, `briefing` da OS, `payload` de evento (§2.3) e `metadados`/`spans`
do trace Langfuse (§10.8). As propriedades que importam:

- mascara em QUALQUER profundidade (o vazamento mora no aninhado, não na raiz);
- **preserva forma e TIPO**: verba `480000.0` continua float; `os_id` continua UUID —
  converter tipos aqui quebraria o contrato §4.1 de quem consome o payload;
- **não mexe em CHAVE**: chave é nome de campo do §4.1; mascarar `"objetivo"` quebraria
  a completude, que é calculada por código;
- não muta a entrada;
- não estoura em estrutura circular (telemetria nunca pode derrubar a aplicação §10.8).
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from domain.privacidade import contem_pii_estrutura, mascarar_estrutura

CPF = "529.982.247-25"
EMAIL = "joao.silva@clientereal.com.br"
TELEFONE = "(11) 98765-4321"


def test_mascara_em_qualquer_profundidade_da_arvore() -> None:
    """PII escondida em dict dentro de lista dentro de dict — o caso do `briefing`
    (`{campo: {valor, inferido, evidencias:[...]}}`), que é onde ela realmente mora."""
    entrada: dict[str, Any] = {
        "objetivo": {
            "valor": f"Ligar para {TELEFONE}",
            "inferido": True,
            "evidencias": [f"solicitante informou {EMAIL}", "verba de R$ 480.000"],
        }
    }
    saida = mascarar_estrutura(entrada)
    assert saida["objetivo"]["valor"] == "Ligar para [TELEFONE]"
    assert saida["objetivo"]["evidencias"][0] == "solicitante informou [EMAIL]"
    assert saida["objetivo"]["evidencias"][1] == "verba de R$ 480.000"  # negócio, não PII
    assert saida["objetivo"]["inferido"] is True


def test_preserva_forma_e_tipo_dos_valores_nao_textuais() -> None:
    """Números de negócio, UUID e datetime atravessam INTACTOS e com o tipo original —
    o payload de evento e o `briefing` §4.1 dependem disso."""
    os_id = uuid.uuid4()
    momento = datetime(2026, 8, 6, tzinfo=UTC)
    entrada: dict[str, Any] = {
        "verba": 480_000.0,
        "audiencia": 847_312,
        "ativo": True,
        "os_id": os_id,
        "quando": momento,
        "nada": None,
        "canais": ("email", "sms"),
        "contato": CPF,
    }
    saida = mascarar_estrutura(entrada)
    assert saida["verba"] == 480_000.0 and isinstance(saida["verba"], float)
    assert saida["audiencia"] == 847_312 and isinstance(saida["audiencia"], int)
    assert saida["ativo"] is True
    assert saida["os_id"] is os_id and saida["quando"] is momento
    assert saida["nada"] is None
    assert saida["canais"] == ("email", "sms") and isinstance(saida["canais"], tuple)
    assert saida["contato"] == "[CPF]"


def test_nao_mascara_chaves_nem_muta_a_entrada() -> None:
    """Chave é NOME DE CAMPO do contrato (§4.1), não dado do titular: mascarar a chave
    quebraria completude/validação por código. E o original não pode ser mutado."""
    entrada = {"objetivo": f"CPF {CPF}", CPF: "chave esquisita mas é chave"}
    saida = mascarar_estrutura(entrada)
    assert set(saida) == {"objetivo", CPF}, "chave foi reescrita"
    assert entrada["objetivo"] == f"CPF {CPF}", "a entrada foi MUTADA"
    assert saida["objetivo"] == "CPF [CPF]"


def test_estrutura_circular_nao_estoura() -> None:
    """§10.8: telemetria/eventos nunca podem derrubar a aplicação. Ciclo não deveria
    existir em payload JSON, mas recursão sem freio vira RecursionError."""
    circular: dict[str, Any] = {"contato": EMAIL}
    circular["eu"] = circular
    saida = mascarar_estrutura(circular)  # não estoura
    assert saida["contato"] == "[EMAIL]"


def test_deteccao_e_mascaramento_usam_a_mesma_regra() -> None:
    """`contem_pii_estrutura` não pode divergir de `mascarar_estrutura` (mesma lição do
    C02: detectar e mascarar por regras diferentes é um vazamento esperando acontecer)."""
    assert contem_pii_estrutura({"a": [{"b": CPF}]}) is True
    assert contem_pii_estrutura({"verba": 480_000.0, "janela": "01/10 a 15/10"}) is False
