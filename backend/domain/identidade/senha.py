"""Política e hash de senha (emenda G01) — argon2id via `argon2-cffi`.

Módulo PURO no sentido que importa ao domínio: não toca banco, rede nem FastAPI. A
dependência de `argon2` é uma primitiva de cálculo (como `hashlib`, já usado em
`aprovacao_service`), não um adapter de I/O — por isso vive junto do modelo em vez de
atrás de uma porta: trocar de algoritmo NÃO é uma decisão de infraestrutura que o
domínio deva ignorar, é uma regra de segurança do próprio agregado.

Três invariantes que este módulo existe para garantir:

1. **Senha em claro morre aqui.** Nenhuma função devolve, guarda ou formata a senha; o
   hash tampouco vira `repr`/log em lugar nenhum (§10.2 — a mesma disciplina que o C02
   impôs à PII no prompt e no ledger).
2. **Tempo de resposta não conta segredo.** `verificar` sempre paga o custo do argon2, e
   `consumir_tempo_de_verificacao` existe para o caminho "e-mail não existe": sem ele o
   login responde rápido para usuário inexistente e devagar para senha errada, e o
   atacante enumera a base por CRONÔMETRO mesmo com as duas respostas idênticas.
3. **Reparametrizar não invalida ninguém.** `precisa_rehash` compara o hash gravado com
   os parâmetros CORRENTES; subir custo (memória/tempo) migra cada conta no próximo
   login bem-sucedido, sem reset em massa.
"""

from __future__ import annotations

import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from argon2.low_level import Type

# Parâmetros argon2id. Defaults correntes do argon2-cffi (RFC 9106 "second recommended":
# 64 MiB, 3 passes) — explicitados aqui porque são política, não detalhe: quem os subir
# deve saber que `precisa_rehash` fará a migração acontecer sozinha, login a login.
_HASHER = PasswordHasher(
    time_cost=3,
    memory_cost=65536,  # 64 MiB
    parallelism=4,
    hash_len=32,
    salt_len=16,
    type=Type.ID,  # argon2id — híbrido resistente a GPU e a side-channel
)

COMPRIMENTO_MINIMO = 12
# Teto contra DoS: argon2 é memory-hard DE PROPÓSITO; sem limite superior um POST com
# 10 MB de "senha" vira trabalho pesado no servidor a custo zero para o atacante.
COMPRIMENTO_MAXIMO = 128

# Hash descartável usado só para equalizar o tempo do caminho "usuário inexistente".
# A senha de origem é aleatória e some do escopo na mesma expressão — ninguém autentica
# com ela nem por acidente nem por vazamento de constante no repositório.
_HASH_ISCA = _HASHER.hash(secrets.token_urlsafe(32))


def validar_politica(senha: str, *, email: str) -> list[str]:
    """Erros ACUMULADOS da política mínima (lista vazia = senha aceita).

    Deliberadamente curta e sem regra de "1 maiúscula + 1 símbolo": composição forçada
    empurra o usuário para `Senha@2026` e não compra entropia. O que compra é
    comprimento e não ser derivada do próprio login.
    """
    erros: list[str] = []
    if len(senha) < COMPRIMENTO_MINIMO:
        erros.append(f"A senha precisa de pelo menos {COMPRIMENTO_MINIMO} caracteres.")
    if len(senha) > COMPRIMENTO_MAXIMO:
        erros.append(f"A senha não pode passar de {COMPRIMENTO_MAXIMO} caracteres.")
    if senha != senha.strip():
        erros.append("A senha não pode começar nem terminar com espaço.")

    login = email.strip().lower()
    parte_local = login.partition("@")[0]
    minuscula = senha.strip().lower()
    if minuscula and login and minuscula == login:
        erros.append("A senha não pode ser igual ao e-mail/login.")
    elif minuscula and parte_local and minuscula == parte_local:
        erros.append("A senha não pode ser igual ao seu identificador de login.")

    if senha and len(set(senha)) == 1:
        erros.append("A senha não pode ser um único caractere repetido.")
    return erros


def gerar_hash(senha: str) -> str:
    """Hash argon2id (o salt vai embutido na string PHC `$argon2id$v=19$...`)."""
    return _HASHER.hash(senha)


def verificar(senha_hash: str, senha: str) -> bool:
    """True se a senha corresponde ao hash. Não levanta: qualquer falha é `False`.

    Engolir `InvalidHashError` é intencional — conta com `senha_hash` corrompido ou
    vazio (linha legada do `usuario` decorativo pré-G01) NÃO pode virar 500 na rota de
    login, o que seria, de novo, um oráculo: 500 aqui e 401 ali distinguem contas.
    """
    try:
        return _HASHER.verify(senha_hash, senha)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def consumir_tempo_de_verificacao() -> None:
    """Paga o custo de um argon2 sem ter contra o que verificar (usuário inexistente).

    Chamado pelo serviço de identidade no caminho em que não há conta: as duas respostas
    já são idênticas em corpo e status; esta função as iguala também no relógio.
    """
    verificar(_HASH_ISCA, "senha-que-nunca-confere")


def precisa_rehash(senha_hash: str) -> bool:
    """True quando o hash gravado usa parâmetros mais fracos que os correntes."""
    try:
        return _HASHER.check_needs_rehash(senha_hash)
    except InvalidHashError:
        return True
