"""Identidade no adapter SQL, com Postgres REAL (@integration) — emenda G01.

O espelho em memória está em `tests/unit/test_G01_senha_e_identidade.py`. Aqui o que
importa é o SCHEMA da migração 0015, que a memória não pode provar:

· `usuario` ganhou corpo (senha_hash, ativo, senha_expirada, trilha de bloqueio) — sem
  as colunas, todo `insert` do adapter estoura;
· o unique de `email` é POR TENANT e sobre `lower(email)` — sem a troca, a mesma pessoa
  não teria conta em dois clientes e o 409 vazaria a existência entre tenants;
· `sessao` existe, referencia `usuario` e a revogação em massa é um UPDATE só.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from adapters.persistence.sql import RepositorioSql, criar_engine
from domain.identidade.modelos import ContaUsuario, Sessao

pytestmark = pytest.mark.integration

AGORA = datetime(2026, 8, 6, 12, 0, 0, tzinfo=UTC)


def _conta(tenant: str, email: str, **kwargs: object) -> ContaUsuario:
    base = {
        "id": uuid.uuid4(),
        "tenant_id": tenant,
        "email": email,
        "nome": "Ana",
        "senha_hash": "$argon2id$v=19$m=65536,t=3,p=4$fake-para-schema",
        "papeis": ["analista"],
        "criado_em": AGORA,
    }
    base.update(kwargs)
    return ContaUsuario(**base)  # type: ignore[arg-type]


def test_usuario_ida_e_volta_com_todas_as_colunas(banco_limpo: str) -> None:
    """Round-trip completo: as colunas da 0015 existem e o agregado volta inteiro."""
    repo = RepositorioSql(criar_engine(banco_limpo))
    conta = _conta(
        "torre-movel",
        "ana@torre.local",
        papeis=["analista", "lider"],
        senha_expirada=True,
        criado_por=uuid.uuid4(),
        ultimo_acesso=AGORA,
        tentativas_falhas=3,
        bloqueado_ate=AGORA + timedelta(minutes=15),
    )
    repo.adicionar_usuario(conta)

    lida = repo.obter_usuario(conta.id)
    assert lida is not None
    assert lida.papeis == ["analista", "lider"]
    assert lida.senha_expirada is True
    assert lida.tentativas_falhas == 3
    assert lida.bloqueado_ate == conta.bloqueado_ate
    assert lida.senha_hash == conta.senha_hash


def test_unique_de_email_e_por_tenant_e_case_insensitive(banco_limpo: str) -> None:
    """Dois tenants com o MESMO e-mail convivem; repetir dentro do tenant quebra — e
    quebra também com outra caixa, porque o índice é sobre `lower(email)`."""
    repo = RepositorioSql(criar_engine(banco_limpo))
    repo.adicionar_usuario(_conta("torre-movel", "ana@torre.local"))
    repo.adicionar_usuario(_conta("outra-torre", "ana@torre.local"))  # sem a 0015: erro

    minha = repo.obter_usuario_por_email("torre-movel", "ANA@TORRE.LOCAL")
    assert minha is not None and minha.tenant_id == "torre-movel"
    assert repo.obter_usuario_por_email("tenant-vazio", "ana@torre.local") is None

    with pytest.raises(IntegrityError):  # a invariante é do BANCO, não só do serviço
        repo.adicionar_usuario(_conta("torre-movel", "Ana@Torre.Local"))


def test_listar_usuarios_e_escopado_por_tenant(banco_limpo: str) -> None:
    repo = RepositorioSql(criar_engine(banco_limpo))
    repo.adicionar_usuario(_conta("torre-movel", "ana@torre.local"))
    repo.adicionar_usuario(_conta("torre-movel", "bruno@torre.local"))
    repo.adicionar_usuario(_conta("outra-torre", "carla@outra.local"))

    emails = [c.email for c in repo.listar_usuarios("torre-movel")]
    assert sorted(emails) == ["ana@torre.local", "bruno@torre.local"]


def test_sessao_persiste_e_revogacao_em_massa_e_um_update(banco_limpo: str) -> None:
    """A revogação preserva o instante da revogação anterior (`revogada_em is null` no
    WHERE) — a trilha por pessoa depende de não sobrescrever o passado."""
    repo = RepositorioSql(criar_engine(banco_limpo))
    conta = _conta("torre-movel", "ana@torre.local")
    repo.adicionar_usuario(conta)

    viva = Sessao(
        id="a" * 64,
        usuario_id=conta.id,
        criada_em=AGORA,
        expira_em=AGORA + timedelta(hours=12),
        ip="10.0.0.1",
        user_agent="pytest",
    )
    ja_revogada = Sessao(
        id="b" * 64,
        usuario_id=conta.id,
        criada_em=AGORA - timedelta(hours=2),
        expira_em=AGORA + timedelta(hours=10),
        revogada_em=AGORA - timedelta(hours=1),
    )
    repo.adicionar_sessao(viva)
    repo.adicionar_sessao(ja_revogada)

    assert repo.obter_sessao("a" * 64) is not None
    assert repo.revogar_sessoes_do_usuario(conta.id, AGORA) == 1  # só a viva

    depois = repo.obter_sessao("a" * 64)
    assert depois is not None and depois.revogada_em == AGORA
    antiga = repo.obter_sessao("b" * 64)
    assert antiga is not None and antiga.revogada_em == AGORA - timedelta(hours=1)


def test_sessao_exige_usuario_existente(banco_limpo: str) -> None:
    """FK de `sessao.usuario_id`: sessão órfã não entra (0015)."""
    repo = RepositorioSql(criar_engine(banco_limpo))
    with pytest.raises(IntegrityError):
        repo.adicionar_sessao(
            Sessao(
                id="c" * 64,
                usuario_id=uuid.uuid4(),
                criada_em=AGORA,
                expira_em=AGORA + timedelta(hours=1),
            )
        )


def test_schema_tem_o_indice_por_tenant_e_a_tabela_sessao(banco_limpo: str) -> None:
    """Guarda-corpo do DDL: as invariantes vivem no schema (0015), não na aplicação."""
    engine = criar_engine(banco_limpo)
    try:
        with engine.connect() as conexao:
            indices = {
                linha[0]
                for linha in conexao.execute(
                    text("select indexname from pg_indexes where tablename = 'usuario'")
                )
            }
            assert "usuario_tenant_id_email_key" in indices
            assert conexao.execute(text("select to_regclass('sessao')")).scalar() == "sessao"
            # o unique GLOBAL do 0001 tem de ter ido embora
            restricoes = {
                linha[0]
                for linha in conexao.execute(
                    text(
                        "select conname from pg_constraint"
                        " where conrelid = 'usuario'::regclass and contype = 'u'"
                    )
                )
            }
            assert "usuario_email_key" not in restricoes
    finally:
        engine.dispose()
