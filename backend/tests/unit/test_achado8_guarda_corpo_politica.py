"""Guarda-corpo de CI do achado 8 (docs/UAT5-2026-08-06-cacada.md): NENHUM serviço
pode ler a política de uma CONSTANTE compilada.

Por que um teste de grep e não uma revisão de código: o achado 8 não foi um bug, foi
uma REGRESSÃO SILENCIOSA de arquitetura. Seis serviços faziam
`from domain.governanca.politicas import POLITICA_PUBLICADA` e a tela de Políticas
(M12) publicava versão no banco sem governar nada — publicar `holdout_min=40` e o PUT
de holdout 15 respondia 200. Nada quebrava: os testes passavam, a tela funcionava, o
ledger registrava. É o tipo de achado que só volta a aparecer numa auditoria, e por
isso precisa de um vigia que roda em toda pipeline.

A regra: a política vigente entra nos serviços por INJEÇÃO (`PublicacoesPort`, que lê
`policy_versao` §4.1 e cai no seed §11.4 quando o tenant ainda não publicou). O seed
`POLITICA_SEED` é semente e fallback — quem legitimamente o consome são as SEEDS
(`adapters/*_seeds.py`) e o ADAPTER de publicações, ambos fora de
`application/services/`.

**Segundo vigia, para o furo que de fato aconteceu.** O achado 8 não chegou só por
import de constante: `api/v1/audiencia.py` montava `PublicacoesLocais()` na mão — um
adapter legítimo, injetado do jeito certo, que simplesmente ignora o banco. O serviço
estava correto; o WIRING é que devolvia a constante. Vigiar só o import de
`POLITICA_*` deixaria essa porta aberta, então as rotas têm que passar pela fábrica
única `publicacoes_vigentes(repositorio)`.
"""

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
SERVICOS = BACKEND / "application" / "services"
ROTAS = BACKEND / "api" / "v1"

# `from domain.governanca.politicas import ... POLITICA_ALGO` (em uma linha ou entre
# parênteses) e o acesso qualificado `politicas.POLITICA_ALGO`. Funções puras do mesmo
# módulo (`faixa_alcada`, `validar_conteudo`) seguem liberadas: são REGRAS, não FONTE.
IMPORT_DO_SEED = re.compile(
    r"from\s+domain\.governanca\.politicas\s+import\s*\(?[^)\n]*POLITICA_\w+"
    r"|politicas\.POLITICA_\w+"
)

# CONSTRUÇÃO na mão de um adapter de publicações dentro das rotas (o `(` é o que separa
# a chamada da menção em comentário/docstring, que continua liberada).
ADAPTER_NA_MAO = re.compile(r"\bPublicacoes(?:Locais|Atelie)\s*\(")


def test_achado8_nenhum_servico_importa_a_politica_do_dominio() -> None:
    """Falha listando arquivo e linha — a mensagem tem que ensinar o caminho certo."""
    infratores: list[str] = []
    for arquivo in sorted(SERVICOS.glob("*.py")):
        for numero, linha in enumerate(arquivo.read_text(encoding="utf-8").splitlines(), 1):
            if IMPORT_DO_SEED.search(linha):
                infratores.append(f"{arquivo.name}:{numero}: {linha.strip()}")
    assert not infratores, (
        "Serviço lendo política de constante compilada — é o achado 8 do UAT #5 de volta:\n"
        + "\n".join(infratores)
        + "\n\nUse o `PublicacoesPort` injetado: `politica_vigente(self._publicacoes, "
        "tenant_id)` devolve o `conteudo` da política PUBLICADA do tenant e cai no seed "
        "§11.4 sozinho quando não há nenhuma. Constante que governa runtime faz da tela "
        "de Políticas teatro auditável."
    )


def test_achado8_nenhuma_rota_monta_o_adapter_de_publicacoes_na_mao() -> None:
    """O furo literal do achado 8: `api/v1/audiencia.py` construía `PublicacoesLocais()`.

    Nada quebrava — o serviço recebia um `PublicacoesPort` de verdade, injetado como
    manda o §2.1. Só que aquele adapter lê a CONSTANTE, então o holdout continuava
    vindo do seed enquanto `api/v1/validacao.py`, montando `PublicacoesAtelie`, lia o
    banco: duas fontes da política na mesma aplicação, escolhidas por router. A fábrica
    única é o que impede a divergência voltar por descuido de wiring.
    """
    infratores: list[str] = []
    for arquivo in sorted(ROTAS.glob("*.py")):
        for numero, linha in enumerate(arquivo.read_text(encoding="utf-8").splitlines(), 1):
            if ADAPTER_NA_MAO.search(linha):
                infratores.append(f"{arquivo.name}:{numero}: {linha.strip()}")
    assert not infratores, (
        "Rota montando adapter de publicações na mão — é o achado 8 do UAT #5 de volta:\n"
        + "\n".join(infratores)
        + "\n\nUse `publicacoes_vigentes(repositorio)` de `adapters/publicacoes`: uma "
        "fonte só de política para TODAS as rotas. `PublicacoesLocais` lê a constante "
        "compilada e existe apenas como fallback DENTRO da fábrica."
    )


def test_achado8_o_vigia_enxerga_a_infracao() -> None:
    """Inversão do próprio guarda-corpo: um teste de grep que não pega nada é decoração.

    Prova que o padrão casa a linha EXATA que o achado 8 descreve (a que estava nos seis
    serviços) e, de quebra, que não confunde com o import legítimo das regras puras.
    """
    assert IMPORT_DO_SEED.search(
        "from domain.governanca.politicas import POLITICA_PUBLICADA, faixa_alcada"
    )
    assert IMPORT_DO_SEED.search("from domain.governanca.politicas import POLITICA_SEED")
    assert IMPORT_DO_SEED.search("    politica = politicas.POLITICA_SEED['conteudo']")
    assert not IMPORT_DO_SEED.search("from domain.governanca.politicas import faixa_alcada")
    assert not IMPORT_DO_SEED.search("from application.ports.publicacoes import politica_vigente")

    # e o vigia do wiring: pega a CHAMADA (a linha que audiencia.py tinha) sem se
    # confundir com a menção em comentário/import, que é legítima.
    assert ADAPTER_NA_MAO.search("_publicacoes = PublicacoesLocais()")
    assert ADAPTER_NA_MAO.search("    publicacoes = PublicacoesAtelie(repo, fallback=disco)")
    assert not ADAPTER_NA_MAO.search("# achado 8: era `PublicacoesLocais` — lia a constante")
    assert not ADAPTER_NA_MAO.search("from adapters.publicacoes import publicacoes_vigentes")
