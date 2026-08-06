"""Sanitizador ÚNICO de PII (§10.2 — emenda C02).

Regra do contrato: **PII nunca entra em prompt de LLM, log ou ledger `invocacao`**.
O UAT #3 adversarial (docs/UAT3-VPS-2026-08-06-adversarial.md) provou o vazamento na
VPS: CPF/telefone/e-mail digitados pelo solicitante chegavam EM CLARO ao prompt e
eram gravados em claro no ledger. Este módulo é o único ponto de verdade do
mascaramento — os serviços o aplicam na FRONTEIRA de entrada do texto livre, e o
texto mascarado é o que segue para prompt, RAG e ledger (nenhum caminho recebe o
original).

Propriedades exigidas (testadas por comportamento — robustez é lei):
- **determinístico e puro**: mesma entrada ⇒ mesma saída, sem I/O, sem estado;
- **preserva o resto do texto**: substitui só o trecho sensível por um marcador
  estável (`[CPF]`, `[EMAIL]`, `[TELEFONE]`...), nunca reescreve o entorno — o
  agente continua entendendo o pedido do usuário;
- **falso positivo é bug**: números de negócio (`480.000` de verba, `847.312` de
  audiência, datas `2026-08-06`, IDs curtos) NÃO são PII. Onde o formato é
  ambíguo o desempate é por CÓDIGO verificável — dígitos verificadores de
  CPF/CNPJ e Luhn de cartão — nunca por chute.

Cobertura: CPF, CNPJ, e-mail, telefone/MSISDN brasileiro (com e sem DDI +55, com e
sem DDD, com e sem 9º dígito) e cartão — cada um com e sem pontuação.
"""

import re

MARCADOR_CPF = "[CPF]"
MARCADOR_CNPJ = "[CNPJ]"
MARCADOR_EMAIL = "[EMAIL]"
MARCADOR_TELEFONE = "[TELEFONE]"
MARCADOR_CARTAO = "[CARTAO]"
MARCADOR_DOCUMENTO = "[DOCUMENTO]"  # identificador longo não classificável

# ------------------------------------------------------------------ padrões
# `(?<!\d)`/`(?!\d)` evitam casar PEDAÇO de um número maior (um run de 20 dígitos
# não pode ser lido como "um cartão de 19 + sobra").
_EMAIL = r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"
_CNPJ_FMT = r"(?<!\d)\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}(?!\d)"
_CPF_FMT = r"(?<!\d)\d{3}\.\d{3}\.\d{3}-\d{2}(?!\d)"
# Cartão em grupos de 4 (o agrupamento é o sinal); confirmado por Luhn no dispatch
# — sem isso "2024 2025 2026 2027" viraria cartão (falso positivo inaceitável).
_CARTAO_FMT = r"(?<!\d)\d{4}[ .\-]\d{4}[ .\-]\d{4}[ .\-]\d{3,4}(?!\d)"
# Telefone com DDI explícito: +55 (11) 98765-4321 / +5511987654321
_TEL_DDI = r"(?<!\d)\+\s?55[ .\-]?\(?\d{2}\)?[ .\-]?9?\d{4}[ .\-]?\d{4}(?!\d)"
# Telefone com DDD entre parênteses: (11) 98765 4321
_TEL_PAREN = r"(?<!\d)\(\d{2}\)[ .\-]?9?\d{4}[ .\-]?\d{4}(?!\d)"
# Telefone com hífen no local (4-4): 98765-4321 / 11 98765-4321 / 3456-7890.
# O hífen entre dois grupos de 4 é o que separa telefone de número de negócio —
# datas ("2026-08-06") não casam porque exigem \d{4}-\d{4}. As bordas `[-\w]`
# protegem CÓDIGOS da plataforma: em `OS-2026-0457` o "2026-0457" vem colado a um
# hífen/letra, logo NÃO é telefone (falso positivo pego no unit do C02).
_TEL_HIFEN = r"(?<![-\w])(?:(?:\+?55[ .\-]?)?(?:\(\d{2}\)|\d{2})[ .\-]?)?9?\d{4}-\d{4}(?![-\w])"
# Run de dígitos sem pontuação: classificado por comprimento + verificadores.
_DIGITOS = r"(?<!\d)\d{8,}(?!\d)"

_PADRAO = re.compile(
    "|".join(
        (
            f"(?P<email>{_EMAIL})",
            f"(?P<cnpj_fmt>{_CNPJ_FMT})",
            f"(?P<cpf_fmt>{_CPF_FMT})",
            f"(?P<cartao_fmt>{_CARTAO_FMT})",
            f"(?P<tel_ddi>{_TEL_DDI})",
            f"(?P<tel_paren>{_TEL_PAREN})",
            f"(?P<tel_hifen>{_TEL_HIFEN})",
            f"(?P<digitos>{_DIGITOS})",
        )
    )
)

# DDD brasileiro: 11-19, 21-29, ..., 91-99 (nenhum termina em 0)
_DDD = re.compile(r"(?:1[1-9]|[2-9][1-9])$")
_MOVEL_COM_DDD = re.compile(r"(?:1[1-9]|[2-9][1-9])9\d{8}$")  # DDD + 9º dígito + 8


def _so_digitos(texto: str) -> str:
    return "".join(c for c in texto if c.isdigit())


def _cpf_valido(digitos: str) -> bool:
    """Dígitos verificadores do CPF (mod 11) — desempata CPF × celular (ambos 11)."""
    if len(digitos) != 11 or len(set(digitos)) == 1:
        return False
    for tamanho in (9, 10):
        soma = sum(int(digitos[i]) * (tamanho + 1 - i) for i in range(tamanho))
        esperado = (soma * 10 % 11) % 10
        if esperado != int(digitos[tamanho]):
            return False
    return True


_PESOS_CNPJ = (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)


def _cnpj_valido(digitos: str) -> bool:
    """Dígitos verificadores do CNPJ (mod 11)."""
    if len(digitos) != 14 or len(set(digitos)) == 1:
        return False
    for tamanho in (12, 13):
        pesos = _PESOS_CNPJ[13 - tamanho :]
        soma = sum(int(digitos[i]) * pesos[i] for i in range(tamanho))
        resto = soma % 11
        esperado = 0 if resto < 2 else 11 - resto
        if esperado != int(digitos[tamanho]):
            return False
    return True


def _luhn_valido(digitos: str) -> bool:
    """Luhn (mod 10) — confirma cartão antes de mascarar sequências agrupadas."""
    soma = 0
    for indice, char in enumerate(reversed(digitos)):
        valor = int(char)
        if indice % 2 == 1:
            valor *= 2
            if valor > 9:
                valor -= 9
        soma += valor
    return soma % 10 == 0


def _classificar_run(digitos: str) -> str | None:
    """Marcador para um run de dígitos SEM pontuação; None = não é PII (mantém o
    texto intacto). Ordem: verificadores primeiro, formato depois."""
    tamanho = len(digitos)
    if tamanho == 11:  # CPF e celular com DDD têm o MESMO tamanho: DV desempata
        if _cpf_valido(digitos):
            return MARCADOR_CPF
        if _MOVEL_COM_DDD.match(digitos):
            return MARCADOR_TELEFONE
        return MARCADOR_CPF  # 11 dígitos é forma de CPF: mascara mesmo com DV ruim
    if tamanho == 14:
        if _cnpj_valido(digitos):
            return MARCADOR_CNPJ
        return MARCADOR_CARTAO if _luhn_valido(digitos) else MARCADOR_DOCUMENTO
    if tamanho == 10 and _DDD.match(digitos[:2]):  # fixo com DDD
        return MARCADOR_TELEFONE
    if tamanho == 9 and digitos[0] == "9":  # celular sem DDD (9º dígito)
        return MARCADOR_TELEFONE
    if tamanho in (12, 13) and digitos.startswith("55") and _DDD.match(digitos[2:4]):
        return MARCADOR_TELEFONE  # MSISDN com DDI: 55 + DDD + fixo/celular
    if 13 <= tamanho <= 19 and _luhn_valido(digitos):
        return MARCADOR_CARTAO
    if tamanho >= 11:
        return MARCADOR_DOCUMENTO  # identificador longo: nunca em claro (§10.2)
    # 8 dígitos crus são ambíguos demais (datas `20260806`, contagens, IDs de
    # sistema): mascarar aqui seria falso positivo — telefone de 8 dígitos só é
    # reconhecido quando vem formatado (`3456-7890`).
    return None


def _substituir(casamento: re.Match[str]) -> str:
    grupo = casamento.lastgroup
    original = casamento.group(0)
    if grupo == "email":
        return MARCADOR_EMAIL
    if grupo == "cnpj_fmt":
        return MARCADOR_CNPJ
    if grupo == "cpf_fmt":
        return MARCADOR_CPF
    if grupo == "cartao_fmt":
        # Sem Luhn não é cartão: preserva o texto (verba "2024 2025 2026 2027").
        return MARCADOR_CARTAO if _luhn_valido(_so_digitos(original)) else original
    if grupo in ("tel_ddi", "tel_paren", "tel_hifen"):
        return MARCADOR_TELEFONE
    marcador = _classificar_run(original)
    return marcador if marcador is not None else original


def mascarar_pii(texto: str) -> str:
    """Substitui PII por marcadores estáveis, PRESERVANDO o resto do texto (§10.2).

    Único ponto de mascaramento da plataforma: aplicado ANTES de montar qualquer
    prompt de LLM/embedding e ANTES de gravar `input` no ledger `invocacao`.
    """
    if not texto:
        return texto
    return _PADRAO.sub(_substituir, texto)


def contem_pii(texto: str) -> bool:
    """True se `mascarar_pii` alteraria o texto — detecção e mascaramento usam
    exatamente a MESMA regra (não podem divergir)."""
    return bool(texto) and mascarar_pii(texto) != texto
