"""Handler de erros RFC-7807 (application/problem+json) — convenção de API do SDD §8."""

from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_CONTENT_TYPE = "application/problem+json"


def problem_response(
    status: int,
    title: str,
    detail: Any = None,
    type_: str = "about:blank",
    instance: str | None = None,
    extra: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Monta uma resposta problem+json conforme RFC 7807."""
    body: dict[str, Any] = {"type": type_, "title": title, "status": status}
    if detail is not None:
        body["detail"] = detail
    if instance is not None:
        body["instance"] = instance
    if extra:
        body.update(extra)
    return JSONResponse(body, status_code=status, media_type=PROBLEM_CONTENT_TYPE, headers=headers)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def _http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        try:
            title = HTTPStatus(exc.status_code).phrase
        except ValueError:
            title = "Error"
        return problem_response(
            exc.status_code,
            title,
            detail=exc.detail,
            instance=request.url.path,
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_exception(request: Request, exc: RequestValidationError) -> JSONResponse:
        return problem_response(
            422,
            "Unprocessable Entity",
            detail="Erro de validação do payload/parâmetros.",
            instance=request.url.path,
            extra={"errors": jsonable_encoder(exc.errors())},
        )

    @app.exception_handler(Exception)
    async def _unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
        return problem_response(
            500,
            "Internal Server Error",
            detail="Erro interno inesperado.",
            instance=request.url.path,
        )
