"""mock-sfmc — simulação do SFMC para dev/CI (SDD §11.1, entrega completa pré-M9).

- `POST /v2/token`: OAuth2 client_credentials (credenciais mock — nunca segredos reais).
- REST (`/rest/...`): eventDefinitions, interactions (journeys) e assets, com validação
  de payload (erros no formato SFMC `{message, errorcode}`) e estado em memória.
- SOAP simplificado (`POST /soap/Service.asmx`): Create/Retrieve/Delete de DataExtension
  e Automation via XML (namespaces tolerados por local-name; sem WSDL — §11.1).
- Chaos (§11.1): `POST /chaos/rate-limit` (REST/SOAP passam a responder 429 com
  Retry-After) e `POST /chaos/drift` (leituras devolvem recurso EDITADO fora do twin —
  insumo do drift check §5.4.5/M9-A4). `POST /chaos/reset` limpa estado (higiene de
  teste; não faz parte do contrato do produto).

Estado é POR INSTÂNCIA de app: `create_app()` nasce limpo (testes) e o módulo expõe
`app = create_app()` para o uvicorn do compose. Em teste o app é usado IN-PROCESS via
TestClient/ASGITransport — nenhum servidor http real (§1.3.5).
"""

from typing import Any
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

TOKEN = "mock-sfmc-access-token"
CLIENT_ID = "mock"
CLIENT_SECRET = "mock"  # valor mock do §3.1 — não é segredo real
MARCA_DRIFT = " (editado fora do twin)"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
NS_PARTNER = "http://exacttarget.com/wsdl/partnerAPI"


def _estado_inicial() -> dict[str, Any]:
    return {
        "chaos": {"rate_limit": False, "drift": False},
        "event_definitions": {},  # eventDefinitionKey -> recurso
        "interactions": {},  # key -> recurso
        "assets": {},  # id (int) -> recurso
        "data_extensions": {},  # CustomerKey -> {customerKey, name, fields, objectId}
        "automations": {},  # CustomerKey -> {customerKey, name, objectId}
        "seq": 0,
    }


# --------------------------------------------------------------------- contratos REST


class EventDefinitionIn(BaseModel):
    """Payload mínimo do POST /interaction/v1/eventDefinitions (SFMC REST)."""

    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=1)
    eventDefinitionKey: str = Field(min_length=1)
    type: str = "APIEvent"
    dataExtensionName: str | None = None


class InteractionIn(BaseModel):
    """Payload mínimo do POST /interaction/v1/interactions (journey spec)."""

    model_config = ConfigDict(extra="allow")

    key: str = Field(min_length=1)
    name: str = Field(min_length=1)
    workflowApiVersion: float = 1.0
    triggers: list[dict[str, Any]] = Field(default_factory=list)
    activities: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def _atividades_tem_key_e_type(self) -> "InteractionIn":
        for atividade in self.activities:
            if not atividade.get("key") or not atividade.get("type"):
                raise ValueError("toda activity exige 'key' e 'type'")
        return self


class AssetTypeIn(BaseModel):
    id: int | None = None
    name: str | None = None

    @model_validator(mode="after")
    def _id_ou_name(self) -> "AssetTypeIn":
        if self.id is None and self.name is None:
            raise ValueError("assetType exige 'id' ou 'name'")
        return self


class AssetIn(BaseModel):
    """Payload mínimo do POST /asset/v1/content/assets."""

    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=1)
    assetType: AssetTypeIn
    customerKey: str | None = None
    content: str | None = None


# ------------------------------------------------------------------------- helpers


def _erro_sfmc(status: int, mensagem: str, errorcode: int) -> HTTPException:
    return HTTPException(status_code=status, detail={"message": mensagem, "errorcode": errorcode})


def _estado(request: Request) -> dict[str, Any]:
    return request.app.state.sfmc  # type: ignore[no-any-return]


def _proximo_id(estado: dict[str, Any]) -> int:
    estado["seq"] += 1
    return int(estado["seq"])


def _com_drift(estado: dict[str, Any], recurso: dict[str, Any]) -> dict[str, Any]:
    """Leituras sob chaos drift devolvem o recurso como se editado por fora (§5.4.5)."""
    if not estado["chaos"]["drift"]:
        return recurso
    alterado = dict(recurso)
    alterado["name"] = f"{alterado.get('name', '')}{MARCA_DRIFT}"
    alterado["modifiedDate"] = "2026-08-04T23:59:59Z"
    return alterado


def _guardas_rest(request: Request) -> dict[str, Any]:
    """Ordem: chaos rate-limit (dominante) → Bearer token. Devolve o estado."""
    estado = _estado(request)
    if estado["chaos"]["rate_limit"]:
        raise HTTPException(
            status_code=429,
            detail={"message": "Rate limit exceeded (chaos)", "errorcode": 50200},
            headers={"Retry-After": "1"},
        )
    if request.headers.get("Authorization") != f"Bearer {TOKEN}":
        raise _erro_sfmc(401, "Not Authorized", 401)
    return estado


# ----------------------------------------------------------------------------- app


def create_app() -> FastAPI:
    app = FastAPI(title="mock-sfmc", version="1.0.0")
    app.state.sfmc = _estado_inicial()

    @app.exception_handler(RequestValidationError)
    async def _validacao_como_sfmc(request: Request, exc: RequestValidationError) -> JSONResponse:
        """SFMC responde 400 {message, errorcode} — não o 422 default do FastAPI."""
        detalhes = "; ".join(
            f"{'.'.join(str(p) for p in erro['loc'])}: {erro['msg']}" for erro in exc.errors()
        )
        return JSONResponse(
            status_code=400,
            content={"message": f"Validation error: {detalhes}", "errorcode": 10006},
        )

    @app.exception_handler(HTTPException)
    async def _detail_na_raiz(request: Request, exc: HTTPException) -> JSONResponse:
        """Erros SFMC vão na raiz do corpo ({message, errorcode}), não sob 'detail'."""
        corpo = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
        return JSONResponse(status_code=exc.status_code, content=corpo, headers=exc.headers)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    # ------------------------------------------------------------------ OAuth (§11.1)

    @app.post("/v2/token")
    def token(payload: dict[str, Any]) -> dict[str, Any]:
        """OAuth2 client_credentials do SFMC — valida grant e credenciais mock."""
        if payload.get("grant_type") != "client_credentials":
            raise _erro_sfmc(400, "unsupported_grant_type", 10006)
        if payload.get("client_id") != CLIENT_ID or payload.get("client_secret") != CLIENT_SECRET:
            raise _erro_sfmc(401, "invalid_client: credenciais mock são mock/mock", 1)
        return {
            "access_token": TOKEN,
            "token_type": "Bearer",
            "expires_in": 1079,
            "scope": "email_read email_write journeys_read journeys_write",
            "rest_instance_url": "http://mock-sfmc:8080/rest",
            "soap_instance_url": "http://mock-sfmc:8080/soap",
        }

    # ------------------------------------------------------------------ chaos (§11.1)

    @app.post("/chaos/rate-limit")
    def chaos_rate_limit(request: Request, enabled: bool = True) -> dict[str, Any]:
        _estado(request)["chaos"]["rate_limit"] = enabled
        return {"chaos": _estado(request)["chaos"]}

    @app.post("/chaos/drift")
    def chaos_drift(request: Request, enabled: bool = True) -> dict[str, Any]:
        _estado(request)["chaos"]["drift"] = enabled
        return {"chaos": _estado(request)["chaos"]}

    @app.post("/chaos/reset")
    def chaos_reset(request: Request) -> dict[str, Any]:
        request.app.state.sfmc = _estado_inicial()
        return {"chaos": request.app.state.sfmc["chaos"]}

    # ------------------------------------------------------------------------- REST

    @app.get("/rest/platform/v1/tokenContext")
    def token_context(estado: dict[str, Any] = Depends(_guardas_rest)) -> dict[str, Any]:
        return {"enterprise": {"id": 1}, "organization": {"id": 1}, "user": {"id": 1}}

    @app.post("/rest/interaction/v1/eventDefinitions", status_code=201)
    def criar_event_definition(
        payload: EventDefinitionIn, estado: dict[str, Any] = Depends(_guardas_rest)
    ) -> dict[str, Any]:
        chave = payload.eventDefinitionKey
        if chave in estado["event_definitions"]:
            raise _erro_sfmc(400, f"Event definition '{chave}' já existe", 30003)
        recurso = payload.model_dump() | {"id": f"ed-{_proximo_id(estado):04d}"}
        estado["event_definitions"][chave] = recurso
        return recurso

    @app.get("/rest/interaction/v1/eventDefinitions")
    def listar_event_definitions(
        estado: dict[str, Any] = Depends(_guardas_rest),
    ) -> dict[str, Any]:
        itens = [_com_drift(estado, r) for r in estado["event_definitions"].values()]
        return {"count": len(itens), "items": itens}

    @app.get("/rest/interaction/v1/eventDefinitions/key:{chave}")
    def obter_event_definition(
        chave: str, estado: dict[str, Any] = Depends(_guardas_rest)
    ) -> dict[str, Any]:
        recurso = estado["event_definitions"].get(chave)
        if recurso is None:
            raise _erro_sfmc(404, f"Event definition '{chave}' não existe", 404)
        return _com_drift(estado, recurso)

    @app.delete("/rest/interaction/v1/eventDefinitions/key:{chave}", status_code=204)
    def destruir_event_definition(
        chave: str, estado: dict[str, Any] = Depends(_guardas_rest)
    ) -> Response:
        if chave not in estado["event_definitions"]:
            raise _erro_sfmc(404, f"Event definition '{chave}' não existe", 404)
        del estado["event_definitions"][chave]
        return Response(status_code=204)

    @app.post("/rest/interaction/v1/interactions", status_code=201)
    def criar_interaction(
        payload: InteractionIn, estado: dict[str, Any] = Depends(_guardas_rest)
    ) -> dict[str, Any]:
        if payload.key in estado["interactions"]:
            raise _erro_sfmc(400, f"Interaction '{payload.key}' já existe", 30003)
        recurso = payload.model_dump() | {
            "id": f"jr-{_proximo_id(estado):04d}",
            "status": "Draft",
            "version": 1,
        }
        estado["interactions"][payload.key] = recurso
        return recurso

    @app.get("/rest/interaction/v1/interactions")
    def listar_interactions(estado: dict[str, Any] = Depends(_guardas_rest)) -> dict[str, Any]:
        itens = [_com_drift(estado, r) for r in estado["interactions"].values()]
        return {"count": len(itens), "items": itens}

    @app.get("/rest/interaction/v1/interactions/key:{chave}")
    def obter_interaction(
        chave: str, estado: dict[str, Any] = Depends(_guardas_rest)
    ) -> dict[str, Any]:
        recurso = estado["interactions"].get(chave)
        if recurso is None:
            raise _erro_sfmc(404, f"Interaction '{chave}' não existe", 404)
        return _com_drift(estado, recurso)

    @app.delete("/rest/interaction/v1/interactions/key:{chave}", status_code=204)
    def destruir_interaction(
        chave: str, estado: dict[str, Any] = Depends(_guardas_rest)
    ) -> Response:
        if chave not in estado["interactions"]:
            raise _erro_sfmc(404, f"Interaction '{chave}' não existe", 404)
        del estado["interactions"][chave]
        return Response(status_code=204)

    @app.post("/rest/asset/v1/content/assets", status_code=201)
    def criar_asset(
        payload: AssetIn, estado: dict[str, Any] = Depends(_guardas_rest)
    ) -> dict[str, Any]:
        if payload.customerKey and any(
            r.get("customerKey") == payload.customerKey for r in estado["assets"].values()
        ):
            raise _erro_sfmc(400, f"Asset '{payload.customerKey}' já existe", 30003)
        asset_id = _proximo_id(estado)
        recurso = payload.model_dump() | {"id": asset_id}
        estado["assets"][asset_id] = recurso
        return recurso

    @app.get("/rest/asset/v1/content/assets")
    def listar_assets(
        estado: dict[str, Any] = Depends(_guardas_rest),
        customer_key: str | None = Query(default=None, alias="customerKey"),
    ) -> dict[str, Any]:
        itens = [
            _com_drift(estado, r)
            for r in estado["assets"].values()
            if customer_key is None or r.get("customerKey") == customer_key
        ]
        return {"count": len(itens), "items": itens}

    @app.get("/rest/asset/v1/content/assets/{asset_id}")
    def obter_asset(
        asset_id: int, estado: dict[str, Any] = Depends(_guardas_rest)
    ) -> dict[str, Any]:
        recurso = estado["assets"].get(asset_id)
        if recurso is None:
            raise _erro_sfmc(404, f"Asset {asset_id} não existe", 404)
        return _com_drift(estado, recurso)

    @app.delete("/rest/asset/v1/content/assets/{asset_id}", status_code=204)
    def destruir_asset(asset_id: int, estado: dict[str, Any] = Depends(_guardas_rest)) -> Response:
        if asset_id not in estado["assets"]:
            raise _erro_sfmc(404, f"Asset {asset_id} não existe", 404)
        del estado["assets"][asset_id]
        return Response(status_code=204)

    # ------------------------------------------------------------- SOAP simplificado

    @app.post("/soap/Service.asmx")
    async def soap(request: Request) -> Response:
        estado = _estado(request)
        if estado["chaos"]["rate_limit"]:
            return _resposta_soap(
                _fault("Server", "Rate limit exceeded (chaos)"),
                status=429,
                headers={"Retry-After": "1"},
            )
        corpo_bruto = await request.body()
        try:
            envelope = ET.fromstring(corpo_bruto)
        except ET.ParseError as exc:
            return _resposta_soap(_fault("Client", f"XML inválido: {exc}"), status=400)
        if _texto_descendente(envelope, "fueloauth") != TOKEN:
            return _resposta_soap(_fault("Client", "Token fueloauth inválido"), status=401)
        requisicao = _corpo_soap(envelope)
        if requisicao is None:
            return _resposta_soap(_fault("Client", "Body SOAP vazio"), status=400)
        acao = _local(requisicao.tag)
        if acao == "CreateRequest":
            return _resposta_soap(_soap_create(estado, requisicao))
        if acao == "RetrieveRequestMsg":
            return _resposta_soap(_soap_retrieve(estado, requisicao))
        if acao == "DeleteRequest":
            return _resposta_soap(_soap_delete(estado, requisicao))
        return _resposta_soap(_fault("Client", f"Ação SOAP não suportada: {acao}"), status=400)

    return app


# ------------------------------------------------------------------ SOAP: parsing


def _local(tag: object) -> str:
    return str(tag).rsplit("}", 1)[-1]


def _filho_direto(elemento: ET.Element, nome: str) -> ET.Element | None:
    return next((filho for filho in elemento if _local(filho.tag) == nome), None)


def _filhos_diretos(elemento: ET.Element, nome: str) -> list[ET.Element]:
    return [filho for filho in elemento if _local(filho.tag) == nome]


def _texto_filho(elemento: ET.Element, nome: str) -> str | None:
    filho = _filho_direto(elemento, nome)
    return filho.text.strip() if filho is not None and filho.text else None


def _texto_descendente(elemento: ET.Element, nome: str) -> str | None:
    alvo = next((e for e in elemento.iter() if _local(e.tag) == nome), None)
    return alvo.text.strip() if alvo is not None and alvo.text else None


def _corpo_soap(envelope: ET.Element) -> ET.Element | None:
    body = next((e for e in envelope.iter() if _local(e.tag) == "Body"), None)
    if body is None:
        return None
    return next(iter(body), None)


def _tipo_xsi(objeto: ET.Element) -> str:
    return objeto.attrib.get(f"{{{XSI}}}type", "").rsplit(":", 1)[-1]


# ------------------------------------------------------------- SOAP: operações


def _soap_create(estado: dict[str, Any], requisicao: ET.Element) -> str:
    resultados: list[str] = []
    for objeto in _filhos_diretos(requisicao, "Objects"):
        tipo = _tipo_xsi(objeto)
        if tipo == "DataExtension":
            resultados.append(_criar_data_extension(estado, objeto))
        elif tipo == "Automation":
            resultados.append(_criar_automation(estado, objeto))
        else:
            resultados.append(
                _resultado_create("Error", f"Tipo não suportado: {tipo or '(sem xsi:type)'}", 10006)
            )
    ok = all("<StatusCode>OK</StatusCode>" in r for r in resultados)
    return (
        f'<CreateResponse xmlns="{NS_PARTNER}">'
        f"{''.join(resultados)}<OverallStatus>{'OK' if ok else 'Error'}</OverallStatus>"
        "</CreateResponse>"
    )


def _criar_data_extension(estado: dict[str, Any], objeto: ET.Element) -> str:
    customer_key = _texto_filho(objeto, "CustomerKey")
    nome = _texto_filho(objeto, "Name")
    if not customer_key or not nome:
        return _resultado_create("Error", "DataExtension exige CustomerKey e Name", 10006)
    if customer_key in estado["data_extensions"]:
        return _resultado_create("Error", f"DataExtension '{customer_key}' já existe", 310007)
    campos: list[dict[str, str]] = []
    bloco_fields = _filho_direto(objeto, "Fields")
    for campo in _filhos_diretos(bloco_fields, "Field") if bloco_fields is not None else []:
        nome_campo = _texto_filho(campo, "Name")
        tipo_campo = _texto_filho(campo, "FieldType")
        if not nome_campo or not tipo_campo:
            return _resultado_create("Error", "Field exige Name e FieldType", 10006)
        campos.append({"name": nome_campo, "fieldType": tipo_campo})
    if not campos:
        return _resultado_create("Error", "DataExtension exige ao menos um Field", 10006)
    object_id = f"de-{_proximo_id(estado):04d}"
    estado["data_extensions"][customer_key] = {
        "customerKey": customer_key,
        "name": nome,
        "fields": campos,
        "objectId": object_id,
    }
    return _resultado_create("OK", "Created", None, object_id)


def _criar_automation(estado: dict[str, Any], objeto: ET.Element) -> str:
    customer_key = _texto_filho(objeto, "CustomerKey")
    nome = _texto_filho(objeto, "Name")
    if not customer_key or not nome:
        return _resultado_create("Error", "Automation exige CustomerKey e Name", 10006)
    if customer_key in estado["automations"]:
        return _resultado_create("Error", f"Automation '{customer_key}' já existe", 310007)
    object_id = f"am-{_proximo_id(estado):04d}"
    estado["automations"][customer_key] = {
        "customerKey": customer_key,
        "name": nome,
        "objectId": object_id,
    }
    return _resultado_create("OK", "Created", None, object_id)


def _soap_retrieve(estado: dict[str, Any], requisicao: ET.Element) -> str:
    pedido = _filho_direto(requisicao, "RetrieveRequest")
    tipo = _texto_filho(pedido, "ObjectType") if pedido is not None else None
    colecoes = {"DataExtension": "data_extensions", "Automation": "automations"}
    if tipo not in colecoes:
        return (
            f'<RetrieveResponseMsg xmlns="{NS_PARTNER}">'
            f"<OverallStatus>Error: ObjectType não suportado: {escape(str(tipo))}</OverallStatus>"
            "</RetrieveResponseMsg>"
        )
    filtro_ck: str | None = None
    filtro = _filho_direto(pedido, "Filter") if pedido is not None else None
    if filtro is not None and _texto_filho(filtro, "Property") == "CustomerKey":
        filtro_ck = _texto_filho(filtro, "Value")
    recursos = [
        _com_drift(estado, r)
        for ck, r in estado[colecoes[tipo]].items()
        if filtro_ck is None or ck == filtro_ck
    ]
    resultados = "".join(_resultado_retrieve(tipo, r) for r in recursos)
    return (
        f'<RetrieveResponseMsg xmlns="{NS_PARTNER}" xmlns:xsi="{XSI}">'
        f"<OverallStatus>OK</OverallStatus>{resultados}</RetrieveResponseMsg>"
    )


def _soap_delete(estado: dict[str, Any], requisicao: ET.Element) -> str:
    resultados: list[str] = []
    colecoes = {"DataExtension": "data_extensions", "Automation": "automations"}
    for objeto in _filhos_diretos(requisicao, "Objects"):
        tipo = _tipo_xsi(objeto)
        customer_key = _texto_filho(objeto, "CustomerKey")
        if tipo not in colecoes or not customer_key:
            resultados.append(
                _resultado_delete("Error", "Delete exige xsi:type suportado e CustomerKey", 10006)
            )
        elif customer_key not in estado[colecoes[tipo]]:
            resultados.append(
                _resultado_delete("Error", f"{tipo} '{customer_key}' não existe", 404)
            )
        else:
            del estado[colecoes[tipo]][customer_key]
            resultados.append(_resultado_delete("OK", "Deleted", None))
    ok = all("<StatusCode>OK</StatusCode>" in r for r in resultados)
    return (
        f'<DeleteResponse xmlns="{NS_PARTNER}">'
        f"{''.join(resultados)}<OverallStatus>{'OK' if ok else 'Error'}</OverallStatus>"
        "</DeleteResponse>"
    )


# ------------------------------------------------------------- SOAP: serialização


def _resultado_create(
    status: str, mensagem: str, codigo_erro: int | None, object_id: str | None = None
) -> str:
    erro = f"<ErrorCode>{codigo_erro}</ErrorCode>" if codigo_erro is not None else ""
    novo = f"<NewObjectID>{escape(object_id)}</NewObjectID>" if object_id else ""
    return (
        f"<Results><StatusCode>{status}</StatusCode>"
        f"<StatusMessage>{escape(mensagem)}</StatusMessage>{erro}{novo}</Results>"
    )


def _resultado_delete(status: str, mensagem: str, codigo_erro: int | None) -> str:
    erro = f"<ErrorCode>{codigo_erro}</ErrorCode>" if codigo_erro is not None else ""
    return (
        f"<Results><StatusCode>{status}</StatusCode>"
        f"<StatusMessage>{escape(mensagem)}</StatusMessage>{erro}</Results>"
    )


def _resultado_retrieve(tipo: str, recurso: dict[str, Any]) -> str:
    campos = "".join(
        f"<Field><Name>{escape(c['name'])}</Name>"
        f"<FieldType>{escape(c['fieldType'])}</FieldType></Field>"
        for c in recurso.get("fields", [])
    )
    fields = f"<Fields>{campos}</Fields>" if campos else ""
    return (
        f'<Results xsi:type="{tipo}">'
        f"<ObjectID>{escape(str(recurso.get('objectId', '')))}</ObjectID>"
        f"<CustomerKey>{escape(str(recurso.get('customerKey', '')))}</CustomerKey>"
        f"<Name>{escape(str(recurso.get('name', '')))}</Name>{fields}</Results>"
    )


def _fault(codigo: str, mensagem: str) -> str:
    return (
        f"<soap:Fault><faultcode>soap:{codigo}</faultcode>"
        f"<faultstring>{escape(mensagem)}</faultstring></soap:Fault>"
    )


def _resposta_soap(
    corpo: str, status: int = 200, headers: dict[str, str] | None = None
) -> Response:
    envelope = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
        f"<soap:Body>{corpo}</soap:Body></soap:Envelope>"
    )
    return Response(
        content=envelope, status_code=status, media_type="text/xml", headers=headers or {}
    )


app = create_app()
