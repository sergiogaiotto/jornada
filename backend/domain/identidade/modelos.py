"""Entidades do contexto Identidade (emenda G01) — espelham `usuario` e `sessao` (§4.1
+ migração 0015), sem I/O.

`usuario` já existia no DDL §4.1 (id, tenant_id, nome, email, papeis) como tabela
DECORATIVA: nada escrevia nela porque a identidade era o token estático `dev-<papel>`.
A emenda G01 dá corpo a ela (senha_hash, ativo, senha_expirada, trilha de bloqueio) e
acrescenta `sessao` — a tabela que torna o logout/bloqueio REVOGÁVEIS de verdade.

Por que `papeis` continua `text[]` e não vira tabela de junção
--------------------------------------------------------------
O conjunto de papéis é FECHADO e pequeno (`PAPEIS`, 6 valores validados em código por
`require_role`), a atribuição não tem atributo nenhum (sem validade, sem escopo, sem
quem concedeu) e o RBAC precisa do vetor inteiro em TODA requisição autenticada. Uma
tabela de junção custaria um join por request para comprar: (a) integridade referencial
contra uma tabela `papel` que não existe — o conjunto vive no Python, não no banco; e
(b) a busca reversa "quem tem o papel X", que nenhuma tela pede. Fica `text[]`, como o
DDL §4.1 já escreveu; se um dia o papel ganhar atributos (delegação temporária, escopo
por OS) a junção entra com a migração que os introduzir, e a busca reversa, se vier,
sai de um índice GIN sem mudar o modelo.

Por que `sessao.id` é o HASH do que viaja no cookie
--------------------------------------------------
O cookie carrega um segredo aleatório (`secrets.token_urlsafe`); a tabela guarda só o
sha256 dele — mesma disciplina que o link mágico do M8 já aplica (`aprovacao.token_hash`,
"persiste apenas o sha256"). Assim o id é opaco para o cliente E para quem lê o banco:
um dump de `sessao` não permite reencenar sessão nenhuma. É por isso que o campo é
`str` (hex) e não `uuid`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

# Papéis do RBAC (§8-M0). Definidos AQUI (domínio) e reexportados por `app.auth` —
# antes moravam na camada de framework, o que impedia o domínio de validá-los.
PAPEIS: tuple[str, ...] = ("solicitante", "analista", "lider", "aprovador", "dpo", "admin")


def normalizar_email(email: str) -> str:
    """Forma canônica do identificador de login: `strip` + minúsculas.

    É o que entra na coluna e o que o unique `(tenant_id, lower(email))` compara — sem
    isso `Sergio@x` e `sergio@x` seriam duas contas no mesmo tenant. Aceita
    identificador SEM `@` de propósito: o root do projeto é `sergio.gaiotto` (não há
    camada de e-mail no sistema — o campo é o login, não um endereço para envio).
    """
    return email.strip().lower()


def login_utilizavel(login: str) -> bool:
    """O login já normalizado é digitável por um humano?

    Regra mínima: não vazio e SEM espaço interno. Não é cosmética — é o guarda-corpo que
    impede uma configuração malformada de virar conta. `JORNADA_ROOT_EMAIL` chega de
    variável de ambiente, e um `.env` mal formado entrega frases inteiras no lugar do
    login (foi assim que um comentário do `.env.example` virou o login de um admin real:
    o parser de .env não trata `# ...` como comentário quando o valor é vazio). Nenhum
    login legítimo tem espaço no meio; qualquer coisa que tenha é configuração podre, e
    conta com login intypável ainda por cima não teria como ser usada de boa-fé.
    """
    return bool(login) and not any(caractere.isspace() for caractere in login)


@dataclass
class ContaUsuario:
    """Linha da tabela `usuario` (§4.1 + migração 0015).

    Distinta de `app.auth.Usuario`: aquela é o espelho IMUTÁVEL do portador dentro de um
    request (id/tenant/nome/email/papéis); esta é o agregado persistido, com o segredo
    e a trilha por pessoa que o tratamento de PII real exige (§10.2/Art. 20 LGPD).
    `senha_hash` NUNCA sai daqui: não vai para contrato de API, log ou evento.
    """

    id: uuid.UUID
    tenant_id: str
    email: str  # normalizado; unique POR TENANT (migração 0015)
    nome: str
    senha_hash: str
    papeis: list[str] = field(default_factory=list)
    ativo: bool = True
    senha_expirada: bool = False  # True → só auth/eu, auth/trocar-senha e auth/logout
    criado_em: datetime | None = None
    criado_por: uuid.UUID | None = None  # quem criou (root/admin); None = bootstrap
    ultimo_acesso: datetime | None = None
    tentativas_falhas: int = 0
    bloqueado_ate: datetime | None = None

    def bloqueada(self, agora: datetime) -> bool:
        """Bloqueio TEMPORAL por tentativas (não é banimento): expira sozinho."""
        return self.bloqueado_ate is not None and agora < self.bloqueado_ate

    def pode_autenticar(self, agora: datetime) -> bool:
        return self.ativo and not self.bloqueada(agora)


@dataclass
class Sessao:
    """Linha da tabela `sessao` (migração 0015) — o que torna o logout REAL.

    A alternativa descartada foi JWT no localStorage: token assinado não se revoga (só
    expira), e qualquer XSS o lê. Aqui o cookie é httpOnly (JS não alcança) e a validade
    é uma LINHA — logout, desativação de usuário e troca de senha viram `revogada_em`
    preenchido, com efeito no próximo request.
    """

    id: str  # sha256 hex do token que viaja no cookie (o segredo nunca é persistido)
    usuario_id: uuid.UUID
    criada_em: datetime
    expira_em: datetime
    revogada_em: datetime | None = None
    ip: str | None = None
    user_agent: str | None = None

    def valida(self, agora: datetime) -> bool:
        return self.revogada_em is None and agora < self.expira_em
