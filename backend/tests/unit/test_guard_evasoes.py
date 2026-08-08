"""UAT5 · Achado 1 — evasões do Guard de elegibilidade (§8-M5-A1, §1.1.2).

O Guard é CÓDIGO, nunca LLM (§1.1.3) — mas quem escreve o SQL varrido é o LLM 120b
(engineer, §7.2). Enquanto a varredura foi "a palavra aparece no texto do WHERE?",
qualquer SQL que apenas CITASSE as 7 listas passava — inclusive um que mirava
exatamente os suprimidos. Cada teste aqui é uma evasão comprovada na caçada UAT5:

  a) EXISTS não negado  → seleciona SÓ quem está suprimido
  b) OR 1=1             → tautologia de topo neutraliza toda a supressão
  c) comentário SQL     → as 7 listas só existem depois de `--` / `/* */`
  d) literal de string  → as 7 listas só existem dentro de `'...'` de um `=`
  e) SELECT-list        → as listas aparecem na projeção, não no WHERE
  f) opt-in invertido   → `opt_in = 0` é mira em quem pediu para não ser incomodado

E o caso FELIZ (NOT EXISTS/NOT IN das 7 + opt-in) que DEVE continuar passando —
tanto na forma do M5 quanto na forma do M9/M10/demo (§11.4).
"""

import re
import uuid
from datetime import UTC, datetime

import pytest

from agents.guard import elegibilidade as guard
from domain.audiencia.erros import CertificadoReprovado
from domain.audiencia.modelos import SETE_LISTAS

# ------------------------------------------------------------------ SQL legítimo
# Forma 1 (test_M5): NOT EXISTS correlacionado com as 7 listas no IN e opt-in por canal.
SQL_FELIZ_NOT_EXISTS = (
    "SELECT c.contato_hash FROM hybris_base_clientes c\n"
    "WHERE c.plano = 'pos_pago'\n"
    "  AND (c.opt_in_email OR c.opt_in_sms OR c.opt_in_push OR c.opt_in_whatsapp)\n"
    "  AND NOT EXISTS (SELECT 1 FROM lista_supressao s\n"
    "    WHERE s.contato_hash = c.contato_hash AND s.lista IN\n"
    "      ('blacklist','fraude','nao_perturbe','optout','procon',"
    "'inadimplente','reprovado_credito'))"
)
# Forma 2 (test_M9/M10/demo_seeds §11.4): NOT IN com subconsulta.
SQL_FELIZ_NOT_IN = (
    "select contato_hash from base_clientes where opt_in_email = true "
    "and contato_hash not in (select contato_hash from lista_supressao where lista in "
    "('blacklist','fraude','nao_perturbe','optout','procon','inadimplente',"
    "'reprovado_credito'))"
)

_LISTAS_SQL = ",".join(f"'{lista}'" for lista in SETE_LISTAS)

# ------------------------------------------------------------------- as evasões
# (a) EXISTS INVERTIDO: seleciona EXATAMENTE quem está suprimido, e sem opt-in.
SQL_EXISTS_INVERTIDO = (
    "SELECT c.id FROM contatos c WHERE "
    + " AND ".join(f"EXISTS (SELECT 1 FROM {lista} s WHERE s.id = c.id)" for lista in SETE_LISTAS)
    + " AND c.opt_in = 0"
)
# (b) OR 1=1: tautologia de topo — o WHERE inteiro vira "todo mundo".
SQL_OR_TAUTOLOGIA = (
    "SELECT id FROM contatos WHERE (1=1 OR "
    + " OR ".join(f"{lista} = 1" for lista in SETE_LISTAS)
    + " OR opt_in = 0)"
)
# (c) COMENTÁRIO: as listas e o opt-in só existem dentro de comentário SQL.
SQL_COMENTARIO = (
    "SELECT id FROM contatos WHERE ativo = 1\n"
    f"-- supressao: {' '.join(SETE_LISTAS)} + opt_in conferidos offline\n"
    f"/* {' '.join(SETE_LISTAS)} opt_in */"
)
# (d) LITERAL: as listas só existem dentro de um literal de string de uma igualdade.
SQL_LITERAL = f"SELECT id FROM contatos WHERE nome = '{' '.join(SETE_LISTAS)} opt_in' AND ativo = 1"
# (e) SELECT-LIST: as listas aparecem na projeção, não na restrição.
SQL_SELECT_LIST = (
    "SELECT id, " + ", ".join(f"0 AS {lista}" for lista in SETE_LISTAS) + ", 1 AS opt_in "
    "FROM contatos WHERE ativo = 1"
)
# (f) OPT-IN INVERTIDO: supressão correta, mas mira em quem NÃO deu opt-in.
SQL_OPT_IN_INVERTIDO = (
    "select contato_hash from base_clientes where opt_in_email = 0 "
    "and contato_hash not in (select contato_hash from lista_supressao where lista in "
    f"({_LISTAS_SQL}))"
)

EVASOES = {
    "exists_invertido": SQL_EXISTS_INVERTIDO,
    "or_tautologia": SQL_OR_TAUTOLOGIA,
    "comentario": SQL_COMENTARIO,
    "literal": SQL_LITERAL,
    "select_list": SQL_SELECT_LIST,
}


@pytest.mark.parametrize("nome", sorted(EVASOES))
def test_evasao_e_reprovada(nome: str) -> None:
    """Toda evasão vira `CertificadoReprovado` — nenhuma emite certificado (§8-M5-A1)."""
    sql = EVASOES[nome]
    faltantes, problemas = guard.problemas_no_sql(sql)
    assert problemas, f"evasão {nome} passou pelo Guard: {sql}"
    with pytest.raises(CertificadoReprovado):
        guard.validar_sql_de_segmentacao(sql)
    # a supressão não foi aplicada em NENHUMA lista: as 7 têm de constar como faltantes
    assert faltantes == list(SETE_LISTAS), f"evasão {nome}: faltantes={faltantes}"


def test_exists_nao_negado_tem_mensagem_propria() -> None:
    """(a) EXISTS/IN sobre lista de supressão SEM negação inverte o filtro — o motivo
    precisa dizer isso, não só 'lista ausente' (o operador leria errado)."""
    _, problemas = guard.problemas_no_sql(SQL_EXISTS_INVERTIDO)
    texto = " ".join(problemas).lower()
    assert "exists" in texto or "não negad" in texto
    assert "blacklist" in texto


def test_or_de_topo_e_denunciado() -> None:
    """(b) supressão sob OR com condição sempre verdadeira → motivo explícito."""
    _, problemas = guard.problemas_no_sql(SQL_OR_TAUTOLOGIA)
    texto = " ".join(problemas).lower()
    assert " or " in texto or "sempre verdadeir" in texto


def test_opt_in_invertido_e_reprovado() -> None:
    """(f) supressão certa + `opt_in = 0`: mira em quem recusou contato."""
    _, problemas = guard.problemas_no_sql(SQL_OPT_IN_INVERTIDO)
    assert problemas, "opt_in = 0 passou pelo Guard"
    assert any("opt" in p.lower() for p in problemas)
    with pytest.raises(CertificadoReprovado):
        guard.validar_sql_de_segmentacao(SQL_OPT_IN_INVERTIDO)


@pytest.mark.parametrize("sql", [SQL_FELIZ_NOT_EXISTS, SQL_FELIZ_NOT_IN])
def test_caso_feliz_continua_passando(sql: str) -> None:
    """Fluxo legítimo intacto: as 7 listas sob NOT EXISTS/NOT IN + opt-in positivo."""
    faltantes, problemas = guard.problemas_no_sql(sql)
    assert (faltantes, problemas) == ([], [])
    guard.validar_sql_de_segmentacao(sql)  # não levanta


def test_adulteracao_classica_ainda_aponta_as_listas_removidas() -> None:
    """Regressão do A1 original: removeram procon/inadimplente do IN → faltam essas 2."""
    adulterado = SQL_FELIZ_NOT_EXISTS.replace("'procon',", "").replace("'inadimplente',", "")
    faltantes, problemas = guard.problemas_no_sql(adulterado)
    assert faltantes == ["procon", "inadimplente"]
    assert problemas


def test_comentario_nao_apaga_where_legitimo() -> None:
    """Higienização não pode comer o SQL: comentário ao lado do WHERE conforme é ok."""
    com_comentario = SQL_FELIZ_NOT_IN + " -- revisado pelo compliance em 2026-08-06"
    assert guard.problemas_no_sql(com_comentario) == ([], [])


def test_literal_com_hifen_duplo_nao_e_tratado_como_comentario() -> None:
    """`--` DENTRO de literal é dado, não comentário: o WHERE conforme continua válido."""
    sql = SQL_FELIZ_NOT_IN.replace(
        "where opt_in_email = true", "where campanha = 'promo--5g' and opt_in_email = true"
    )
    assert guard.problemas_no_sql(sql) == ([], [])


def test_precedencia_and_or_nao_deixa_tautologia_passar() -> None:
    """`A AND B OR 1=1` é `(A AND B) OR 1=1` = todo mundo. O Guard tem de ler a
    PRECEDÊNCIA do SQL, não a ordem em que os AND aparecem."""
    for cauda in (" or 1=1", " and ativo = 1 or 1=1", " or 'x' = 'x'", " or true"):
        faltantes, problemas = guard.problemas_no_sql(SQL_FELIZ_NOT_IN + cauda)
        assert problemas, f"cauda {cauda!r} passou pelo Guard"
        assert faltantes == list(SETE_LISTAS), cauda


def test_union_e_ponto_e_virgula_contrabandeiam_audiencia() -> None:
    """Fora do WHERE varrido também entra gente: um segundo SELECT colado por UNION
    (ou outra instrução após `;`) traria a lista de supressão inteira."""
    _, problemas_union = guard.problemas_no_sql(
        SQL_FELIZ_NOT_IN + " union all select contato_hash from lista_supressao"
    )
    assert any("union" in p.lower() for p in problemas_union)
    _, problemas_ponto = guard.problemas_no_sql(
        SQL_FELIZ_NOT_IN + "; select contato_hash from lista_supressao"
    )
    assert any("instru" in p.lower() for p in problemas_ponto)
    # `;` no fim da instrução é pontuação, não contrabando
    assert guard.problemas_no_sql(SQL_FELIZ_NOT_IN + ";") == ([], [])


def test_where_de_subconsulta_nao_conta_como_where_de_topo() -> None:
    """A varredura é do WHERE de TOPO: WHERE dentro de subconsulta no FROM não vale."""
    sql = (
        "SELECT t.id FROM (SELECT id FROM contatos WHERE "
        + " AND ".join(f"{lista} = 0" for lista in SETE_LISTAS)
        + " AND opt_in = 1) t"
    )
    faltantes, problemas = guard.problemas_no_sql(sql)
    assert faltantes == list(SETE_LISTAS) and problemas


# --------------------------------------------- evasões de 2ª geração (auditoria)
# O predicado só vale pelo que ele afirma NO PRÓPRIO NÍVEL. Estas três burlam a
# varredura quando o formato é lido no texto inteiro da folha, subconsulta incluída:
# um `IS NULL`/`= 0` inocente DENTRO do parêntese fazia um `EXISTS` positivo passar
# por exclusão — ou seja, o achado 1a de volta, com um predicado a mais.
SQL_EXISTS_POSITIVO_COM_EXCLUSAO_INTERNA = (
    "SELECT c.contato_hash FROM base_clientes c WHERE c.opt_in_email = true "
    "AND EXISTS (SELECT 1 FROM lista_supressao s WHERE s.contato_hash = c.contato_hash "
    f"AND s.lista IN ({_LISTAS_SQL}) AND s.removido_em IS NULL)"
)
SQL_IN_POSITIVO_COM_EXCLUSAO_INTERNA = (
    "select contato_hash from base_clientes where opt_in_email = true "
    "and contato_hash in (select contato_hash from lista_supressao where lista in "
    f"({_LISTAS_SQL}) and revogado = 0)"
)


@pytest.mark.parametrize(
    "sql",
    [SQL_EXISTS_POSITIVO_COM_EXCLUSAO_INTERNA, SQL_IN_POSITIVO_COM_EXCLUSAO_INTERNA],
    ids=["exists_positivo", "in_positivo"],
)
def test_exclusao_dentro_da_subconsulta_nao_cobre_pertinencia_positiva(sql: str) -> None:
    """`EXISTS/IN (… IS NULL)` continua SELECIONANDO os suprimidos: o `IS NULL` está
    dentro do parêntese e não nega coisa alguma no nível do predicado (§8-M5-A1)."""
    faltantes, problemas = guard.problemas_no_sql(sql)
    assert faltantes == list(SETE_LISTAS), f"exclusão interna cobriu as listas: {faltantes}"
    assert any("exists" in p.lower() or "não negad" in p.lower() for p in problemas), problemas
    with pytest.raises(CertificadoReprovado):
        guard.validar_sql_de_segmentacao(sql)


def test_opt_in_so_dentro_de_literal_nao_conta_como_checagem() -> None:
    """Supressão impecável, mas o `opt_in` só existe dentro de `'promo opt_in'`:
    menção não é checagem — o mesmo critério já aplicado às 7 listas (achado 1d)."""
    sql = SQL_FELIZ_NOT_IN.replace("where opt_in_email = true", "where campanha = 'promo opt_in'")
    _, problemas = guard.problemas_no_sql(sql)
    assert any("opt" in p.lower() for p in problemas), problemas


@pytest.mark.parametrize(
    "checagem",
    ["NOT c.opt_in_email", "not base.opt_in_sms", "c.opt_in_email = 0", "c.opt_in_email is false"],
)
def test_opt_in_invertido_e_reprovado_mesmo_qualificado(checagem: str) -> None:
    """`NOT c.opt_in_email` nega tanto quanto `NOT opt_in_email` — o alias da tabela
    não pode ser um buraco na detecção de opt-in invertido (§8-M5)."""
    sql = SQL_FELIZ_NOT_IN.replace("opt_in_email = true", checagem)
    _, problemas = guard.problemas_no_sql(sql)
    assert any("opt" in p.lower() for p in problemas), (checagem, problemas)


def test_opt_in_dentro_da_subconsulta_de_supressao_nao_conta() -> None:
    """`… not in (select … where opt_in = 1)` filtra a SUPRESSÃO, não a audiência:
    a checagem de opt-in tem de valer no WHERE de topo (§8-M5)."""
    sql = SQL_FELIZ_NOT_IN.replace("where opt_in_email = true and", "where").replace(
        f"({_LISTAS_SQL}))", f"({_LISTAS_SQL}) and opt_in_email = 1)"
    )
    _, problemas = guard.problemas_no_sql(sql)
    assert any("opt" in p.lower() for p in problemas), problemas


# ------------------------------------------------------- camada 2: as contagens
def test_supressao_zero_nas_sete_listas_reprova_certificado() -> None:
    """Camada 2 (§8-M5-A1): SQL 'aprovado' que suprime ZERO nas 7 listas com líquido
    positivo é evidência de cláusula inoperante — não se emite certificado."""
    problemas = guard.problemas_nas_contagens({lista: 0 for lista in SETE_LISTAS}, 888_620)
    assert problemas
    assert any(re.search(r"zero", p, re.IGNORECASE) for p in problemas)
    uma_lista_corta = {**{lista: 0 for lista in SETE_LISTAS}, "optout": 1}
    assert guard.problemas_nas_contagens(uma_lista_corta, 10) == []
    assert guard.problemas_nas_contagens({lista: 0 for lista in SETE_LISTAS}, 0) == []


def test_emitir_certificado_recusa_supressao_zero() -> None:
    """O certificado é o documento que autoriza o disparo: o último portão (§8-M5-A3)
    também olha o EFEITO medido — supressão zero nas 7 com líquido não vira assinatura."""
    argumentos = {
        "os_id": uuid.UUID(int=1),
        "segmento_id": uuid.UUID(int=2),
        "sql_publico": SQL_FELIZ_NOT_IN,
        "liquido": 888_620,
        "agora": datetime(2026, 8, 6, 12, 0, tzinfo=UTC),
        # §8-M5-A5: os dicionários deste teste são montados à mão — não são medição
        "contagens_derivadas_do_sql": False,
    }
    with pytest.raises(CertificadoReprovado) as erro:
        guard.emitir_certificado(suprimidos={lista: 0 for lista in SETE_LISTAS}, **argumentos)
    assert erro.value.listas_faltantes == list(SETE_LISTAS)
    # com supressão real, emite normalmente (fluxo legítimo intacto)
    certificado = guard.emitir_certificado(
        suprimidos={lista: 10 for lista in SETE_LISTAS}, **argumentos
    )
    assert len(certificado.hash) == 64 and certificado.liquido == 888_620


# ----------------------------------------------------- E01b (UAT #5 pós-onda 1)
# A primeira correção fechou as 5 evasões catalogadas e REABRIU a mesma classe com
# operadores vizinhos: a lista era dada por coberta quando a MENÇÃO aparecia no texto
# e um `_EXCLUSAO` qualquer aparecia na estrutura do predicado. Como
# `_estrutura_do_predicado` esvazia o interior dos parênteses mas os preserva,
# `NOT (tipo = 'blacklist … optout')` virava `not ( )` e casava. Denylist de evasão é
# corrida armamentista — a folha passou a reconhecer FORMA CANÔNICA de supressão.
_LISTAS_NO_TEXTO = " ".join(SETE_LISTAS)
_NOT_EXISTS_7 = " AND ".join(
    f"NOT EXISTS (SELECT 1 FROM {lista} s WHERE s.id = c.id)" for lista in SETE_LISTAS
)


@pytest.mark.parametrize(
    ("nome", "sql"),
    [
        (
            "not_parenteses",  # `NOT ( )` na estrutura — predicado que não exclui ninguém
            f"SELECT id FROM contatos c WHERE NOT (tipo = '{_LISTAS_NO_TEXTO}') AND opt_in = 1",
        ),
        (
            "not_like",  # idem, casando `\bnot\s+like\b`
            f"SELECT id FROM contatos c WHERE obs NOT LIKE '%{_LISTAS_NO_TEXTO}%' AND opt_in = 1",
        ),
        (
            "comentario_aninhado",  # o Postgres aninha; fechar no 1º `*/` mostrava a cauda
            f"SELECT id FROM contatos c WHERE /* nota /* interna */ {_NOT_EXISTS_7} */ "
            "1 = 1 AND opt_in = 1",
        ),
        (
            "subconsulta_vazia",  # `NOT EXISTS (… AND 1=0)` é sempre verdadeiro
            "SELECT id FROM contatos c WHERE "
            + " AND ".join(
                f"NOT EXISTS (SELECT 1 FROM {lista} s WHERE s.id = c.id AND 1 = 0)"
                for lista in SETE_LISTAS
            )
            + " AND opt_in = 1",
        ),
        (
            "dollar_quoting",  # $$…$$ é literal no banco e era código para o Guard
            f"SELECT id FROM contatos c WHERE descricao = $$ {_NOT_EXISTS_7} $$ AND opt_in = 1",
        ),
    ],
)
def test_E01b_predicado_que_nao_exclui_ninguem_e_reprovado(nome: str, sql: str) -> None:
    """Cada um destes saía com certificado 201 e `suprimidos` preenchido."""
    faltantes, problemas = guard.problemas_no_sql(sql)
    assert faltantes or problemas, f"{nome}: SQL que não suprime ninguém foi aprovado"


@pytest.mark.parametrize(
    ("nome", "sql"),
    [
        (
            "not_exists",
            f"SELECT id FROM contatos c WHERE {_NOT_EXISTS_7} AND opt_in = 1",
        ),
        (
            "coluna_bandeira",
            "SELECT id FROM contatos c WHERE "
            + " AND ".join(f"{lista} = 0" for lista in SETE_LISTAS)
            + " AND opt_in = 1",
        ),
        (
            "not_in",
            "SELECT id FROM contatos c WHERE "
            + " AND ".join(f"c.id NOT IN (SELECT id FROM {lista})" for lista in SETE_LISTAS)
            + " AND opt_in = 1",
        ),
    ],
)
def test_E01b_formas_canonicas_de_supressao_seguem_passando(nome: str, sql: str) -> None:
    """O fix não pode fechar o caminho legítimo — falha para o lado seguro é fácil
    demais, e um Guard que reprova tudo é substituído pelo primeiro analista apressado."""
    faltantes, problemas = guard.problemas_no_sql(sql)
    assert not faltantes and not problemas, f"{nome}: {faltantes} {problemas}"
