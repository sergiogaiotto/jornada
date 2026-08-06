"""Casos de uso da Identidade (emenda G01) — login, sessão, troca de senha e a
administração de usuários feita DENTRO da aplicação (não há camada de e-mail: o
`SMTP_URL` do §3.1 nunca teve consumidor, então convite por link não é uma opção).

Desenho, e o porquê de cada peça
--------------------------------
· **Sessão em tabela, id opaco no cookie.** O token que viaja no cookie httpOnly é
  aleatório (`secrets.token_urlsafe(32)`); o banco guarda só o sha256 (`Sessao.id`).
  Revogar é escrever `revogada_em` — logout, desativação, reset e troca de senha
  matam o cookie no request seguinte. Um JWT no localStorage não daria nada disso e
  ainda seria legível por qualquer XSS.
· **Login não revela existência.** E-mail inexistente, senha errada, conta inativa e
  conta bloqueada produzem a MESMA `CredencialInvalida` — e o caminho "não existe"
  paga o custo de um argon2 (`consumir_tempo_de_verificacao`) para não se denunciar
  pelo relógio.
· **Bloqueio temporal por tentativas.** N falhas consecutivas → `bloqueado_ate`; o
  relógio vem do `ClockPort` (§2.1), nunca de `datetime.now()` — é o que permite ao
  teste provar o desbloqueio adiantando o relógio, sem `sleep`.
· **Senha provisória + `senha_expirada`.** Toda conta nasce (e todo reset repõe) com
  `senha_expirada=True`: quem criou a conta conhece a senha inicial, logo ela não pode
  valer como credencial permanente. O guard que restringe a navegação nesse estado
  mora em `app.auth.get_current_user` (ver a justificativa lá).
· **Trilha por pessoa.** Cada ato de identidade vira evento no outbox `domain_event`
  (§2.3) com `actor` = o e-mail de quem agiu. A base processa PII real de clientes:
  saber QUEM entrou, quem criou/desativou conta e quando é requisito de Art. 20 LGPD,
  não enfeite. Nenhum evento carrega senha ou hash (§10.2).
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any

from application.ports.clock import ClockPort
from application.ports.repositorio_identidade import RepositorioIdentidade
from domain.campanha.modelos import EventoDominio
from domain.identidade import senha as regras_senha
from domain.identidade.erros import (
    CredencialInvalida,
    EmailDuplicado,
    SenhaAtualIncorreta,
    SenhaFraca,
    UsuarioNaoEncontrado,
)
from domain.identidade.modelos import (
    PAPEIS,
    ContaUsuario,
    Sessao,
    login_utilizavel,
    normalizar_email,
)

# Mensagem ÚNICA das quatro causas de recusa de login (ver `CredencialInvalida`).
_RECUSA_LOGIN = "E-mail ou senha inválidos."


def hash_token_sessao(token: str) -> str:
    """sha256 hex do token do cookie — a chave primária de `sessao`.

    Mesma disciplina do link mágico do M8 (`aprovacao.token_hash`): o segredo vive no
    cliente, o banco guarda só o resumo. Dump da tabela não reencena sessão nenhuma.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class ServicoIdentidade:
    def __init__(
        self,
        repositorio: RepositorioIdentidade,
        relogio: ClockPort,
        *,
        ttl_horas: int = 12,
        max_tentativas: int = 5,
        bloqueio_minutos: int = 15,
    ) -> None:
        self._repo = repositorio
        self._relogio = relogio
        self._ttl = timedelta(hours=ttl_horas)
        self._max_tentativas = max_tentativas
        self._bloqueio = timedelta(minutes=bloqueio_minutos)

    # ------------------------------------------------------------------ login/sessão
    def autenticar(
        self,
        tenant_id: str,
        *,
        email: str,
        senha: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> tuple[str, ContaUsuario]:
        """Devolve `(token_do_cookie, conta)` — o token existe só aqui e no cookie.

        Levanta `CredencialInvalida` (401) em TODAS as recusas, sem distinguir causa.
        """
        agora = self._relogio.agora()
        conta = self._repo.obter_usuario_por_email(tenant_id, normalizar_email(email))

        if conta is None:
            # Sem conta não há hash a conferir — paga-se o custo mesmo assim para que
            # "não existe" e "senha errada" também levem o MESMO tempo (§10.2).
            regras_senha.consumir_tempo_de_verificacao()
            raise CredencialInvalida(_RECUSA_LOGIN)

        if not conta.pode_autenticar(agora):
            # Inativa ou dentro da janela de bloqueio: nem se dá ao trabalho de conferir
            # a senha (e a resposta continua indistinguível das demais).
            regras_senha.consumir_tempo_de_verificacao()
            raise CredencialInvalida(_RECUSA_LOGIN)

        if not regras_senha.verificar(conta.senha_hash, senha):
            self._registrar_falha(conta, agora)
            raise CredencialInvalida(_RECUSA_LOGIN)

        # Acerto: zera a contagem, solta bloqueio residual e migra o hash se os
        # parâmetros do argon2 subiram desde o último login (§ senha.precisa_rehash).
        conta.tentativas_falhas = 0
        conta.bloqueado_ate = None
        conta.ultimo_acesso = agora
        if regras_senha.precisa_rehash(conta.senha_hash):
            conta.senha_hash = regras_senha.gerar_hash(senha)
        self._repo.salvar_usuario(conta)

        token = self.abrir_sessao(conta, ip=ip, user_agent=user_agent)
        self._evento(
            conta.tenant_id, "usuario.logged_in", conta.email, {"usuario_id": str(conta.id)}
        )
        return token, conta

    def abrir_sessao(
        self, conta: ContaUsuario, *, ip: str | None = None, user_agent: str | None = None
    ) -> str:
        """Cria a linha de `sessao` e devolve o token que vai para o cookie.

        Público porque a troca de senha ROTACIONA a sessão (revoga todas e abre uma
        nova): manter o mesmo id depois de trocar a credencial deixaria de pé um cookie
        que já circulou — a defesa clássica contra fixação de sessão é justamente
        emitir identificador novo em toda mudança de estado de autenticação.
        """
        agora = self._relogio.agora()
        token = secrets.token_urlsafe(32)
        self._repo.adicionar_sessao(
            Sessao(
                id=hash_token_sessao(token),
                usuario_id=conta.id,
                criada_em=agora,
                expira_em=agora + self._ttl,
                ip=ip,
                user_agent=user_agent,
            )
        )
        return token

    def revogar_sessoes(self, conta: ContaUsuario) -> int:
        """Mata todas as sessões vivas da conta; devolve quantas."""
        return self._repo.revogar_sessoes_do_usuario(conta.id, self._relogio.agora())

    def _registrar_falha(self, conta: ContaUsuario, agora: datetime) -> None:
        """Conta a falha e, no limite, bloqueia por tempo (nunca permanentemente).

        Zerar o contador ao bloquear é o que faz a janela ser POR RAJADA: passada a
        punição, a conta volta com o orçamento cheio em vez de bloquear a cada erro.
        """
        conta.tentativas_falhas += 1
        if conta.tentativas_falhas >= self._max_tentativas:
            conta.bloqueado_ate = agora + self._bloqueio
            conta.tentativas_falhas = 0
            self._evento(
                conta.tenant_id,
                "usuario.locked_out",
                conta.email,
                {"usuario_id": str(conta.id), "ate": conta.bloqueado_ate.isoformat()},
            )
        self._repo.salvar_usuario(conta)

    def resolver_sessao(self, token: str) -> ContaUsuario | None:
        """Cookie → conta, ou `None` se a sessão não vale mais.

        `None` cobre tudo que impede autenticar: sessão inexistente, expirada, revogada,
        usuário sumido ou desativado DEPOIS do login. É a checagem por request que
        transforma "desativar usuário" em efeito imediato, e não em promessa.
        """
        agora = self._relogio.agora()
        sessao = self._repo.obter_sessao(hash_token_sessao(token))
        if sessao is None or not sessao.valida(agora):
            return None
        conta = self._repo.obter_usuario(sessao.usuario_id)
        if conta is None or not conta.ativo:
            return None
        return conta

    def encerrar_sessao(self, token: str) -> bool:
        """Logout — idempotente: sessão desconhecida/já revogada devolve False sem erro
        (a rota responde 204 de qualquer jeito; logout que falha é logout que não fecha)."""
        agora = self._relogio.agora()
        sessao = self._repo.obter_sessao(hash_token_sessao(token))
        if sessao is None or sessao.revogada_em is not None:
            return False
        sessao.revogada_em = agora
        self._repo.salvar_sessao(sessao)
        conta = self._repo.obter_usuario(sessao.usuario_id)
        if conta is not None:
            self._evento(
                conta.tenant_id, "usuario.logged_out", conta.email, {"usuario_id": str(conta.id)}
            )
        return True

    # -------------------------------------------------------------------- senha
    def trocar_senha(self, conta: ContaUsuario, *, senha_atual: str, senha_nova: str) -> None:
        """Exige a senha ATUAL, recusa repetir a mesma, aplica a política e limpa
        `senha_expirada`.

        A ROTAÇÃO das sessões é do chamador (`api/v1/autenticacao.trocar_senha`), que
        revoga todas e emite um id novo: se a troca aconteceu porque a senha vazou,
        deixar cookies antigos vivos anularia o motivo da troca.

        Por que `senha_nova == senha_atual` é RECUSADA (auditoria da frente 1)
        --------------------------------------------------------------------
        Sem esta recusa a senha provisória sobrevivia à própria troca. O invariante que
        `criar_usuario`/`resetar_senha` escrevem — "quem cria conhece a senha inicial,
        logo ela vale para UM acesso e morre na primeira troca" — era contornável com o
        gesto mais óbvio possível: `senha_atual = senha_nova = provisória`. A conta saía
        de `senha_expirada`, ganhava navegação plena, e o admin que criou (ou resetou)
        ficava com uma credencial PERMANENTE e válida da conta alheia — exatamente a
        posse que a flag existe para impedir, e que a trilha por pessoa (Art. 20 LGPD)
        pressupõe não existir: um acesso do admin ficaria indistinguível do titular.

        A checagem só cabe AQUI, e não em `_aplicar_senha`: nesta rota quem chama já
        provou a senha atual, então comparar contra ela não conta nada que o chamador já
        não saiba. No `resetar_senha` do admin a mesma comparação seria um oráculo — diria
        ao admin se o provisório que ele escolheu por acaso é a senha real do usuário.
        """
        if not regras_senha.verificar(conta.senha_hash, senha_atual):
            raise SenhaAtualIncorreta("Senha atual incorreta.")
        if regras_senha.verificar(conta.senha_hash, senha_nova):
            raise SenhaFraca(
                "A senha nova precisa ser diferente da atual.",
                ["Escolha uma senha diferente da que está em uso (a provisória não vale)."],
            )
        self._aplicar_senha(conta, senha_nova, expirada=False)
        self._evento(
            conta.tenant_id, "usuario.password_changed", conta.email, {"usuario_id": str(conta.id)}
        )

    def _aplicar_senha(self, conta: ContaUsuario, senha_nova: str, *, expirada: bool) -> None:
        erros = regras_senha.validar_politica(senha_nova, email=conta.email)
        if erros:
            raise SenhaFraca(f"Senha fora da política mínima — {len(erros)} problema(s).", erros)
        conta.senha_hash = regras_senha.gerar_hash(senha_nova)
        conta.senha_expirada = expirada
        conta.tentativas_falhas = 0
        conta.bloqueado_ate = None
        self._repo.salvar_usuario(conta)

    # ------------------------------------------------------------- admin de usuários
    def criar_usuario(
        self,
        tenant_id: str,
        *,
        email: str,
        nome: str,
        papeis: list[str],
        senha_provisoria: str,
        criado_por: uuid.UUID,
        ator: str,
    ) -> ContaUsuario:
        """Criação PELA APLICAÇÃO (root/admin), com senha provisória já expirada.

        `senha_expirada=True` não é detalhe: quem cria conhece a senha inicial, então
        ela vale para UM acesso e morre na primeira troca. Sem isso o admin ficaria
        com credencial permanente de todo mundo — e a trilha por pessoa (Art. 20)
        deixaria de significar alguma coisa.
        """
        login = normalizar_email(email)
        if not login_utilizavel(login):
            raise SenhaFraca(
                "E-mail/login obrigatório e sem espaços.",
                ["Informe o e-mail (login) do usuário, sem espaços no meio."],
            )
        desconhecidos = sorted(set(papeis) - set(PAPEIS))
        if desconhecidos:
            raise SenhaFraca(
                "Papel desconhecido (§8-M0).",
                [f"Papel inexistente: {p}" for p in desconhecidos],
            )
        if self._repo.obter_usuario_por_email(tenant_id, login) is not None:
            raise EmailDuplicado(f"Já existe usuário com o login {login} neste tenant.")

        agora = self._relogio.agora()
        conta = ContaUsuario(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            email=login,
            nome=nome.strip() or login,
            senha_hash="",  # preenchido por `_aplicar_senha` (que valida a política antes)
            papeis=list(papeis),
            ativo=True,
            senha_expirada=True,
            criado_em=agora,
            criado_por=criado_por,
        )
        self._aplicar_senha(conta, senha_provisoria, expirada=True)
        self._repo.adicionar_usuario(conta)
        self._evento(
            tenant_id,
            "usuario.created",
            ator,
            {"usuario_id": str(conta.id), "email": login, "papeis": list(papeis)},
        )
        return conta

    def listar_usuarios(self, tenant_id: str) -> list[ContaUsuario]:
        return self._repo.listar_usuarios(tenant_id)

    def desativar_usuario(
        self, tenant_id: str, usuario_id: uuid.UUID, *, ator: str
    ) -> ContaUsuario:
        """Desativa e REVOGA as sessões — sem a revogação o cookie vivo continuaria
        entrando até expirar, e "desativar" seria só uma anotação."""
        conta = self._conta_do_tenant(tenant_id, usuario_id)
        agora = self._relogio.agora()
        conta.ativo = False
        self._repo.salvar_usuario(conta)
        revogadas = self._repo.revogar_sessoes_do_usuario(conta.id, agora)
        self._evento(
            tenant_id,
            "usuario.deactivated",
            ator,
            {"usuario_id": str(conta.id), "sessoes_revogadas": revogadas},
        )
        return conta

    def resetar_senha(
        self, tenant_id: str, usuario_id: uuid.UUID, *, senha_provisoria: str, ator: str
    ) -> ContaUsuario:
        """Reset pelo admin: senha provisória, `senha_expirada=True`, sessões revogadas
        e bloqueio limpo (é também o caminho de destravar quem estourou as tentativas)."""
        conta = self._conta_do_tenant(tenant_id, usuario_id)
        self._aplicar_senha(conta, senha_provisoria, expirada=True)
        revogadas = self._repo.revogar_sessoes_do_usuario(conta.id, self._relogio.agora())
        self._evento(
            tenant_id,
            "usuario.password_reset",
            ator,
            {"usuario_id": str(conta.id), "sessoes_revogadas": revogadas},
        )
        return conta

    def _conta_do_tenant(self, tenant_id: str, usuario_id: uuid.UUID) -> ContaUsuario:
        conta = self._repo.obter_usuario(usuario_id)
        if conta is None or conta.tenant_id != tenant_id:
            # Conta de OUTRO tenant responde igual a inexistente (isolamento §8).
            raise UsuarioNaoEncontrado("Usuário não encontrado neste tenant.")
        return conta

    # --------------------------------------------------------------- bootstrap root
    def semear_root(
        self, tenant_id: str, *, email: str, senha: str, nome: str = "Root"
    ) -> ContaUsuario | None:
        """Cria o root se (e só se) ele ainda não existir. IDEMPOTENTE.

        Rodar de novo com a variável ainda no ambiente NÃO reseta a senha de quem já
        trocou — é o requisito que separa "bootstrap" de "backdoor de recuperação":
        um `JORNADA_ROOT_SENHA` esquecido no compose não pode ser um caminho de volta
        para dentro da conta mais poderosa do sistema a cada restart.

        Devolve a conta criada, ou `None` quando já existia (nada foi tocado).

        Login MALFORMADO também devolve `None` (sem criar nada): `JORNADA_ROOT_EMAIL` vem
        de variável de ambiente, e um `.env` mal formado entrega frase no lugar do login.
        Não semear é a falha certa aqui — o operador percebe que não há root e conserta;
        semear com o que veio criaria um admin com credencial que ele não escolheu.
        """
        login = normalizar_email(email)
        if not login_utilizavel(login) or not senha:
            return None
        if self._repo.obter_usuario_por_email(tenant_id, login) is not None:
            return None

        erros = regras_senha.validar_politica(senha, email=login)
        if erros:
            # Falha ALTA e explícita: root com senha fraca é pior que root ausente.
            raise SenhaFraca(
                "JORNADA_ROOT_SENHA fora da política mínima — o root NÃO foi criado.", erros
            )

        agora = self._relogio.agora()
        conta = ContaUsuario(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            email=login,
            nome=nome,
            senha_hash=regras_senha.gerar_hash(senha),
            papeis=["admin"],
            ativo=True,
            senha_expirada=True,  # troca obrigatória no 1º acesso
            criado_em=agora,
            criado_por=None,  # bootstrap: não há criador humano
        )
        self._repo.adicionar_usuario(conta)
        self._evento(
            tenant_id, "usuario.created", "bootstrap", {"usuario_id": str(conta.id), "root": True}
        )
        return conta

    # ------------------------------------------------------------------------ outbox
    def _evento(self, tenant_id: str, tipo: str, ator: str, payload: dict[str, Any]) -> None:
        """Trilha no outbox `domain_event` (§2.3). NUNCA carrega senha nem hash.

        `adicionar_evento` é oferecido pela mesma instância de repositório (tipagem
        estrutural §2.1); o `getattr` protege repositórios de teste que implementem só
        as portas de identidade.
        """
        adicionar = getattr(self._repo, "adicionar_evento", None)
        if adicionar is None:
            return
        adicionar(
            EventoDominio(
                tenant_id=tenant_id,
                type=tipo,
                payload=payload,
                actor=ator,
                via_ai=False,
                created_at=self._relogio.agora(),
            )
        )
