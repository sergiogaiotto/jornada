"""J02 (onda 6) — unit do teto de tokens + o guarda-corpo de FIAÇÃO.

O domínio (`teto.py`) é puro e pequeno; o que merece vigia é a fiação: o enforcement
mora em `autorizar_modelo` (onde o vigia AST do F03 já olha), mas o GASTO chega pelo
`gasto_tokens=` da fábrica `portao_ia.de` — e essa metade o vigia AST não exige. Um
serviço novo com `chat` que esqueça a fiação nasceria com teto FURADO em silêncio:
o portão receberia gasto None e pularia a checagem. O vigia de fiação abaixo fecha
exatamente esse buraco, com auto-inversão (um vigia que nunca falhou é indistinguível
de um vigia quebrado — a lição do F03).
"""

import ast
from datetime import UTC, datetime
from pathlib import Path

import pytest

from domain.ia_responsavel.erros import TetoDeTokensExcedido
from domain.ia_responsavel.teto import (
    exigir_dentro_do_teto,
    inicio_do_dia_utc,
    teto_tokens_diario,
)

SERVICOS = Path(__file__).resolve().parents[2] / "application" / "services"

# Exceções DECLARADAS do teto, por (arquivo, função) — no estilo do vigia F03. Um chat
# que não fia o teto tem de estar aqui, com o motivo por escrito, ou o vigia acusa.
# VAZIO hoje: todo chat fia o teto — 13 via `autorizar_modelo` (que aplica o teto) e o
# warn de compliance do criativo via `exigir_dentro_do_teto` explícito (ele não passa
# por autorizar_modelo por causa da exceção de PERFIL do vigia F03, mas o teto é
# ortogonal ao perfil e é aplicado à parte). O mecanismo existe para o próximo caso.
EXCECOES_TETO: dict[tuple[str, str], str] = {}


# ------------------------------------------------------------------ domínio puro
def test_J02_teto_diario_le_o_bloco_e_tolera_o_lixo() -> None:
    assert teto_tokens_diario({"teto_tokens": {"tokens_por_dia": 100}}) == 100
    assert teto_tokens_diario({"teto_tokens": {"tokens_por_dia": None}}) is None
    assert teto_tokens_diario({}) is None  # política pré-J02: sem bloco = sem teto
    assert teto_tokens_diario({"teto_tokens": "mil"}) is None  # lixo nunca vira teto
    assert teto_tokens_diario({"teto_tokens": {"tokens_por_dia": True}}) is None  # bool≠int


def test_J02_gate_on_entry_recusa_no_igual_e_deixa_passar_abaixo() -> None:
    """`>=` e não `>`: quem chega com o orçamento consumido não inicia chamada nova.
    INVERSÃO: trocar o `>=` por `>` em exigir_dentro_do_teto deixa este teste vermelho."""
    conteudo = {"teto_tokens": {"tokens_por_dia": 10}}
    exigir_dentro_do_teto(9, conteudo)  # abaixo: passa
    with pytest.raises(TetoDeTokensExcedido) as capturado:
        exigir_dentro_do_teto(10, conteudo)  # no teto: recusa (gate-on-entry)
    assert capturado.value.gasto == 10 and capturado.value.teto == 10
    exigir_dentro_do_teto(999_999, {})  # sem teto: nunca recusa


def test_J02_virada_do_orcamento_e_meia_noite_utc() -> None:
    agora = datetime(2026, 8, 7, 22, 45, 10, tzinfo=UTC)
    assert inicio_do_dia_utc(agora) == datetime(2026, 8, 7, 0, 0, 0, tzinfo=UTC)
    naive = datetime(2026, 8, 7, 3, 0, 0)  # naive = UTC por pressuposto do ledger
    assert inicio_do_dia_utc(naive) == datetime(2026, 8, 7, 0, 0, 0, tzinfo=UTC)


# ------------------------------------------------------------ vigia de FIAÇÃO (J02)
#
# Auditoria da onda 6: o vigia file-level ("o arquivo tem chat E tem gasto_do_dia?")
# dava falso negativo — bastava UM gasto_do_dia em qualquer método para o arquivo
# passar, ainda que outro chat ficasse sem teto (foi assim que criativo._avisos_
# compliance escapou). O vigia agora é por CALL SITE (AST), no molde do F03: para cada
# `.chat(` de LLM, a FUNÇÃO que o contém precisa fiar o teto — via `autorizar_modelo`
# (que aplica o teto) OU `exigir_dentro_do_teto` explícito — ou estar em EXCECOES_TETO.


def _funcoes_com_chat_sem_teto(codigo: str) -> list[str]:
    """Funções que chamam `self._llm.chat(` mas NÃO fiam o teto na mesma função."""
    arvore = ast.parse(codigo)
    infratoras: list[str] = []
    for no in ast.walk(arvore):
        if not isinstance(no, ast.FunctionDef):
            continue
        chamadas = {
            n.func.attr
            for n in ast.walk(no)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        }
        tem_chat = any(
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "chat"
            and isinstance(n.func.value, ast.Attribute)
            and n.func.value.attr == "_llm"
            for n in ast.walk(no)
        )
        if not tem_chat:
            continue
        fia_teto = "autorizar_modelo" in chamadas or "exigir_dentro_do_teto" in chamadas
        if not fia_teto:
            infratoras.append(no.name)
    return infratoras


def test_J02_todo_chat_fia_o_teto_por_call_site() -> None:
    fugitivos: list[str] = []
    for caminho in sorted(SERVICOS.glob("*.py")):
        codigo = caminho.read_text(encoding="utf-8")
        # a fábrica de() precisa RECEBER o gasto: sem gasto_do_dia no arquivo, o teto
        # nunca é carregado, então checar por-função não bastaria.
        tem_fabrica_gasto = "gasto_do_dia(" in codigo
        for funcao in _funcoes_com_chat_sem_teto(codigo):
            if (caminho.name, funcao) in EXCECOES_TETO:
                continue
            fugitivos.append(f"{caminho.name}::{funcao}")
        if "._llm.chat(" in codigo and not tem_fabrica_gasto:
            fugitivos.append(f"{caminho.name}::<sem gasto_do_dia na fábrica de()>")
    assert not fugitivos, (
        f"Chats de LLM sem fiação do teto (J02), por call site: {sorted(set(fugitivos))}. "
        "Cada função com chat precisa de `autorizar_modelo` (que aplica o teto) ou "
        "`exigir_dentro_do_teto` explícito na MESMA função, e o serviço precisa passar "
        "`gasto_tokens=portao_ia.gasto_do_dia(...)` na fábrica `de()`. Exceção só com "
        "justificativa em EXCECOES_TETO."
    )


def test_J02_excecoes_do_teto_nao_ficam_orfas() -> None:
    """Toda exceção declarada tem de corresponder a uma função REAL com chat sem teto —
    exceção órfã é doc que envelhece (mesma trava do F03)."""
    for (arquivo, funcao), _motivo in EXCECOES_TETO.items():
        codigo = (SERVICOS / arquivo).read_text(encoding="utf-8")
        assert funcao in _funcoes_com_chat_sem_teto(codigo), (
            f"Exceção órfã: {arquivo}::{funcao} não é mais uma função com chat sem "
            "autorizar_modelo — remova-a de EXCECOES_TETO."
        )


def test_J02_o_vigia_por_call_site_enxerga_a_infracao() -> None:
    """Auto-inversão: o vigia acusa a função infratora e NÃO a fiada — mesmo num
    ARQUIVO que tenha outra função com teto (o falso negativo do vigia file-level)."""
    fonte = (
        "class S:\n"
        "    def fiada(self):\n"
        "        self._portao.autorizar_modelo('a','20b')\n"
        "        self._llm.chat(m, perfil='20b')\n"
        "    def infratora(self):\n"
        "        self._llm.chat(m, perfil='20b')\n"
        "    def explicita(self):\n"
        "        self._portao.exigir_dentro_do_teto()\n"
        "        self._llm.chat(m, perfil='20b')\n"
    )
    assert _funcoes_com_chat_sem_teto(fonte) == ["infratora"]
