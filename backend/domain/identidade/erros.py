"""Erros do contexto Identidade (emenda G01) — traduzidos para problem+json em
`api/v1/autenticacao.py`.

Mapa: CredencialInvalida→401 · ContaBloqueada→401 (DE PROPÓSITO igual ao anterior —
ver abaixo) · SenhaFraca→422 · EmailDuplicado→409 · UsuarioNaoEncontrado→404 ·
SenhaAtualIncorreta→403.

Herdam de `ErroDominio` (domain/campanha/erros.py) para que qualquer router com o
`RotaComErrosDeDominio` do M1 já os traduza em vez de estourar 500.
"""

from domain.campanha.erros import ErroDominio


class CredencialInvalida(ErroDominio):
    """E-mail inexistente, senha errada, conta inativa OU conta bloqueada.

    Um único erro para quatro causas é intencional: qualquer resposta que distinga
    "não existe" de "existe mas a senha está errada" (ou de "existe e está bloqueada")
    transforma o login num ORÁCULO DE EXISTÊNCIA — a mesma classe de fuga que o achado
    22/UAT5 fechou no `os.codigo` unique global. Quem sabe que a conta existe já tem
    metade do trabalho de um ataque dirigido, e aqui a base tem PII real de clientes.
    """


class SenhaFraca(ErroDominio):
    """Senha fora da política mínima (`domain/identidade/senha.validar_politica`).

    `erros` acumula TODAS as violações (padrão do parser §7.1 e do `PolicyInvalida`):
    devolver uma por vez faz o usuário descobrir a regra a tentativa e erro.
    """

    def __init__(self, motivo: str, erros: list[str]) -> None:
        super().__init__(motivo)
        self.erros = erros


class EmailDuplicado(ErroDominio):
    """`usuario.email` é unique POR TENANT (migração 0015) — vide achado 22/UAT5."""


class UsuarioNaoEncontrado(ErroDominio):
    """Usuário inexistente NO TENANT do request (rotas de admin)."""


class SenhaAtualIncorreta(ErroDominio):
    """Troca de senha sem provar posse da senha atual.

    Aqui distinguir é seguro e necessário: quem chega nesta rota já provou identidade
    (sessão autenticada), então não há oráculo a proteger — só a exigência de reprovar
    a posse antes de trocar a credencial (cookie roubado não vira senha nova).
    """
