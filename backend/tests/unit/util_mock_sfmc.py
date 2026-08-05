"""Loader do mock-sfmc para uso IN-PROCESS em teste (§1.3.5 — nunca http real).

`mocks/sfmc-server/` tem hífen no nome (layout do §2.2) e não é pacote importável —
carrega-se o módulo pelo caminho. Cada teste chama `modulo.create_app()` para nascer
com estado limpo.
"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_RAIZ = Path(__file__).resolve().parents[3]
CAMINHO_MOCK_SFMC = _RAIZ / "mocks" / "sfmc-server" / "main.py"
_NOME_MODULO = "mock_sfmc_main"


def carregar_mock_sfmc() -> ModuleType:
    if _NOME_MODULO in sys.modules:
        return sys.modules[_NOME_MODULO]
    spec = importlib.util.spec_from_file_location(_NOME_MODULO, CAMINHO_MOCK_SFMC)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[_NOME_MODULO] = modulo
    spec.loader.exec_module(modulo)
    return modulo
