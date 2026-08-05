"""SFMCPort — materialização no SFMC atrás de porta (§2.1; consumidor: compilador §5.4).

Porta = Protocol assíncrono. Recursos = tipos do `resource_registry` (§4.1):
eventDefinition/journey(interaction)/asset via REST; dataExtension/automation via SOAP.
Dicts com a forma dos payloads SFMC (camelCase) — o compilador (M9) monta os payloads a
partir do JGC; a porta só transporta. Em dev o adapter fala com o mock-sfmc (§11.1);
em teste, SEMPRE in-process via transport ASGI injetado — nunca http real (§1.3.5).
LLM proibido em qualquer implementação desta porta (§5.4).

Erros: `SfmcRateLimit` (429 — insumo do retry/backoff tenacity do apply §5.4.2),
`SfmcIndisponivel` (5xx/rede), `SfmcRecusado` (4xx/validação/StatusCode Error SOAP).
"""

from typing import Any, Protocol


class SfmcErro(RuntimeError):
    """Base dos erros da porta SFMC."""


class SfmcIndisponivel(SfmcErro):
    """SFMC fora (5xx/erro de rede) — apply decide retry/rollback (§5.4.2)."""


class SfmcRateLimit(SfmcIndisponivel):
    """429 do SFMC (ou chaos §11.1); `retry_after` em segundos quando informado."""

    def __init__(self, mensagem: str, retry_after: float | None = None) -> None:
        super().__init__(mensagem)
        self.retry_after = retry_after


class SfmcRecusado(SfmcErro):
    """Payload recusado (4xx REST ou StatusCode Error no SOAP) — não adianta repetir."""


class SFMCPort(Protocol):
    # ------------------------------------------------------------------------ REST
    async def criar_event_definition(self, definicao: dict[str, Any]) -> dict[str, Any]:
        """POST eventDefinitions; exige `name` + `eventDefinitionKey` (externalKey §5.4.1)."""
        ...

    async def obter_event_definition(self, chave: str) -> dict[str, Any] | None:
        """Por eventDefinitionKey; None se não existir (base do plan/drift)."""
        ...

    async def destruir_event_definition(self, chave: str) -> bool:
        """Rollback compensatório/destruição (§5.4.2-3); False se não existia."""
        ...

    async def criar_interaction(self, interaction: dict[str, Any]) -> dict[str, Any]:
        """POST interactions (journey spec); exige `key` + `name`."""
        ...

    async def obter_interaction(self, chave: str) -> dict[str, Any] | None: ...

    async def destruir_interaction(self, chave: str) -> bool: ...

    async def criar_asset(self, asset: dict[str, Any]) -> dict[str, Any]:
        """POST assets; exige `name` + `assetType{id|name}`; `customerKey` = externalKey."""
        ...

    async def obter_asset(self, customer_key: str) -> dict[str, Any] | None: ...

    async def destruir_asset(self, customer_key: str) -> bool: ...

    # ------------------------------------------------------------- SOAP simplificado
    async def criar_data_extension(self, de: dict[str, Any]) -> dict[str, Any]:
        """Create DataExtension: {customerKey, name, fields:[{name, fieldType}]}."""
        ...

    async def obter_data_extension(self, customer_key: str) -> dict[str, Any] | None:
        """Retrieve por CustomerKey; None se não existir."""
        ...

    async def destruir_data_extension(self, customer_key: str) -> bool:
        """Delete DataExtension (aviso destrutivo é responsabilidade do plan §5.4.3)."""
        ...

    async def criar_automation(self, automacao: dict[str, Any]) -> dict[str, Any]:
        """Create Automation: {customerKey, name}."""
        ...

    async def obter_automation(self, customer_key: str) -> dict[str, Any] | None: ...

    async def destruir_automation(self, customer_key: str) -> bool: ...
