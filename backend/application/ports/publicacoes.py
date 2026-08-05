"""PublicacoesPort — versões publicadas ATUAIS congeladas no GO (§8-M4-A2) e
tarifário vigente do taxímetro (§8-M7-A2).

Porta = Protocol (§2.1). O GO grava em `os.frozen` (§4.1):
{agent_versions, policy_version, tarifario_id, slas}. Enquanto o Ateliê (M12) não tem
CRUD, o adapter local lê skills publicadas do disco, a política v1 do domínio e o
tarifário seed §11.4 — trocá-lo não toca serviço nem domínio.
"""

from decimal import Decimal
from typing import Any, Protocol


class PublicacoesPort(Protocol):
    def versoes_agentes(self) -> dict[str, str]:
        """{nome_do_agente: versão publicada atual} (skills §7.1)."""
        ...

    def politica_publicada(self) -> dict[str, Any]:
        """Política publicada atual — ao menos {versao, conteudo} (§4.1 policy_versao)."""
        ...

    def tarifario_id(self) -> str:
        """Identificador do tarifário vigente (frozen.tarifario_id §4.1)."""
        ...

    def tarifas_vigentes(self) -> dict[str, Decimal]:
        """{canal: custo_unit} do tarifário vigente (`tarifa_canal` §4.1; seed §11.4)."""
        ...
