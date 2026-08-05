"""Adapter HTTP do SFMCPort — REST via httpx + SOAP por template XML (SDD §2.1, §11.1).

- REST: `httpx.AsyncClient` com `transport` INJETÁVEL — teste injeta
  `httpx.ASGITransport(app=mock_sfmc)` e conversa com o mock IN-PROCESS (nenhum
  servidor/porta real — §1.3.5). Em dev/compose o transport default resolve as URLs
  `SFMC_*` do §3.1 (mock-sfmc); em prod, o SFMC real.
- SOAP: envelopes montados por template de string (Create/Retrieve/Delete de
  DataExtension e Automation) e parseados com ElementTree — suficiente para o contrato
  §11.1. `zeep` (§3.3) fica reservado ao adapter contra o SFMC real caso o template
  não baste; NÃO é exigido em teste (nem importado aqui).
- Retry/backoff (tenacity) e orçamento `SFMC_API_BUDGET_PER_APPLY` são do compilador
  (§5.4.2) — o adapter só traduz respostas em erros tipados da porta.

LLM proibido neste caminho (§5.4): tudo aqui é determinístico.
"""

from typing import Any
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

import httpx

from app.config import Settings
from application.ports.sfmc import SfmcIndisponivel, SfmcRateLimit, SfmcRecusado

_NS_PARTNER = "http://exacttarget.com/wsdl/partnerAPI"
_XSI = "http://www.w3.org/2001/XMLSchema-instance"

_ENVELOPE = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">'
    '<s:Header><fueloauth xmlns="http://exacttarget.com">{token}</fueloauth></s:Header>'
    "<s:Body>{corpo}</s:Body></s:Envelope>"
)


def _local(tag: object) -> str:
    return str(tag).rsplit("}", 1)[-1]


def _texto(elemento: ET.Element, nome: str) -> str | None:
    alvo = next((e for e in elemento.iter() if _local(e.tag) == nome), None)
    return alvo.text.strip() if alvo is not None and alvo.text else None


def _texto_filho(elemento: ET.Element, nome: str) -> str | None:
    alvo = next((f for f in elemento if _local(f.tag) == nome), None)
    return alvo.text.strip() if alvo is not None and alvo.text else None


class SfmcHttp:
    """Implementa SFMCPort sobre HTTP (token v2 + REST + SOAP Service.asmx)."""

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self._settings = settings
        self._transport = transport  # teste: ASGITransport(app=mock_sfmc) — §1.3.5
        self._token: str | None = None

    # ------------------------------------------------------------------ infra http
    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=10.0, transport=self._transport)

    async def _autenticar(self, client: httpx.AsyncClient) -> str:
        if self._token is None:
            try:
                resposta = await client.post(
                    self._settings.sfmc_auth_url,
                    json={
                        "grant_type": "client_credentials",
                        "client_id": self._settings.sfmc_client_id,
                        "client_secret": self._settings.sfmc_client_secret,
                        "account_id": self._settings.sfmc_account_mid,
                    },
                )
            except httpx.HTTPError as exc:
                raise SfmcIndisponivel(f"Falha de rede no token SFMC: {exc}") from exc
            if resposta.status_code >= 400:
                raise SfmcRecusado(f"Token SFMC recusado ({resposta.status_code})")
            self._token = str(resposta.json()["access_token"])
        return self._token

    @staticmethod
    def _checar_status(resposta: httpx.Response) -> None:
        if resposta.status_code == 429:
            retry_after = resposta.headers.get("Retry-After")
            raise SfmcRateLimit(
                "Rate limit do SFMC (429)",
                retry_after=float(retry_after) if retry_after else None,
            )
        if resposta.status_code >= 500:
            raise SfmcIndisponivel(f"SFMC indisponível ({resposta.status_code})")

    async def _rest(
        self,
        metodo: str,
        caminho: str,
        json_: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> httpx.Response:
        async with self._client() as client:
            token = await self._autenticar(client)
            try:
                resposta = await client.request(
                    metodo,
                    f"{self._settings.sfmc_rest_url}{caminho}",
                    json=json_,
                    params=params,
                    headers={"Authorization": f"Bearer {token}"},
                )
            except httpx.HTTPError as exc:
                raise SfmcIndisponivel(f"Falha de rede no REST SFMC: {exc}") from exc
        self._checar_status(resposta)
        return resposta

    @staticmethod
    def _recusado(resposta: httpx.Response) -> SfmcRecusado:
        try:
            mensagem = str(resposta.json().get("message", resposta.text))
        except ValueError:
            mensagem = resposta.text
        return SfmcRecusado(f"SFMC recusou ({resposta.status_code}): {mensagem}")

    def _json_criado(self, resposta: httpx.Response) -> dict[str, Any]:
        if resposta.status_code >= 400:
            raise self._recusado(resposta)
        return dict(resposta.json())

    # ------------------------------------------------------------------------ REST
    async def criar_event_definition(self, definicao: dict[str, Any]) -> dict[str, Any]:
        resposta = await self._rest("POST", "/interaction/v1/eventDefinitions", json_=definicao)
        return self._json_criado(resposta)

    async def obter_event_definition(self, chave: str) -> dict[str, Any] | None:
        resposta = await self._rest("GET", f"/interaction/v1/eventDefinitions/key:{chave}")
        return None if resposta.status_code == 404 else dict(resposta.json())

    async def destruir_event_definition(self, chave: str) -> bool:
        resposta = await self._rest("DELETE", f"/interaction/v1/eventDefinitions/key:{chave}")
        return resposta.status_code == 204

    async def criar_interaction(self, interaction: dict[str, Any]) -> dict[str, Any]:
        resposta = await self._rest("POST", "/interaction/v1/interactions", json_=interaction)
        return self._json_criado(resposta)

    async def obter_interaction(self, chave: str) -> dict[str, Any] | None:
        resposta = await self._rest("GET", f"/interaction/v1/interactions/key:{chave}")
        return None if resposta.status_code == 404 else dict(resposta.json())

    async def destruir_interaction(self, chave: str) -> bool:
        resposta = await self._rest("DELETE", f"/interaction/v1/interactions/key:{chave}")
        return resposta.status_code == 204

    async def criar_asset(self, asset: dict[str, Any]) -> dict[str, Any]:
        resposta = await self._rest("POST", "/asset/v1/content/assets", json_=asset)
        return self._json_criado(resposta)

    async def obter_asset(self, customer_key: str) -> dict[str, Any] | None:
        resposta = await self._rest(
            "GET", "/asset/v1/content/assets", params={"customerKey": customer_key}
        )
        itens = resposta.json().get("items", []) if resposta.status_code < 400 else []
        return dict(itens[0]) if itens else None

    async def destruir_asset(self, customer_key: str) -> bool:
        recurso = await self.obter_asset(customer_key)
        if recurso is None:
            return False
        resposta = await self._rest("DELETE", f"/asset/v1/content/assets/{recurso['id']}")
        return resposta.status_code == 204

    # ------------------------------------------------------------- SOAP simplificado
    async def _soap(self, corpo: str, acao: str) -> ET.Element:
        async with self._client() as client:
            token = await self._autenticar(client)
            try:
                resposta = await client.post(
                    f"{self._settings.sfmc_soap_url}/Service.asmx",
                    content=_ENVELOPE.format(token=token, corpo=corpo),
                    headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": acao},
                )
            except httpx.HTTPError as exc:
                raise SfmcIndisponivel(f"Falha de rede no SOAP SFMC: {exc}") from exc
        self._checar_status(resposta)
        if resposta.status_code >= 400:
            raise SfmcRecusado(f"SOAP SFMC recusado ({resposta.status_code})")
        return ET.fromstring(resposta.text)

    @staticmethod
    def _corpo_create(tipo: str, conteudo: str) -> str:
        return (
            f'<CreateRequest xmlns="{_NS_PARTNER}" xmlns:xsi="{_XSI}">'
            f'<Objects xsi:type="{tipo}">{conteudo}</Objects></CreateRequest>'
        )

    @staticmethod
    def _corpo_retrieve(tipo: str, customer_key: str) -> str:
        return (
            f'<RetrieveRequestMsg xmlns="{_NS_PARTNER}" xmlns:xsi="{_XSI}">'
            f"<RetrieveRequest><ObjectType>{tipo}</ObjectType>"
            "<Properties>CustomerKey</Properties><Properties>Name</Properties>"
            '<Filter xsi:type="SimpleFilterPart"><Property>CustomerKey</Property>'
            f"<SimpleOperator>equals</SimpleOperator><Value>{escape(customer_key)}</Value>"
            "</Filter></RetrieveRequest></RetrieveRequestMsg>"
        )

    @staticmethod
    def _corpo_delete(tipo: str, customer_key: str) -> str:
        return (
            f'<DeleteRequest xmlns="{_NS_PARTNER}" xmlns:xsi="{_XSI}">'
            f'<Objects xsi:type="{tipo}">'
            f"<CustomerKey>{escape(customer_key)}</CustomerKey></Objects></DeleteRequest>"
        )

    @staticmethod
    def _exigir_ok(raiz: ET.Element, contexto: str) -> None:
        if _texto(raiz, "StatusCode") != "OK":
            mensagem = _texto(raiz, "StatusMessage") or "StatusCode != OK"
            raise SfmcRecusado(f"{contexto}: {mensagem}")

    @staticmethod
    def _resultado_retrieve(raiz: ET.Element) -> dict[str, Any] | None:
        resultado = next((e for e in raiz.iter() if _local(e.tag) == "Results"), None)
        if resultado is None:
            return None
        recurso: dict[str, Any] = {
            "customerKey": _texto_filho(resultado, "CustomerKey"),
            "name": _texto_filho(resultado, "Name"),
            "objectId": _texto_filho(resultado, "ObjectID"),
        }
        campos = [
            {"name": _texto_filho(campo, "Name"), "fieldType": _texto_filho(campo, "FieldType")}
            for campo in resultado.iter()
            if _local(campo.tag) == "Field"
        ]
        if campos:
            recurso["fields"] = campos
        return recurso

    async def criar_data_extension(self, de: dict[str, Any]) -> dict[str, Any]:
        campos = "".join(
            f"<Field><Name>{escape(str(campo['name']))}</Name>"
            f"<FieldType>{escape(str(campo['fieldType']))}</FieldType></Field>"
            for campo in de.get("fields", [])
        )
        conteudo = (
            f"<CustomerKey>{escape(str(de['customerKey']))}</CustomerKey>"
            f"<Name>{escape(str(de['name']))}</Name><Fields>{campos}</Fields>"
        )
        raiz = await self._soap(self._corpo_create("DataExtension", conteudo), "Create")
        self._exigir_ok(raiz, "Create DataExtension")
        return {
            "customerKey": de["customerKey"],
            "name": de["name"],
            "objectId": _texto(raiz, "NewObjectID"),
        }

    async def obter_data_extension(self, customer_key: str) -> dict[str, Any] | None:
        raiz = await self._soap(self._corpo_retrieve("DataExtension", customer_key), "Retrieve")
        return self._resultado_retrieve(raiz)

    async def destruir_data_extension(self, customer_key: str) -> bool:
        raiz = await self._soap(self._corpo_delete("DataExtension", customer_key), "Delete")
        return _texto(raiz, "StatusCode") == "OK"

    async def criar_automation(self, automacao: dict[str, Any]) -> dict[str, Any]:
        conteudo = (
            f"<CustomerKey>{escape(str(automacao['customerKey']))}</CustomerKey>"
            f"<Name>{escape(str(automacao['name']))}</Name>"
        )
        raiz = await self._soap(self._corpo_create("Automation", conteudo), "Create")
        self._exigir_ok(raiz, "Create Automation")
        return {
            "customerKey": automacao["customerKey"],
            "name": automacao["name"],
            "objectId": _texto(raiz, "NewObjectID"),
        }

    async def obter_automation(self, customer_key: str) -> dict[str, Any] | None:
        raiz = await self._soap(self._corpo_retrieve("Automation", customer_key), "Retrieve")
        return self._resultado_retrieve(raiz)

    async def destruir_automation(self, customer_key: str) -> bool:
        raiz = await self._soap(self._corpo_delete("Automation", customer_key), "Delete")
        return _texto(raiz, "StatusCode") == "OK"
