"""Cálculo determinístico de completude/faltantes do pedido (§8-M3).

REGRA DO SDD: "cálculo de completude é CÓDIGO determinístico; LLM só conversa/infere".
Nada aqui consulta LLM; o consultor jamais escreve completude/faltantes — quem recalcula
é sempre este módulo, após cada mutação do `conteudo`.
"""

from typing import Any

from domain.intake.modelos import CAMPOS_OBRIGATORIOS, Pedido


def valor_presente(valor: Any) -> bool:
    """Presença: None/str em branco/coleção vazia NÃO contam; 0/False contam (valor dado)."""
    if valor is None:
        return False
    if isinstance(valor, str):
        return valor.strip() != ""
    if isinstance(valor, (list, dict, tuple, set)):
        return len(valor) > 0
    return True


def valor_do_campo(conteudo: dict[str, Any], campo: str) -> Any:
    """Extrai o valor da entrada `{valor, inferido, ...}` (aceita valor cru por robustez)."""
    entrada = conteudo.get(campo)
    if isinstance(entrada, dict) and "valor" in entrada:
        return entrada["valor"]
    return entrada


def calcular(conteudo: dict[str, Any]) -> tuple[float, list[str]]:
    """(completude%, faltantes) sobre os CAMPOS_OBRIGATORIOS, na ordem canônica.

    completude = 100 × presentes/obrigatórios, 1 casa decimal (numeric(4,1) §4.1).
    Campos extras no conteúdo não pontuam (só os obrigatórios contam).
    """
    faltantes = [
        campo
        for campo in CAMPOS_OBRIGATORIOS
        if not valor_presente(valor_do_campo(conteudo, campo))
    ]
    presentes = len(CAMPOS_OBRIGATORIOS) - len(faltantes)
    completude = round(100.0 * presentes / len(CAMPOS_OBRIGATORIOS), 1)
    return completude, faltantes


def atualizar(pedido: Pedido) -> None:
    """Recalcula completude/faltantes e deriva o estado rascunho|completo.

    `convertido` é terminal (mudança de estado é do serviço de conversão, não daqui).
    """
    pedido.completude, pedido.faltantes = calcular(pedido.conteudo)
    if pedido.estado != "convertido":
        pedido.estado = "completo" if pedido.completude >= 100.0 else "rascunho"
