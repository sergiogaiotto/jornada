"""Unit do sanitizador único de PII (§10.2 — emenda C02).

Duas obrigações simétricas, e a segunda é tão dura quanto a primeira:
1. **não vazar**: toda forma de CPF/CNPJ/e-mail/telefone/cartão vira marcador;
2. **não estragar**: número de negócio (verba, audiência, data, ID curto) passa
   INTACTO — falso positivo aqui apaga informação do briefing e é bug.
"""

import pytest

from domain.privacidade import contem_pii, mascarar_pii


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        # CPF com e sem pontuação (DV válido e DV inválido — ambos são forma de CPF)
        ("CPF 529.982.247-25", "CPF [CPF]"),
        ("CPF 52998224725", "CPF [CPF]"),
        ("CPF 111.222.333-44", "CPF [CPF]"),
        # CNPJ com e sem pontuação
        ("CNPJ 12.345.678/0001-95", "CNPJ [CNPJ]"),
        ("CNPJ 12345678000195", "CNPJ [CNPJ]"),
        # e-mail
        ("fale com joao.silva+promo@empresa.com.br hoje", "fale com [EMAIL] hoje"),
        # telefone: DDI, DDD entre parênteses, 9º dígito, fixo, tudo cru
        ("tel +55 11 98765-4321", "tel [TELEFONE]"),
        ("tel +5511987654321", "tel [TELEFONE]"),
        ("tel (11) 98765-4321", "tel [TELEFONE]"),
        ("tel (11) 3456 7890", "tel [TELEFONE]"),
        ("tel 11987654321", "tel [TELEFONE]"),
        ("tel 11 98765-4321", "tel [TELEFONE]"),
        ("tel 98765-4321", "tel [TELEFONE]"),
        ("tel 3456-7890", "tel [TELEFONE]"),
        ("tel 1134567890", "tel [TELEFONE]"),
        # cartão agrupado e cru (Luhn confirma)
        ("cartao 4111 1111 1111 1111", "cartao [CARTAO]"),
        ("cartao 4111111111111111", "cartao [CARTAO]"),
    ],
)
def test_mascara_toda_forma_de_pii(entrada: str, esperado: str) -> None:
    assert mascarar_pii(entrada) == esperado
    assert contem_pii(entrada)


@pytest.mark.parametrize(
    "texto",
    [
        # verba e audiência: os números que o UAT usa de verdade
        "verba de R$ 480.000 para 847.312 clientes",
        "1.234.567 envios com ROAS 18,5x",
        # datas em vários formatos NÃO são telefone
        "janela de 01/10 a 15/10 de 2026",
        "publicado em 2026-08-06 às 14:30",
        "campanha 06/08/2026",
        # sequências de anos não são cartão (Luhn reprova) e IDs curtos passam
        "orçamento 2024 2025 2026 2027 comparado",
        "12345678 impressões no período",
        # códigos da própria plataforma (§11.4) — o hífen 4-4 NÃO faz deles telefone
        "OS-2026-0457 aprovada",
        "compare OS-2025-0311 com OS-2026-0457",
        "lift de 24,1% e CPM 0,0018",
    ],
)
def test_nao_mascara_numero_de_negocio(texto: str) -> None:
    """Falso positivo é bug: mascarar verba/audiência/data destrói o briefing."""
    assert mascarar_pii(texto) == texto
    assert not contem_pii(texto)


def test_preserva_o_texto_em_volta_e_e_deterministico() -> None:
    entrada = (
        "Cliente joao@x.com.br, CPF 529.982.247-25, fone (11) 98765-4321 — "
        "verba R$ 480.000 na janela 01/10 a 15/10."
    )
    saida = mascarar_pii(entrada)
    assert saida == (
        "Cliente [EMAIL], CPF [CPF], fone [TELEFONE] — verba R$ 480.000 na janela 01/10 a 15/10."
    )
    assert mascarar_pii(saida) == saida  # idempotente: marcador não vira outro marcador
    assert mascarar_pii(entrada) == saida  # determinístico


def test_numero_4_4_solto_e_tratado_como_telefone() -> None:
    """Fronteira consciente: `2026-0457` SOLTO é indistinguível de um fixo brasileiro
    (`3456-7890`), então o desempate é a favor da privacidade — mascara. O código real
    da plataforma vem sempre prefixado (`OS-2026-0457`) e por isso fica intacto."""
    assert mascarar_pii("snapshot 2026-0457") == "snapshot [TELEFONE]"
    assert mascarar_pii("snapshot OS-2026-0457") == "snapshot OS-2026-0457"


def test_texto_vazio_e_sem_pii() -> None:
    assert mascarar_pii("") == ""
    assert not contem_pii("")
    assert mascarar_pii("Quero aumentar upgrade 5G") == "Quero aumentar upgrade 5G"
