"""Unit do adapter SfmcHttp (SFMCPort — §2.1) contra o mock-sfmc IN-PROCESS.

O transport ASGI injetado (`httpx.ASGITransport(app=mock)`) faz o httpx do adapter
entregar as requisições diretamente ao app FastAPI do mock — nenhuma porta/servidor
http real em teste (§1.3.5). SOAP sai como template XML (zeep não é usado — §3.3
reserva-o ao adapter contra SFMC real).
"""

import httpx
import pytest
from fastapi.testclient import TestClient

from adapters.sfmc.cliente import SfmcHttp
from app.config import Settings
from application.ports.sfmc import SfmcRateLimit, SfmcRecusado
from tests.unit.util_mock_sfmc import carregar_mock_sfmc

modulo = carregar_mock_sfmc()


@pytest.fixture()
def mock_sfmc():  # type: ignore[no-untyped-def]
    return modulo.create_app()


@pytest.fixture()
def adapter(mock_sfmc) -> SfmcHttp:  # type: ignore[no-untyped-def]
    settings = Settings(
        _env_file=None,
        sfmc_auth_url="http://mock-sfmc/v2/token",
        sfmc_rest_url="http://mock-sfmc/rest",
        sfmc_soap_url="http://mock-sfmc/soap",
    )
    return SfmcHttp(settings, transport=httpx.ASGITransport(app=mock_sfmc))


async def test_event_definition_roundtrip(adapter: SfmcHttp) -> None:
    criado = await adapter.criar_event_definition(
        {"name": "Entrada OS-457", "eventDefinitionKey": "jrn-abc123def456-n1"}
    )
    assert criado["id"].startswith("ed-")

    obtido = await adapter.obter_event_definition("jrn-abc123def456-n1")
    assert obtido is not None and obtido["name"] == "Entrada OS-457"

    assert await adapter.destruir_event_definition("jrn-abc123def456-n1") is True
    assert await adapter.obter_event_definition("jrn-abc123def456-n1") is None


async def test_payload_invalido_vira_sfmc_recusado(adapter: SfmcHttp) -> None:
    with pytest.raises(SfmcRecusado, match="eventDefinitionKey"):
        await adapter.criar_event_definition({"name": "Sem chave"})


async def test_interaction_e_asset_roundtrip(adapter: SfmcHttp) -> None:
    jornada = await adapter.criar_interaction(
        {
            "key": "jrn-abc123def456",
            "name": "Upgrade 5G",
            "activities": [{"key": "a1", "type": "EMAILV2"}],
        }
    )
    assert jornada["status"] == "Draft"
    assert (await adapter.obter_interaction("jrn-abc123def456")) is not None

    await adapter.criar_asset(
        {"name": "KV e-mail", "assetType": {"id": 208}, "customerKey": "jrn-abc123def456-n3"}
    )
    asset = await adapter.obter_asset("jrn-abc123def456-n3")
    assert asset is not None and asset["name"] == "KV e-mail"
    assert await adapter.destruir_asset("jrn-abc123def456-n3") is True
    assert await adapter.obter_asset("jrn-abc123def456-n3") is None


async def test_data_extension_soap_por_template_xml(adapter: SfmcHttp) -> None:
    criada = await adapter.criar_data_extension(
        {
            "customerKey": "DE_457_entrada",
            "name": "DE Entrada OS-457",
            "fields": [{"name": "SubscriberKey", "fieldType": "Text"}],
        }
    )
    assert criada["objectId"] is not None and criada["objectId"].startswith("de-")

    obtida = await adapter.obter_data_extension("DE_457_entrada")
    assert obtida is not None
    assert obtida["name"] == "DE Entrada OS-457"
    assert obtida["fields"] == [{"name": "SubscriberKey", "fieldType": "Text"}]

    with pytest.raises(SfmcRecusado, match="Field"):
        await adapter.criar_data_extension({"customerKey": "DE_x", "name": "X", "fields": []})

    assert await adapter.destruir_data_extension("DE_457_entrada") is True
    assert await adapter.obter_data_extension("DE_457_entrada") is None


async def test_automation_soap_roundtrip(adapter: SfmcHttp) -> None:
    await adapter.criar_automation({"customerKey": "am_extract", "name": "Extract diário"})
    automacao = await adapter.obter_automation("am_extract")
    assert automacao is not None and automacao["name"] == "Extract diário"
    assert await adapter.destruir_automation("am_extract") is True


async def test_chaos_rate_limit_vira_excecao_tipada(mock_sfmc, adapter: SfmcHttp) -> None:  # type: ignore[no-untyped-def]
    """429 do chaos (§11.1) → SfmcRateLimit com retry_after (insumo do apply §5.4.2)."""
    TestClient(mock_sfmc).post("/chaos/rate-limit")
    with pytest.raises(SfmcRateLimit) as excecao:
        await adapter.obter_event_definition("qualquer")
    assert excecao.value.retry_after == 1.0

    with pytest.raises(SfmcRateLimit):
        await adapter.obter_data_extension("qualquer")  # SOAP também respeita o chaos


async def test_chaos_drift_visivel_pelo_adapter(mock_sfmc, adapter: SfmcHttp) -> None:  # type: ignore[no-untyped-def]
    """Drift injetado no mock aparece na leitura — insumo do drift check M9 (§5.4.5)."""
    await adapter.criar_event_definition({"name": "Entrada", "eventDefinitionKey": "k1"})
    TestClient(mock_sfmc).post("/chaos/drift")
    lido = await adapter.obter_event_definition("k1")
    assert lido is not None and lido["name"] == f"Entrada{modulo.MARCA_DRIFT}"
