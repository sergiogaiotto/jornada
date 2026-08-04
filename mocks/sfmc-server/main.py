"""mock-sfmc — stub mínimo M0 (SDD §11.1).

M0: token OAuth + endpoints de chaos (flags em memória) + healthz.
M9 completa: REST (eventDefinitions, interactions, assets), SOAP (DataExtension,
Automation) com validação de schema, estado em memória e injeção de drift.
"""

from typing import Any

from fastapi import FastAPI, Response

app = FastAPI(title="mock-sfmc", version="0.1.0")

STATE: dict[str, Any] = {"chaos": {"rate_limit": False, "drift": False}}


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v2/token")
def token() -> dict[str, Any]:
    """OAuth2 client_credentials do SFMC (valores mock — nunca segredos reais)."""
    return {
        "access_token": "mock-sfmc-access-token",
        "token_type": "Bearer",
        "expires_in": 1079,
        "scope": "email_read email_write journeys_read journeys_write",
        "rest_instance_url": "http://mock-sfmc:8080/rest",
        "soap_instance_url": "http://mock-sfmc:8080/soap",
    }


@app.post("/chaos/rate-limit")
def chaos_rate_limit(enabled: bool = True) -> dict[str, Any]:
    STATE["chaos"]["rate_limit"] = enabled
    return {"chaos": STATE["chaos"]}


@app.post("/chaos/drift")
def chaos_drift(enabled: bool = True) -> dict[str, Any]:
    STATE["chaos"]["drift"] = enabled
    return {"chaos": STATE["chaos"]}


@app.get("/rest/platform/v1/tokenContext")
def token_context(response: Response) -> dict[str, Any]:
    if STATE["chaos"]["rate_limit"]:
        response.status_code = 429
        return {"message": "Rate limit exceeded (chaos)", "errorcode": 50200}
    return {"enterprise": {"id": 1}, "organization": {"id": 1}, "user": {"id": 1}}
