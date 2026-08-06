"""RepositorioIdentidade — porta de persistência de `usuario` e `sessao` (§2.1, §4.1 +
migração 0015).

Implementada por `RepositorioOsMemoria` e por `RepositorioSql` na MESMA instância das
demais portas (tipagem estrutural §2.1), como todo o resto do projeto.

Nota de contrato: as buscas por e-mail SEMPRE recebem `tenant_id`. Não existe (e não
deve existir) um `obter_usuario_por_email` global — seria o oráculo de existência
cross-tenant que o achado 22/UAT5 fechou no `os.codigo`.
"""

import uuid
from datetime import datetime
from typing import Protocol

from domain.identidade.modelos import ContaUsuario, Sessao


class RepositorioIdentidade(Protocol):
    # --- usuario (§4.1 + migração 0015) ---
    def adicionar_usuario(self, conta: ContaUsuario) -> None:
        """UPSERT por id (mesma semântica do resto do projeto — bootstrap idempotente)."""
        ...

    def salvar_usuario(self, conta: ContaUsuario) -> None: ...

    def obter_usuario(self, usuario_id: uuid.UUID) -> ContaUsuario | None:
        """Sem escopo de tenant: a chave é o id da SESSÃO já autenticada, e o tenant
        efetivo do request é derivado da conta encontrada (nunca do header)."""
        ...

    def obter_usuario_por_email(self, tenant_id: str, email: str) -> ContaUsuario | None:
        """`email` já normalizado (`domain.identidade.modelos.normalizar_email`)."""
        ...

    def listar_usuarios(self, tenant_id: str) -> list[ContaUsuario]: ...

    # --- sessao (migração 0015) ---
    def adicionar_sessao(self, sessao: Sessao) -> None: ...

    def obter_sessao(self, sessao_id: str) -> Sessao | None:
        """`sessao_id` é o sha256 do token do cookie — nunca o token em claro."""
        ...

    def salvar_sessao(self, sessao: Sessao) -> None: ...

    def revogar_sessoes_do_usuario(self, usuario_id: uuid.UUID, agora: datetime) -> int:
        """Revoga TODAS as sessões vivas da conta; devolve quantas. É o que dá efeito
        imediato a desativar usuário, resetar e trocar senha (o cookie antigo morre)."""
        ...
