"""A7 parte 1 — seleção de persistência por config (SEM docker, §1.3.5).

`criar_repositorio`: DATABASE_URL setado E alcançável → repos SQL; senão memória.
Aqui cobrimos os caminhos de fallback (URL ausente/inalcançável) e a normalização
de driver (o §3.1 fixa `postgresql+asyncpg`; as portas de repositório são síncronas).
"""

from adapters.persistence.memoria import RepositorioOsMemoria
from adapters.persistence.sql import RepositorioSql, criar_repositorio, url_sincrona


def test_sem_database_url_cai_para_memoria() -> None:
    repositorio = criar_repositorio(None)
    assert isinstance(repositorio, RepositorioOsMemoria)
    assert not isinstance(repositorio, RepositorioSql)
    assert criar_repositorio("").__class__ is RepositorioOsMemoria


def test_database_url_inalcancavel_cai_para_memoria() -> None:
    # porta descartável em loopback: conexão recusada na hora (sonda de 2s no pior caso)
    repositorio = criar_repositorio("postgresql+asyncpg://u:p@127.0.0.1:9/jornada")
    assert isinstance(repositorio, RepositorioOsMemoria)
    assert not isinstance(repositorio, RepositorioSql)


def test_url_sincrona_normaliza_driver_preservando_credenciais() -> None:
    url = url_sincrona("postgresql+asyncpg://jornada:s3nha@db:5432/jornada")
    assert url.drivername == "postgresql+psycopg2"
    assert url.host == "db" and url.port == 5432 and url.database == "jornada"
    assert url.username == "jornada" and url.password == "s3nha"
