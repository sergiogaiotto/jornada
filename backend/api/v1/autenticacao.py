"""Rotas de `/api/v1/auth` (emenda G01) — tag OpenAPI `auth`.

`POST /auth/login` (e-mail + senha → sessão + cookie httpOnly) · `POST /auth/logout`
(revoga a sessão) · `GET /auth/eu` (quem sou: nome, papéis, tenant, senha_expirada) ·
`POST /auth/trocar-senha` (exige a senha atual; limpa `senha_expirada` e ROTACIONA a
sessão) · administração pelo root/admin: `POST/GET /auth/usuarios`,
`POST /auth/usuarios/{id}/desativar`, `POST /auth/usuarios/{id}/resetar-senha`.

Decisões visíveis no contrato:

· **Cookie, não corpo.** O token de sessão sai daqui só como `Set-Cookie` httpOnly:
  se ele aparecesse no JSON, a SPA teria de guardá-lo em algum lugar que o JavaScript
  lê — e aí qualquer XSS o leva junto. `SameSite=Lax` corta CSRF nas requisições
  cross-site que importam; `Secure` vem de `SESSION_COOKIE_SECURE` porque hoje a
  aplicação roda em HTTP puro e um cookie Secure simplesmente não seria enviado.
· **`X-Tenant` também no login.** O `email` é unique POR TENANT, então o tenant faz
  parte da chave de busca. O contrato §8-M0-A2 (header obrigatório em `/api/v1/*`)
  fica intacto — nenhuma rota de auth é pública, ao contrário do link mágico do C03.
· **Erros RFC-7807 em tudo**, e login errado NUNCA revela se o e-mail existe (uma só
  `CredencialInvalida` para inexistente/senha errada/inativa/bloqueada — ver
  `domain/identidade/erros.py`).
"""

import uuid
from collections.abc import Callable, Coroutine
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field

from app.auth import (
    Usuario,
    get_current_user,
    nome_cookie_sessao,
    require_role,
    servico_identidade,
)
from app.config import get_settings
from app.errors import problem_response
from application.services.identidade_service import ServicoIdentidade
from domain.campanha.erros import ErroDominio
from domain.identidade.erros import (
    CredencialInvalida,
    EmailDuplicado,
    SenhaAtualIncorreta,
    SenhaFraca,
    UsuarioNaoEncontrado,
)
from domain.identidade.modelos import PAPEIS, ContaUsuario

# ----------------------------------------------------------- Erros → problem+json
_STATUS_POR_ERRO: tuple[tuple[type[ErroDominio], int], ...] = (
    (CredencialInvalida, 401),
    (SenhaAtualIncorreta, 403),
    (SenhaFraca, 422),
    (EmailDuplicado, 409),
    (UsuarioNaoEncontrado, 404),
)


class RotaAutenticacao(APIRoute):
    """Traduz os erros de identidade no próprio router (padrão M1/M4/M12)."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler_original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await handler_original(request)
            except ErroDominio as exc:
                status = next((s for t, s in _STATUS_POR_ERRO if isinstance(exc, t)), 500)
                extra: dict[str, Any] | None = None
                if isinstance(exc, SenhaFraca):  # todas as violações de uma vez
                    extra = {"erros": exc.erros}
                cabecalhos = (
                    {"WWW-Authenticate": "Bearer"} if isinstance(exc, CredencialInvalida) else None
                )
                return problem_response(
                    status,
                    _TITULO[status],
                    detail=exc.motivo,
                    instance=request.url.path,
                    extra=extra,
                    headers=cabecalhos,
                )

        return handler


_TITULO: dict[int, str] = {
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    409: "Conflict",
    422: "Unprocessable Entity",
    500: "Internal Server Error",
}


# ------------------------------------------------------------------ Dependências
def get_servico_identidade(request: Request) -> ServicoIdentidade:
    """Serviço de identidade COM o bootstrap do root garantido na primeira passagem.

    O bootstrap vive aqui (e não no startup do `app/main.py`) pelo mesmo motivo e no
    mesmo formato que `get_repositorio_plataforma` semeia roster/políticas: é
    idempotente, custa uma leitura por processo e acontece exatamente quando faz falta
    — ninguém precisa do root antes de alguém tentar entrar. A EMENDA propõe promovê-lo
    ao startup quando `app/main.py` for tocado.

    Quem garante que rodar de novo não repõe a senha antiga é `semear_root` (ele desiste
    se a conta já existe), NÃO esta flag: a flag só evita uma leitura por request. A
    auditoria da frente 1 removeu daqui um `settings.jornada_root_senha = SecretStr("")`
    que se anunciava como higiene de segredo e era duas coisas piores:

    1. **Não apagava nada.** O `Settings` é lido de `os.environ`, e a variável continua
       lá pelo processo inteiro — qualquer `Settings()` novo relê o mesmo valor em claro.
       O que de fato protege repr/log/traceback é o `SecretStr` (§3.1), e esse fica.
    2. **Quebrava o bootstrap.** A escrita atingia o objeto do `lru_cache`, que é global
       ao PROCESSO, enquanto `_root_semeado` é do APP: um segundo `create_app()` no mesmo
       processo nascia sem root e sem erro nenhum — falha silenciosa na conta mais
       poderosa do sistema (provado em `test_bootstrap_semeia_em_todo_app_do_processo`).
    """
    servico = servico_identidade(request)
    if not getattr(request.app.state, "_root_semeado", False):
        settings = get_settings()
        senha = settings.jornada_root_senha.get_secret_value()
        if settings.jornada_root_email and senha:
            servico.semear_root(
                settings.default_tenant, email=settings.jornada_root_email, senha=senha
            )
        del senha  # some do escopo local; o SecretStr do Settings nunca vira repr/log
        request.app.state._root_semeado = True
    return servico


def get_tenant(request: Request) -> str:
    return request.state.tenant_id  # garantido pelo middleware X-Tenant (app/main.py, §8)


Servico = Annotated[ServicoIdentidade, Depends(get_servico_identidade)]
Tenant = Annotated[str, Depends(get_tenant)]
Autenticado = Annotated[Usuario, Depends(get_current_user)]
Admin = Annotated[Usuario, Depends(require_role("admin"))]


# ------------------------------------------------- Contratos Pydantic (§1.3.2, §4.1)
class LoginEntrada(BaseModel):
    email: str = Field(min_length=1, max_length=320)
    # `max_length` casa com o teto da política (§ senha.COMPRIMENTO_MAXIMO): rejeitar
    # no contrato evita que um corpo gigante chegue ao argon2 (memory-hard de propósito).
    senha: str = Field(min_length=1, max_length=128)


class TrocaSenha(BaseModel):
    senha_atual: str = Field(min_length=1, max_length=128)
    senha_nova: str = Field(min_length=1, max_length=128)


class UsuarioCriar(BaseModel):
    email: str = Field(min_length=1, max_length=320)
    nome: str = Field(min_length=1, max_length=200)
    papeis: list[str] = Field(min_length=1)
    senha_provisoria: str = Field(min_length=1, max_length=128)


class SenhaProvisoria(BaseModel):
    senha_provisoria: str = Field(min_length=1, max_length=128)


class EuOut(BaseModel):
    """Quem sou. NUNCA carrega `senha_hash` — nem para o próprio dono da conta."""

    id: uuid.UUID
    tenant_id: str
    email: str
    nome: str
    papeis: list[str]
    senha_expirada: bool


class UsuarioOut(EuOut):
    """Listagem/administração: acrescenta a trilha operacional, sem segredo algum."""

    ativo: bool
    criado_em: datetime | None
    criado_por: uuid.UUID | None
    ultimo_acesso: datetime | None
    bloqueado_ate: datetime | None


def _usuario_out(conta: ContaUsuario) -> UsuarioOut:
    return UsuarioOut(
        id=conta.id,
        tenant_id=conta.tenant_id,
        email=conta.email,
        nome=conta.nome,
        papeis=list(conta.papeis),
        senha_expirada=conta.senha_expirada,
        ativo=conta.ativo,
        criado_em=conta.criado_em,
        criado_por=conta.criado_por,
        ultimo_acesso=conta.ultimo_acesso,
        bloqueado_ate=conta.bloqueado_ate,
    )


def _gravar_cookie(resposta: Response, token: str) -> None:
    """`Set-Cookie` da sessão: httpOnly + SameSite=Lax + Secure por configuração.

    `max_age` acompanha o TTL da linha em `sessao` só por higiene do navegador — quem
    manda é a tabela: cookie sobrevivente a uma revogação não autentica nada.
    """
    settings = get_settings()
    resposta.set_cookie(
        key=settings.session_cookie_nome,
        value=token,
        max_age=settings.session_ttl_horas * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure,
        path="/",
    )


# ------------------------------------------------------------------------- Rotas
router = APIRouter(route_class=RotaAutenticacao, tags=["auth"])


@router.post("/auth/login", response_model=EuOut)
async def login(
    payload: LoginEntrada, request: Request, resposta: Response, tenant: Tenant, servico: Servico
) -> EuOut:
    """E-mail + senha → sessão (cookie httpOnly). Recusa SEMPRE 401 com o mesmo corpo.

    `ip`/`user_agent` entram na linha de `sessao` para a trilha por pessoa que o
    tratamento de PII real exige (§10.2) — não são usados para decidir acesso.
    """
    token, conta = servico.autenticar(
        tenant,
        email=payload.email,
        senha=payload.senha,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    _gravar_cookie(resposta, token)
    return EuOut(
        id=conta.id,
        tenant_id=conta.tenant_id,
        email=conta.email,
        nome=conta.nome,
        papeis=list(conta.papeis),
        senha_expirada=conta.senha_expirada,
    )


@router.post("/auth/logout", status_code=204)
async def logout(request: Request, servico: Servico) -> Response:
    """Revoga a sessão e apaga o cookie. Idempotente: sem cookie também responde 204.

    Não exige `get_current_user` de propósito — logout de sessão já expirada tem de
    limpar o cookie do navegador, e um 401 aqui deixaria o usuário preso na tela.
    """
    token = request.cookies.get(nome_cookie_sessao())
    if token:
        servico.encerrar_sessao(token)
    resposta = Response(status_code=204)
    resposta.delete_cookie(key=nome_cookie_sessao(), path="/")
    return resposta


@router.get("/auth/eu", response_model=EuOut)
async def eu(usuario: Autenticado) -> EuOut:
    """Quem sou. É por aqui que a SPA descobre `senha_expirada` e redireciona à troca
    — rota liberada mesmo com a senha expirada (`ROTAS_SEM_SENHA_VALIDA`)."""
    return EuOut(
        id=usuario.id,
        tenant_id=usuario.tenant_id,
        email=usuario.email,
        nome=usuario.nome,
        papeis=list(usuario.papeis),
        senha_expirada=usuario.senha_expirada,
    )


@router.post("/auth/trocar-senha", response_model=EuOut)
async def trocar_senha(
    payload: TrocaSenha,
    request: Request,
    resposta: Response,
    usuario: Autenticado,
    servico: Servico,
) -> EuOut:
    """Exige a senha ATUAL, aplica a política, limpa `senha_expirada` e rotaciona a sessão.

    A rotação revoga TODAS as sessões (inclusive a de quem está trocando) e emite uma
    nova: se a troca aconteceu porque a senha vazou, deixar os cookies antigos vivos
    anularia o motivo da troca. Quem trocou continua logado — com id de sessão novo.
    """
    conta = servico.resolver_sessao(request.cookies.get(nome_cookie_sessao(), ""))
    if conta is None:  # portador Bearer de dev não tem senha para trocar
        raise SenhaAtualIncorreta("Troca de senha exige sessão de usuário (login com senha).")
    servico.trocar_senha(conta, senha_atual=payload.senha_atual, senha_nova=payload.senha_nova)
    servico.revogar_sessoes(conta)
    _gravar_cookie(
        resposta,
        servico.abrir_sessao(
            conta,
            ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        ),
    )
    return EuOut(
        id=conta.id,
        tenant_id=conta.tenant_id,
        email=conta.email,
        nome=conta.nome,
        papeis=list(conta.papeis),
        senha_expirada=conta.senha_expirada,
    )


@router.post("/auth/usuarios", status_code=201, response_model=UsuarioOut)
async def criar_usuario(
    payload: UsuarioCriar, tenant: Tenant, servico: Servico, admin: Admin
) -> UsuarioOut:
    """Criação PELA APLICAÇÃO (não há e-mail de convite — o `SMTP_URL` do §3.1 nunca
    teve consumidor). A conta nasce com senha provisória e `senha_expirada=True`."""
    conta = servico.criar_usuario(
        tenant,
        email=payload.email,
        nome=payload.nome,
        papeis=payload.papeis,
        senha_provisoria=payload.senha_provisoria,
        criado_por=admin.id,
        ator=admin.email,
    )
    return _usuario_out(conta)


@router.get("/auth/usuarios", response_model=list[UsuarioOut])
async def listar_usuarios(tenant: Tenant, servico: Servico, _admin: Admin) -> list[UsuarioOut]:
    return [_usuario_out(c) for c in servico.listar_usuarios(tenant)]


@router.post("/auth/usuarios/{usuario_id}/desativar", response_model=UsuarioOut)
async def desativar_usuario(
    usuario_id: uuid.UUID, tenant: Tenant, servico: Servico, admin: Admin
) -> UsuarioOut:
    """Desativa e revoga as sessões — efeito no request seguinte, não na expiração."""
    return _usuario_out(servico.desativar_usuario(tenant, usuario_id, ator=admin.email))


@router.post("/auth/usuarios/{usuario_id}/resetar-senha", response_model=UsuarioOut)
async def resetar_senha(
    usuario_id: uuid.UUID,
    payload: SenhaProvisoria,
    tenant: Tenant,
    servico: Servico,
    admin: Admin,
) -> UsuarioOut:
    """Senha provisória nova + `senha_expirada=True` + sessões revogadas. É também o
    caminho de destravar quem estourou as tentativas antes da janela vencer."""
    return _usuario_out(
        servico.resetar_senha(
            tenant, usuario_id, senha_provisoria=payload.senha_provisoria, ator=admin.email
        )
    )


@router.get("/auth/papeis", response_model=list[str])
async def listar_papeis(_usuario: Autenticado) -> list[str]:
    """Conjunto FECHADO de papéis (§8-M0) — a tela de criação de usuário lê daqui em
    vez de duplicar a lista no front (o mesmo raciocínio do guia do M-Guia)."""
    return list(PAPEIS)
