"""Contract test do ReadModelAudienciaPort · a proveniência é AFIRMAÇÃO VERIFICADA (§8-M5-A5).

O K05 fez o certificado declarar de onde vieram as contagens (`derivado_do_sql`). O
risco imediato dessa declaração é ela virar flag: um adapter futuro devolve `True` sem
executar o SQL — por descuido ou para "ficar verde" — e o overclaim que o campo veio
eliminar volta, agora ASSINADO no hash do certificado, que é pior.

Este arquivo é o contrato que toda implementação da porta atravessa:

- **t1** forma: o dict tem `derivado_do_sql: bool`. Sem ele, o serviço cai no default
  conservador (False) — funciona, mas o adapter está fora do contrato.
- **t2** discriminador: quem declara `True` tem de PROVAR que consome o SQL — a mesma
  instância, dois SQLs materialmente distintos, contagens distintas. Para o adapter de
  fixtures o caso é `skip` nomeando o achado aberto por extenso, porque skip sem nome
  vira paisagem.
- **t3** alçapão: um `_ReadModelMentiroso` (declara `True`, ignora o argumento) tem de
  REPROVAR na verificação do t2. Este caso é o teste do teste: se o discriminador
  deixar o mentiroso passar, o contrato não prende nada.
- **t4** o adapter real de fixtures declara `False` — a confissão exigida pela porta.

A verificação central (`_verificar_discriminador`) é função compartilhada de propósito:
t2 e t3 têm de usar EXATAMENTE o mesmo juiz, senão o alçapão provaria a firmeza de um
juiz que ninguém usa.
"""

from typing import Any

import pytest

from adapters.fontes.read_model import ReadModelFixtures

# Dois SQLs materialmente distintos: universos e filtros diferentes. Um read model que
# EXECUTA o SQL não tem como devolver os mesmos números para os dois (fixado o estado
# da base durante o teste — os dois rodam na mesma chamada de verificação).
SQL_A = (
    "select contato_id from clientes where plano = 'pos' "
    "and contato_id not in (select contato_id from lista_optout)"
)
SQL_B = (
    "select contato_id from clientes where plano = 'pre' and uf = 'SP' "
    "and contato_id not in (select contato_id from lista_optout) "
    "and idade >= 60"
)


def _verificar_discriminador(read_model: Any) -> None:
    """O juiz único de t2/t3: quem declara True tem de discriminar SQLs distintos."""
    a = read_model.contagens_segmentacao(SQL_A)
    b = read_model.contagens_segmentacao(SQL_B)
    assert a.get("derivado_do_sql") is True and b.get("derivado_do_sql") is True
    contagens_a = (a.get("bruto"), dict(a.get("supressoes") or {}))
    contagens_b = (b.get("bruto"), dict(b.get("supressoes") or {}))
    assert contagens_a != contagens_b, (
        "o adapter declara derivado_do_sql=True mas devolveu contagens IDÊNTICAS para "
        "dois SQLs materialmente distintos — a declaração de proveniência é falsa"
    )


class _ReadModelMentiroso:
    """O adapter que o contrato existe para pegar: True sem consumir o argumento."""

    def contagens_segmentacao(self, sql_publico: str) -> dict[str, Any]:
        return {
            "bruto": 1_000,
            "supressoes": {"optout": 10},
            "derivado_do_sql": True,  # mentira: o sql_publico foi ignorado
        }


def test_t1_forma_o_dict_declara_proveniencia() -> None:
    contagens = ReadModelFixtures().contagens_segmentacao(SQL_A)
    assert "derivado_do_sql" in contagens, (
        "adapter fora do contrato §8-M5-A5: sem `derivado_do_sql` o serviço cai no "
        "default conservador e o certificado sai como fixture — declare a proveniência"
    )
    assert isinstance(contagens["derivado_do_sql"], bool)


def test_t2_quem_declara_true_discrimina_sqls_distintos() -> None:
    read_model = ReadModelFixtures()
    if read_model.contagens_segmentacao(SQL_A).get("derivado_do_sql") is not True:
        pytest.skip(
            "read model de fixtures não deriva contagens do SQL — o discriminador só "
            "se aplica a quem declara True. Este skip é o registro executável do achado "
            "ABERTO 'Camada 2 do Guard' (HANDOFF §8.3, J01 revertido na onda 6): o fecho "
            "real exige um read model que EXECUTE o sql_publico num Postgres com a base "
            "de contatos, no dialeto que o Engineer gera. Quando ele existir, este skip "
            "desaparece sozinho e o discriminador passa a valer."
        )
    _verificar_discriminador(read_model)


def test_t3_alcapao_o_mentiroso_reprova() -> None:
    """Se este teste falhar, o discriminador do t2 está frouxo — conserte O JUIZ."""
    with pytest.raises(AssertionError, match="proveniência é falsa"):
        _verificar_discriminador(_ReadModelMentiroso())


def test_t4_o_adapter_de_fixtures_confessa_false() -> None:
    """A confissão do estado atual, presa por teste: fixtures NÃO derivam do SQL.

    Se alguém trocar isto para True sem trocar a implementação, o t2 deixa de pular,
    o discriminador roda e reprova — os dois testes se travam mutuamente.
    """
    contagens = ReadModelFixtures().contagens_segmentacao(SQL_A)
    assert contagens["derivado_do_sql"] is False
    # e o adapter é MESMO indiferente ao SQL (é por isso que confessa False)
    assert ReadModelFixtures().contagens_segmentacao(SQL_B)["bruto"] == contagens["bruto"]
