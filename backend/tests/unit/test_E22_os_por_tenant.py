"""Achado 22 (UAT5) — sequência e duplicidade da OS são POR TENANT no adapter.

Contrato das portas (§2.1) exercido direto no repositório de memória; o adapter SQL
tem o espelho em `tests/integration/test_E22_os_por_tenant_sql.py` (@integration, com
o unique (tenant_id, codigo) da migração 0014 de pé).

O último teste é o CONTRAGOLPE da emenda: afrouxar o unique tornou legítimo dois
tenants compartilharem um código, e por isso a busca GLOBAL deixou de ser inofensiva
no loader de extracts (§8-M10) — devolvendo uma OS arbitrária, o batch do cliente
certo sumia em `ignorados`, sem erro nenhum.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from adapters.persistence.memoria import RepositorioOsMemoria
from adapters.publicacoes import PublicacoesLocais
from application.services.lancamento_service import ServicoLancamento
from domain.campanha.modelos import OS

AGORA = datetime(2026, 8, 6, 12, 0, 0, tzinfo=UTC)


def _os(tenant: str, codigo: str) -> OS:
    return OS(
        id=uuid.uuid4(),
        tenant_id=tenant,
        codigo=codigo,
        nome="Campanha",
        tshirt="M",
        fase="pensada",
        briefing={},
        frozen=None,
        created_by=uuid.uuid4(),
        created_at=AGORA,
        updated_at=AGORA,
    )


def test_obter_os_por_codigo_escopa_por_tenant() -> None:
    """Com tenant informado, código de outro cliente é INEXISTENTE (era o oráculo do
    409); sem tenant a busca segue global — o loader de extracts §8-M10 depende disso."""
    repo = RepositorioOsMemoria()
    alheia = _os("torre-movel", "OS-2026-0457")
    repo.adicionar_os(alheia)

    assert repo.obter_os_por_codigo("OS-2026-0457", "outra-torre") is None
    assert repo.obter_os_por_codigo("OS-2026-0457", "torre-movel") is not None
    assert repo.obter_os_por_codigo("OS-2026-0457") is not None  # cross-tenant explícito


def test_mesmo_codigo_pode_existir_em_dois_tenants() -> None:
    repo = RepositorioOsMemoria()
    repo.adicionar_os(_os("torre-movel", "OS-2026-0457"))
    repo.adicionar_os(_os("outra-torre", "OS-2026-0457"))

    minha = repo.obter_os_por_codigo("OS-2026-0457", "torre-movel")
    dela = repo.obter_os_por_codigo("OS-2026-0457", "outra-torre")
    assert minha is not None and dela is not None and minha.id != dela.id
    assert [o.codigo for o in repo.listar_os("outra-torre", 10, 0)] == ["OS-2026-0457"]


def test_sequencial_nao_enxerga_o_volume_do_outro_tenant() -> None:
    repo = RepositorioOsMemoria()
    assert [repo.proximo_sequencial_os(2026, "torre-movel") for _ in range(3)] == [1, 2, 3]
    assert repo.proximo_sequencial_os(2026, "outra-torre") == 1  # começa do 1, não do 4
    assert repo.proximo_sequencial_os(2026, "torre-movel") == 4  # e o meu segue de onde parou
    assert repo.proximo_sequencial_os(2027, "torre-movel") == 1  # ano é parte da chave


# ------------------------------------------- contragolpe: o loader de extracts (§8-M10)
class _RelogioFixo:
    def agora(self) -> datetime:
        return AGORA


class _SemSupressao:
    def esta_suprimido(self, contato_hash: str) -> bool:
        return False

    def listar(self) -> list[str]:
        return []


class _ExtractsUmaLinha:
    """Batch D-1 com uma linha de `OS-2026-0457` — código que, depois da emenda,
    pode existir em MAIS DE UM tenant."""

    def listar_eventos(self) -> list[dict[str, Any]]:
        return [
            {
                "os_codigo": "OS-2026-0457",
                "no_jgc": "n1",
                "canal": "email",
                "tipo": "delivered",
                "contato_hash": "a" * 64,  # sha256 hex (§10.2) — o loader recusa o resto
                "ts": "2026-08-05T10:00:00+00:00",
                "payload": {},
            }
        ]


def test_loader_de_extracts_acha_a_os_do_proprio_tenant() -> None:
    """O loader resolve o `os_codigo` DENTRO do tenant que pediu a carga.

    Com a busca global, `obter_os_por_codigo` devolvia a primeira OS com aquele código
    — a do vizinho — e a conferência de tenant logo abaixo descartava a linha: carga
    de 0 e `ignorados` de 1, sem erro. Perda silenciosa de telemetria, não vazamento.
    """
    repo = RepositorioOsMemoria()
    repo.adicionar_os(_os("torre-movel", "OS-2026-0457"))  # entra primeiro de propósito
    minha = _os("outra-torre", "OS-2026-0457")
    repo.adicionar_os(minha)

    servico = ServicoLancamento(
        repo, _RelogioFixo(), _SemSupressao(), PublicacoesLocais(), extracts=_ExtractsUmaLinha()
    )
    carga = servico.carregar_extracts("outra-torre")

    assert (carga["carregados"], carga["ignorados"]) == (1, 0), carga
    assert [e.os_id for e in repo.listar_telemetria(minha.id)] == [minha.id]


def test_loader_de_extracts_ignora_codigo_de_outro_tenant() -> None:
    """E o isolamento continua: código que só existe no vizinho é IGNORADO (§8-M10 —
    extract multi-OS; nada é inventado §1.3.5), nunca ingerido no tenant errado."""
    repo = RepositorioOsMemoria()
    repo.adicionar_os(_os("torre-movel", "OS-2026-0457"))

    servico = ServicoLancamento(
        repo, _RelogioFixo(), _SemSupressao(), PublicacoesLocais(), extracts=_ExtractsUmaLinha()
    )
    carga = servico.carregar_extracts("outra-torre")

    assert (carga["carregados"], carga["ignorados"]) == (0, 1), carga
