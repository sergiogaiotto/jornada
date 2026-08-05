"""Unit do mock-sfmc (SDD §11.1): token, REST com validação de payload, SOAP
simplificado (DataExtension/Automation) e chaos (rate-limit, drift).

O mock é usado IN-PROCESS via TestClient (ASGI) — nenhum servidor http real (§1.3.5).
`create_app()` por teste → estado em memória sempre limpo.
"""

from xml.etree import ElementTree as ET

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.unit.util_mock_sfmc import carregar_mock_sfmc

modulo = carregar_mock_sfmc()

AUTH = {"Authorization": f"Bearer {modulo.TOKEN}"}
CREDENCIAIS = {"grant_type": "client_credentials", "client_id": "mock", "client_secret": "mock"}
NS = "http://exacttarget.com/wsdl/partnerAPI"
XSI = "http://www.w3.org/2001/XMLSchema-instance"


@pytest.fixture()
def client() -> TestClient:
    return TestClient(modulo.create_app(), raise_server_exceptions=False)


def _envelope(corpo: str, token: str = modulo.TOKEN) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">'
        f'<s:Header><fueloauth xmlns="http://exacttarget.com">{token}</fueloauth></s:Header>'
        f"<s:Body>{corpo}</s:Body></s:Envelope>"
    )


def _soap(client: TestClient, corpo: str, token: str = modulo.TOKEN) -> httpx.Response:
    return client.post(
        "/soap/Service.asmx",
        content=_envelope(corpo, token),
        headers={"Content-Type": "text/xml"},
    )


CAMPO_PADRAO = "<Field><Name>SubscriberKey</Name><FieldType>Text</FieldType></Field>"


def _criar_de(customer_key: str, nome: str, campos: str = CAMPO_PADRAO) -> str:
    return (
        f'<CreateRequest xmlns="{NS}" xmlns:xsi="{XSI}"><Objects xsi:type="DataExtension">'
        f"<CustomerKey>{customer_key}</CustomerKey><Name>{nome}</Name>"
        f"<Fields>{campos}</Fields></Objects></CreateRequest>"
    )


def _retrieve(tipo: str, customer_key: str) -> str:
    return (
        f'<RetrieveRequestMsg xmlns="{NS}" xmlns:xsi="{XSI}"><RetrieveRequest>'
        f"<ObjectType>{tipo}</ObjectType><Properties>CustomerKey</Properties>"
        f'<Filter xsi:type="SimpleFilterPart"><Property>CustomerKey</Property>'
        f"<SimpleOperator>equals</SimpleOperator><Value>{customer_key}</Value></Filter>"
        "</RetrieveRequest></RetrieveRequestMsg>"
    )


def _texto(xml: str, nome: str) -> str | None:
    raiz = ET.fromstring(xml)
    alvo = next((e for e in raiz.iter() if str(e.tag).rsplit("}", 1)[-1] == nome), None)
    return alvo.text if alvo is not None else None


# ---------------------------------------------------------------------- OAuth/auth


def test_token_valida_credenciais(client: TestClient) -> None:
    ok = client.post("/v2/token", json=CREDENCIAIS)
    assert ok.status_code == 200
    corpo = ok.json()
    assert corpo["access_token"] == modulo.TOKEN
    assert corpo["rest_instance_url"].endswith("/rest")
    errado = client.post("/v2/token", json=CREDENCIAIS | {"client_secret": "invalido"})
    assert errado.status_code == 401
    sem_grant = client.post("/v2/token", json={"client_id": "mock", "client_secret": "mock"})
    assert sem_grant.status_code == 400


def test_rest_exige_bearer(client: TestClient) -> None:
    assert client.get("/rest/interaction/v1/eventDefinitions").status_code == 401
    errado = client.get(
        "/rest/interaction/v1/eventDefinitions", headers={"Authorization": "Bearer x"}
    )
    assert errado.status_code == 401


# ------------------------------------------------------------- REST + validação


def test_event_definition_ciclo_completo(client: TestClient) -> None:
    payload = {"name": "Entrada OS-457", "eventDefinitionKey": "jrn-abc123def456-n1"}
    criado = client.post("/rest/interaction/v1/eventDefinitions", json=payload, headers=AUTH)
    assert criado.status_code == 201
    assert criado.json()["id"].startswith("ed-")

    obtido = client.get(
        "/rest/interaction/v1/eventDefinitions/key:jrn-abc123def456-n1", headers=AUTH
    )
    assert obtido.status_code == 200
    assert obtido.json()["name"] == "Entrada OS-457"

    duplicado = client.post("/rest/interaction/v1/eventDefinitions", json=payload, headers=AUTH)
    assert duplicado.status_code == 400
    assert duplicado.json()["errorcode"] == 30003

    destruido = client.delete(
        "/rest/interaction/v1/eventDefinitions/key:jrn-abc123def456-n1", headers=AUTH
    )
    assert destruido.status_code == 204
    sumiu = client.get(
        "/rest/interaction/v1/eventDefinitions/key:jrn-abc123def456-n1", headers=AUTH
    )
    assert sumiu.status_code == 404


def test_event_definition_validacao_payload(client: TestClient) -> None:
    """Validação de payload (§11.1): erro no formato SFMC {message, errorcode}, 400."""
    resposta = client.post(
        "/rest/interaction/v1/eventDefinitions", json={"name": "Sem chave"}, headers=AUTH
    )
    assert resposta.status_code == 400
    corpo = resposta.json()
    assert corpo["errorcode"] == 10006
    assert "eventDefinitionKey" in corpo["message"]


def test_interaction_valida_atividades(client: TestClient) -> None:
    invalida = {
        "key": "jrn-abc123def456",
        "name": "Upgrade 5G",
        "activities": [{"key": "a1"}],  # sem type
    }
    resposta = client.post("/rest/interaction/v1/interactions", json=invalida, headers=AUTH)
    assert resposta.status_code == 400
    assert resposta.json()["errorcode"] == 10006

    valida = {
        "key": "jrn-abc123def456",
        "name": "Upgrade 5G",
        "activities": [{"key": "a1", "type": "EMAILV2"}],
    }
    criada = client.post("/rest/interaction/v1/interactions", json=valida, headers=AUTH)
    assert criada.status_code == 201
    assert criada.json()["status"] == "Draft"


def test_asset_valida_asset_type_e_filtra_por_customer_key(client: TestClient) -> None:
    sem_tipo = client.post(
        "/rest/asset/v1/content/assets",
        json={"name": "E-mail KV", "assetType": {}},
        headers=AUTH,
    )
    assert sem_tipo.status_code == 400

    criado = client.post(
        "/rest/asset/v1/content/assets",
        json={
            "name": "E-mail KV",
            "assetType": {"id": 208, "name": "htmlemail"},
            "customerKey": "jrn-abc123def456-n3",
        },
        headers=AUTH,
    )
    assert criado.status_code == 201

    filtrado = client.get(
        "/rest/asset/v1/content/assets",
        params={"customerKey": "jrn-abc123def456-n3"},
        headers=AUTH,
    )
    assert filtrado.json()["count"] == 1
    vazio = client.get(
        "/rest/asset/v1/content/assets", params={"customerKey": "nao-existe"}, headers=AUTH
    )
    assert vazio.json()["count"] == 0


# ---------------------------------------------------------------- SOAP simplificado


def test_soap_data_extension_create_retrieve_delete(client: TestClient) -> None:
    criada = _soap(client, _criar_de("DE_457_entrada", "DE Entrada OS-457"))
    assert criada.status_code == 200
    assert _texto(criada.text, "StatusCode") == "OK"
    assert (_texto(criada.text, "NewObjectID") or "").startswith("de-")

    obtida = _soap(client, _retrieve("DataExtension", "DE_457_entrada"))
    assert _texto(obtida.text, "OverallStatus") == "OK"
    assert _texto(obtida.text, "Name") == "DE Entrada OS-457"
    assert _texto(obtida.text, "FieldType") == "Text"

    inexistente = _soap(client, _retrieve("DataExtension", "DE_outra"))
    assert "<Results" not in inexistente.text  # OverallStatus OK, sem Results

    deletada = _soap(
        client,
        f'<DeleteRequest xmlns="{NS}" xmlns:xsi="{XSI}"><Objects xsi:type="DataExtension">'
        "<CustomerKey>DE_457_entrada</CustomerKey></Objects></DeleteRequest>",
    )
    assert _texto(deletada.text, "StatusCode") == "OK"
    de_novo = _soap(client, _retrieve("DataExtension", "DE_457_entrada"))
    assert "<Results" not in de_novo.text


def test_soap_data_extension_validacao(client: TestClient) -> None:
    """DE sem Fields → StatusCode Error 10006; duplicada → Error 310007 (§11.1)."""
    sem_campos = _soap(client, _criar_de("DE_x", "DE X", campos=""))
    assert _texto(sem_campos.text, "StatusCode") == "Error"
    assert _texto(sem_campos.text, "ErrorCode") == "10006"
    assert _texto(sem_campos.text, "OverallStatus") == "Error"

    assert _texto(_soap(client, _criar_de("DE_y", "DE Y")).text, "StatusCode") == "OK"
    duplicada = _soap(client, _criar_de("DE_y", "DE Y"))
    assert _texto(duplicada.text, "StatusCode") == "Error"
    assert _texto(duplicada.text, "ErrorCode") == "310007"


def test_soap_automation_create_retrieve(client: TestClient) -> None:
    corpo = (
        f'<CreateRequest xmlns="{NS}" xmlns:xsi="{XSI}"><Objects xsi:type="Automation">'
        "<CustomerKey>am_457_extract</CustomerKey><Name>Extract diário</Name>"
        "</Objects></CreateRequest>"
    )
    criada = _soap(client, corpo)
    assert _texto(criada.text, "StatusCode") == "OK"
    obtida = _soap(client, _retrieve("Automation", "am_457_extract"))
    assert _texto(obtida.text, "Name") == "Extract diário"


def test_soap_recusa_xml_invalido_token_errado_e_acao_desconhecida(client: TestClient) -> None:
    invalido = client.post(
        "/soap/Service.asmx", content="isto não é xml", headers={"Content-Type": "text/xml"}
    )
    assert invalido.status_code == 400
    assert "Fault" in invalido.text

    token_errado = _soap(client, _retrieve("DataExtension", "x"), token="furado")
    assert token_errado.status_code == 401

    acao = _soap(client, f'<PerformRequestMsg xmlns="{NS}"/>')
    assert acao.status_code == 400
    assert "não suportada" in acao.text


# ------------------------------------------------------------------------- chaos


def test_chaos_rate_limit_liga_e_desliga(client: TestClient) -> None:
    """§11.1: com rate-limit ligado, REST e SOAP respondem 429 com Retry-After."""
    assert client.post("/chaos/rate-limit").status_code == 200

    rest = client.get("/rest/interaction/v1/eventDefinitions", headers=AUTH)
    assert rest.status_code == 429
    assert rest.headers["Retry-After"] == "1"
    assert rest.json()["errorcode"] == 50200

    soap = _soap(client, _retrieve("DataExtension", "x"))
    assert soap.status_code == 429

    client.post("/chaos/rate-limit", params={"enabled": "false"})
    assert client.get("/rest/interaction/v1/eventDefinitions", headers=AUTH).status_code == 200


def test_chaos_drift_muda_leituras_sem_tocar_o_estado(client: TestClient) -> None:
    """§11.1/§5.4.5: drift ligado → leitura devolve recurso 'editado fora do twin'."""
    payload = {"name": "Entrada", "eventDefinitionKey": "k1"}
    client.post("/rest/interaction/v1/eventDefinitions", json=payload, headers=AUTH)
    _soap(client, _criar_de("DE_drift", "DE Drift"))

    client.post("/chaos/drift")
    rest = client.get("/rest/interaction/v1/eventDefinitions/key:k1", headers=AUTH)
    assert rest.json()["name"] == f"Entrada{modulo.MARCA_DRIFT}"
    soap = _soap(client, _retrieve("DataExtension", "DE_drift"))
    assert _texto(soap.text, "Name") == f"DE Drift{modulo.MARCA_DRIFT}"

    client.post("/chaos/drift", params={"enabled": "false"})
    limpo = client.get("/rest/interaction/v1/eventDefinitions/key:k1", headers=AUTH)
    assert limpo.json()["name"] == "Entrada"  # estado nunca foi mutado — só a leitura


def test_chaos_reset_limpa_estado(client: TestClient) -> None:
    client.post(
        "/rest/interaction/v1/eventDefinitions",
        json={"name": "E", "eventDefinitionKey": "k1"},
        headers=AUTH,
    )
    client.post("/chaos/rate-limit")
    client.post("/chaos/reset")
    assert client.get("/rest/interaction/v1/eventDefinitions", headers=AUTH).json()["count"] == 0
