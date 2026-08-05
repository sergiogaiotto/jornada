"""Adapter HTTP do DataCloudPort — fala com o mock-datacloud (compose) ou, em prod,
com o Data Cloud real. NUNCA usado em teste (§1.3.5: mocks §11; testes usam o adapter
de fixtures ou dublês em `app.state.datacloud`).

OAuth client-credentials no `DC_AUTH_URL` + consultas no `DC_API_URL` (§3.1). Client
httpx lazy; `republicado_em` absoluto do serviço vira `republicado_ha_horas` relativo
(contrato da porta) usando o relógio injetado.
"""

from datetime import UTC, datetime
from typing import Any

import httpx

from app.config import Settings


class DataCloudHttp:
    """Implementa DataCloudPort sobre HTTP (token + /segments — mock-datacloud §11.2)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._token: str | None = None

    # ------------------------------------------------------------------ interno
    def _autenticar(self, client: httpx.Client) -> str:
        if self._token is None:
            resposta = client.post(
                self._settings.dc_auth_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._settings.dc_client_id,
                    "client_secret": self._settings.dc_client_secret,
                },
            )
            resposta.raise_for_status()
            self._token = str(resposta.json()["access_token"])
        return self._token

    def _get(self, caminho: str) -> Any:
        with httpx.Client(timeout=10.0) as client:
            token = self._autenticar(client)
            resposta = client.get(
                f"{self._settings.dc_api_url}{caminho}",
                headers={"Authorization": f"Bearer {token}"},
            )
            if resposta.status_code == 404:
                return None
            resposta.raise_for_status()
            return resposta.json()

    @staticmethod
    def _com_frescor_relativo(segmento: dict[str, Any]) -> dict[str, Any]:
        """`republicado_em` ISO do serviço → `republicado_ha_horas` (contrato da porta)."""
        dados = dict(segmento)
        republicado_em = dados.pop("republicado_em", None)
        if "republicado_ha_horas" not in dados and republicado_em:
            delta = datetime.now(UTC) - datetime.fromisoformat(republicado_em)
            dados["republicado_ha_horas"] = max(0.0, delta.total_seconds() / 3600.0)
        return dados

    # -------------------------------------------------------------------- porta
    def segmentos(self) -> list[dict[str, Any]]:
        corpo = self._get("/segments") or {}
        return [self._com_frescor_relativo(s) for s in corpo.get("segments", [])]

    def segmento(self, segmento_id: str) -> dict[str, Any] | None:
        corpo = self._get(f"/segments/{segmento_id}")
        return self._com_frescor_relativo(corpo) if corpo else None

    def relatorio(self, segmento_id: str) -> dict[str, Any] | None:
        corpo = self._get(f"/segments/{segmento_id}/report")
        return dict(corpo) if corpo else None
