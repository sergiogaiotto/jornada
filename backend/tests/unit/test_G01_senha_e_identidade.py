"""Unit — política/hash de senha e o serviço de identidade (emenda G01).

Nível de serviço (sem HTTP): o que se prova aqui é o comportamento que NENHUMA rota
pode desfazer — bloqueio temporal pelo ClockPort, idempotência do bootstrap do root e
unicidade de e-mail POR TENANT.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from adapters.persistence.memoria import RepositorioOsMemoria
from application.services.identidade_service import ServicoIdentidade
from domain.identidade import senha as regras_senha
from domain.identidade.erros import (
    CredencialInvalida,
    EmailDuplicado,
    SenhaAtualIncorreta,
    SenhaFraca,
)
from domain.identidade.modelos import normalizar_email

INICIO = datetime(2026, 8, 6, 12, 0, 0, tzinfo=UTC)
SENHA_BOA = "correta-cavalo-bateria"
SENHA_NOVA = "outra-frase-bem-longa"
TENANT = "torre-movel"


class _RelogioFixo:
    """ClockPort (§2.1) manipulável — o bloqueio expira por AVANÇO, nunca por sleep."""

    def __init__(self, instante: datetime) -> None:
        self.instante = instante

    def agora(self) -> datetime:
        return self.instante

    def avancar(self, delta: timedelta) -> None:
        self.instante += delta


@pytest.fixture()
def relogio() -> _RelogioFixo:
    return _RelogioFixo(INICIO)


@pytest.fixture()
def repo() -> RepositorioOsMemoria:
    return RepositorioOsMemoria()


@pytest.fixture()
def servico(repo: RepositorioOsMemoria, relogio: _RelogioFixo) -> ServicoIdentidade:
    return ServicoIdentidade(repo, relogio, ttl_horas=12, max_tentativas=3, bloqueio_minutos=15)


def _conta_pronta(servico: ServicoIdentidade, email: str = "ana@torre.local") -> None:
    """Cria a conta e já troca a senha provisória (sai de `senha_expirada`)."""
    conta = servico.criar_usuario(
        TENANT,
        email=email,
        nome="Ana",
        papeis=["analista"],
        senha_provisoria="provisoria-longa-01",
        criado_por=uuid.uuid4(),
        ator="root@torre.local",
    )
    servico.trocar_senha(conta, senha_atual="provisoria-longa-01", senha_nova=SENHA_BOA)


# ------------------------------------------------------------------ política/hash
def test_politica_acumula_todos_os_erros() -> None:
    """Erros ACUMULADOS: devolver um por vez faria o usuário descobrir a regra por
    tentativa e erro (mesmo padrão do parser §7.1 e do PolicyInvalida)."""
    erros = regras_senha.validar_politica("aaa", email="aaa")
    assert len(erros) >= 2  # curta demais E caractere único repetido


def test_politica_recusa_senha_igual_ao_login() -> None:
    assert regras_senha.validar_politica("ana@torre.local", email="ana@torre.local")
    assert regras_senha.validar_politica("sergio.gaiotto", email="sergio.gaiotto@x.com")


def test_hash_nunca_e_a_senha_e_verifica() -> None:
    hash_ = regras_senha.gerar_hash(SENHA_BOA)
    assert SENHA_BOA not in hash_
    assert hash_.startswith("$argon2id$")  # argon2id, não argon2i/d
    assert regras_senha.verificar(hash_, SENHA_BOA)
    assert not regras_senha.verificar(hash_, SENHA_BOA + "x")


def test_hash_tem_salt_por_conta() -> None:
    """Dois hashes da MESMA senha diferem — sem isso o banco entregaria de graça
    quais contas compartilham senha."""
    assert regras_senha.gerar_hash(SENHA_BOA) != regras_senha.gerar_hash(SENHA_BOA)


def test_hash_invalido_nao_explode() -> None:
    """Linha legada da `usuario` decorativa (pré-G01, `senha_hash` vazio) não pode
    virar 500 no login — 500 aqui e 401 ali já distinguiriam contas."""
    assert regras_senha.verificar("", SENHA_BOA) is False
    assert regras_senha.verificar("lixo", SENHA_BOA) is False


def test_normalizar_email_e_canonico() -> None:
    assert normalizar_email("  Ana@Torre.LOCAL ") == "ana@torre.local"
    assert normalizar_email("Sergio.Gaiotto") == "sergio.gaiotto"  # login sem @ é válido


# ------------------------------------------------------------------------- login
def test_login_ok_abre_sessao(servico: ServicoIdentidade) -> None:
    _conta_pronta(servico)
    token, conta = servico.autenticar(TENANT, email="ANA@torre.local", senha=SENHA_BOA)
    assert servico.resolver_sessao(token) is not None
    assert conta.ultimo_acesso == INICIO


def test_inexistente_e_senha_errada_dao_a_mesma_recusa(servico: ServicoIdentidade) -> None:
    """Oráculo de existência fechado: as duas causas produzem a MESMA mensagem."""
    _conta_pronta(servico)
    with pytest.raises(CredencialInvalida) as inexistente:
        servico.autenticar(TENANT, email="ninguem@torre.local", senha=SENHA_BOA)
    with pytest.raises(CredencialInvalida) as errada:
        servico.autenticar(TENANT, email="ana@torre.local", senha="senha-errada-longa")
    assert inexistente.value.motivo == errada.value.motivo


def test_bloqueio_por_tentativas_e_desbloqueio_pelo_relogio(
    servico: ServicoIdentidade, relogio: _RelogioFixo
) -> None:
    """3 falhas → bloqueio; nem a senha CERTA entra; 15min depois entra."""
    _conta_pronta(servico)
    for _ in range(3):
        with pytest.raises(CredencialInvalida):
            servico.autenticar(TENANT, email="ana@torre.local", senha="errada-mas-longa")

    with pytest.raises(CredencialInvalida):  # senha certa, conta bloqueada
        servico.autenticar(TENANT, email="ana@torre.local", senha=SENHA_BOA)

    relogio.avancar(timedelta(minutes=16))
    token, _ = servico.autenticar(TENANT, email="ana@torre.local", senha=SENHA_BOA)
    assert servico.resolver_sessao(token) is not None


def test_sessao_expira_pelo_relogio(servico: ServicoIdentidade, relogio: _RelogioFixo) -> None:
    _conta_pronta(servico)
    token, _ = servico.autenticar(TENANT, email="ana@torre.local", senha=SENHA_BOA)
    relogio.avancar(timedelta(hours=13))  # TTL = 12h
    assert servico.resolver_sessao(token) is None


def test_sessao_revogada_nao_autentica(servico: ServicoIdentidade) -> None:
    _conta_pronta(servico)
    token, _ = servico.autenticar(TENANT, email="ana@torre.local", senha=SENHA_BOA)
    assert servico.encerrar_sessao(token) is True
    assert servico.resolver_sessao(token) is None
    assert servico.encerrar_sessao(token) is False  # logout é idempotente


def test_desativar_usuario_mata_a_sessao_viva(servico: ServicoIdentidade) -> None:
    """Desativar sem revogar seria só uma anotação: o cookie entraria até expirar."""
    _conta_pronta(servico)
    token, conta = servico.autenticar(TENANT, email="ana@torre.local", senha=SENHA_BOA)
    servico.desativar_usuario(TENANT, conta.id, ator="root@torre.local")
    assert servico.resolver_sessao(token) is None


# ------------------------------------------------------------------- troca de senha
def test_troca_de_senha_limpa_a_flag_e_exige_a_atual(servico: ServicoIdentidade) -> None:
    conta = servico.criar_usuario(
        TENANT,
        email="bruno@torre.local",
        nome="Bruno",
        papeis=["analista"],
        senha_provisoria="provisoria-longa-01",
        criado_por=uuid.uuid4(),
        ator="root@torre.local",
    )
    assert conta.senha_expirada is True

    with pytest.raises(SenhaAtualIncorreta):
        servico.trocar_senha(conta, senha_atual="chute-bem-longo", senha_nova=SENHA_NOVA)

    servico.trocar_senha(conta, senha_atual="provisoria-longa-01", senha_nova=SENHA_NOVA)
    assert conta.senha_expirada is False
    token, _ = servico.autenticar(TENANT, email="bruno@torre.local", senha=SENHA_NOVA)
    assert servico.resolver_sessao(token) is not None


def test_troca_recusa_repetir_a_senha_atual(servico: ServicoIdentidade) -> None:
    """Auditoria da frente 1: a "troca" de provisória por ela MESMA anulava a flag.

    `criar_usuario` promete que a senha que o admin escolheu vale para UM acesso e morre
    na primeira troca. Sem esta recusa a promessa caía no gesto mais óbvio possível
    (`senha_atual = senha_nova = provisória`): a conta saía de `senha_expirada` com
    navegação plena e o admin ficava com credencial PERMANENTE da conta alheia — o que
    torna a trilha por pessoa (Art. 20 LGPD) indistinguível entre titular e criador.
    """
    conta = servico.criar_usuario(
        TENANT,
        email="dani@torre.local",
        nome="Dani",
        papeis=["analista"],
        senha_provisoria="provisoria-longa-01",
        criado_por=uuid.uuid4(),
        ator="root@torre.local",
    )
    with pytest.raises(SenhaFraca):
        servico.trocar_senha(
            conta, senha_atual="provisoria-longa-01", senha_nova="provisoria-longa-01"
        )
    assert conta.senha_expirada is True  # continua presa até trocar DE VERDADE

    servico.trocar_senha(conta, senha_atual="provisoria-longa-01", senha_nova=SENHA_NOVA)
    assert conta.senha_expirada is False


def test_troca_recusa_senha_fora_da_politica(servico: ServicoIdentidade) -> None:
    _conta_pronta(servico)
    conta = servico.listar_usuarios(TENANT)[0]
    with pytest.raises(SenhaFraca) as exc:
        servico.trocar_senha(conta, senha_atual=SENHA_BOA, senha_nova="curta")
    assert exc.value.erros


def test_resetar_senha_reexpira_e_revoga(servico: ServicoIdentidade) -> None:
    _conta_pronta(servico)
    conta = servico.listar_usuarios(TENANT)[0]
    token, _ = servico.autenticar(TENANT, email=conta.email, senha=SENHA_BOA)
    depois = servico.resetar_senha(
        TENANT, conta.id, senha_provisoria="nova-provisoria-01", ator="root@torre.local"
    )
    assert servico.resolver_sessao(token) is None
    assert depois.senha_expirada is True


# ---------------------------------------------------------- unicidade e tenants
def test_email_duplicado_no_mesmo_tenant_recusado_e_permitido_em_outro(
    servico: ServicoIdentidade,
) -> None:
    """`(tenant_id, lower(email))` é a chave (migração 0015): o unique GLOBAL do 0001
    impediria a mesma pessoa de ter conta em dois clientes E vazaria, pelo 409, que o
    e-mail já existe em outro tenant (achado 22/UAT5 aplicado à identidade)."""
    criador = uuid.uuid4()
    servico.criar_usuario(
        TENANT,
        email="ana@torre.local",
        nome="Ana",
        papeis=["analista"],
        senha_provisoria="provisoria-longa-01",
        criado_por=criador,
        ator="root",
    )
    with pytest.raises(EmailDuplicado):
        servico.criar_usuario(
            TENANT,
            email="ANA@TORRE.LOCAL",  # normalização: é o MESMO e-mail
            nome="Ana 2",
            papeis=["analista"],
            senha_provisoria="provisoria-longa-02",
            criado_por=criador,
            ator="root",
        )
    outra = servico.criar_usuario(
        "outra-torre",
        email="ana@torre.local",
        nome="Ana (outra torre)",
        papeis=["analista"],
        senha_provisoria="provisoria-longa-03",
        criado_por=criador,
        ator="root",
    )
    assert outra.tenant_id == "outra-torre"


def test_papel_desconhecido_recusado(servico: ServicoIdentidade) -> None:
    with pytest.raises(SenhaFraca):
        servico.criar_usuario(
            TENANT,
            email="x@torre.local",
            nome="X",
            papeis=["deus"],
            senha_provisoria="provisoria-longa-01",
            criado_por=uuid.uuid4(),
            ator="root",
        )


# --------------------------------------------------------------- bootstrap do root
def test_bootstrap_do_root_e_idempotente(servico: ServicoIdentidade) -> None:
    """Rodar de novo NÃO reseta a senha de quem já trocou — é o que separa bootstrap
    de backdoor: `JORNADA_ROOT_SENHA` esquecida no compose não pode ser caminho de
    volta para dentro da conta mais poderosa a cada restart."""
    criado = servico.semear_root(TENANT, email="sergio.gaiotto", senha="senha-inicial-root")
    assert criado is not None
    assert criado.papeis == ["admin"]
    assert criado.senha_expirada is True  # troca obrigatória no 1º acesso

    servico.trocar_senha(criado, senha_atual="senha-inicial-root", senha_nova=SENHA_NOVA)

    assert servico.semear_root(TENANT, email="sergio.gaiotto", senha="senha-inicial-root") is None
    with pytest.raises(CredencialInvalida):  # a senha antiga NÃO voltou a valer
        servico.autenticar(TENANT, email="sergio.gaiotto", senha="senha-inicial-root")
    token, _ = servico.autenticar(TENANT, email="sergio.gaiotto", senha=SENHA_NOVA)
    assert servico.resolver_sessao(token) is not None
    assert len(servico.listar_usuarios(TENANT)) == 1  # não duplicou


def test_env_example_copiado_nao_cria_root(servico: ServicoIdentidade) -> None:
    """O `.env.example` REAL, copiado como manda a linha 1 dele, não pode virar conta.

    Achado da auditoria: o parser de `.env` só trata `# ...` como comentário quando a
    linha TEM valor. Com `JORNADA_ROOT_EMAIL=   # login do root ...` o texto do
    comentário virava o VALOR, e as duas frases — publicadas neste repositório —
    passavam pela política de senha e criavam um admin de verdade. `senha_expirada` não
    salvava: `/auth/trocar-senha` é justamente uma das rotas liberadas nesse estado, e o
    invasor saía de lá com senha própria e papel `admin`.

    Este teste lê o arquivo de verdade (não uma cópia) porque o que se protege é o
    ARQUIVO: qualquer um que volte a pôr comentário ao lado de variável vazia reabre o
    buraco, e o teste morre junto.
    """
    from pathlib import Path

    from app.config import Settings

    env_example = Path(__file__).resolve().parents[3] / ".env.example"
    assert env_example.is_file(), env_example

    settings = Settings(_env_file=env_example)
    assert settings.jornada_root_email == ""
    assert settings.jornada_root_senha.get_secret_value() == ""
    assert (
        servico.semear_root(
            TENANT,
            email=settings.jornada_root_email,
            senha=settings.jornada_root_senha.get_secret_value(),
        )
        is None
    )
    assert servico.listar_usuarios(TENANT) == []


def test_bootstrap_ignora_login_malformado(servico: ServicoIdentidade) -> None:
    """Guarda-corpo de fundo: configuração podre não vira admin, mesmo que a "senha"
    passe na política. Nenhum login legítimo tem espaço no meio."""
    assert (
        servico.semear_root(
            TENANT,
            email="# login do root (aceita identificador sem @)",
            senha="# >=12 caracteres; nasce expirada (troca no 1o acesso)",
        )
        is None
    )
    assert servico.listar_usuarios(TENANT) == []

    with pytest.raises(SenhaFraca):  # e a rota de admin recusa o mesmo lixo
        servico.criar_usuario(
            TENANT,
            email="ana com espaco@torre.local",
            nome="Ana",
            papeis=["analista"],
            senha_provisoria="provisoria-longa-01",
            criado_por=uuid.uuid4(),
            ator="root",
        )


def test_bootstrap_recusa_senha_fraca(servico: ServicoIdentidade) -> None:
    """Root com senha fraca é pior que root ausente: falha ALTA, conta não criada."""
    with pytest.raises(SenhaFraca):
        servico.semear_root(TENANT, email="sergio.gaiotto", senha="123")
    assert servico.listar_usuarios(TENANT) == []


def test_bootstrap_sem_variaveis_nao_faz_nada(servico: ServicoIdentidade) -> None:
    assert servico.semear_root(TENANT, email="", senha="") is None
    assert servico.listar_usuarios(TENANT) == []
