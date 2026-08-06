"""Guard determinístico de elegibilidade (roster §7.2) — CÓDIGO PURO, ZERO LLM.

Compliance é código determinístico, nunca LLM (§1.1.3); o caminho crítico jamais
depende de LLM (§10.6). Este módulo NÃO importa LLMPort nem nada de adapters.

Responsabilidades (§8-M5):
1. `analisar_sql`/`validar_sql_de_segmentacao` — CAMADA 1 (texto): varre o WHERE de
   TOPO do SQL público; as 7 listas de supressão (§4.1 `lista_supressao`) precisam
   estar sob predicado de EXCLUSÃO e a checagem de opt-in precisa existir e não estar
   invertida; qualquer falha → `CertificadoReprovado` (A1).
2. `problemas_nas_contagens` — CAMADA 2 (números): cláusula que suprime ZERO nas 7
   listas com líquido positivo é cláusula inoperante; `emitir_certificado` recusa.
3. `emitir_certificado` — emite `certificado_elegibilidade` (§4.1) com hash sha256
   do conteúdo canônico e validade (A3).
4. `certificado_vigente`/`exigir_certificado_vigente` — helpers de validade que o
   publish (M8/M9) usará para RECUSAR certificado expirado (A3).

Por que camada 1 não é "a palavra aparece?" (UAT5 · achado 1): quem escreve o SQL é
o LLM 120b (engineer §7.2) e a busca por substring aprovava SQL que MIRAVA os
suprimidos — `EXISTS` no lugar de `NOT EXISTS`, `1=1 OR ...`, as 7 listas dentro de
comentário ou de literal de string. A varredura agora é estrutural: higieniza
(comentários fora), percorre a árvore booleana do WHERE de topo respeitando a
precedência OR/AND e exige, POR LISTA, uma exclusão que valha em todos os ramos —
recusando também o que escapa do WHERE (UNION, `;`). Texto ainda é texto: nenhum
parser textual sabe se `lista_supressao` é mesmo a tabela das 7 listas — por isso
a camada 2 (números) existe.

O LLM 20b pode apenas EXPLICAR o veredito na UI (§7.2) — nunca produzi-lo.
"""

import hashlib
import json
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from domain.audiencia.erros import CertificadoExpirado, CertificadoReprovado
from domain.audiencia.modelos import SETE_LISTAS, CertificadoElegibilidade

# Validade do certificado: 24h, alinhada ao ciclo D-1 do Hybris (§11 fixtures; A4).
# A re-varredura last-mile no disparo (M9/M10) re-emite/atualiza (§4.1 last_mile).
VALIDADE_HORAS_CERTIFICADO = 24

_WHERE = re.compile(r"\bwhere\b", re.IGNORECASE)
_AND = re.compile(r"\band\b", re.IGNORECASE)
_OR = re.compile(r"\bor\b", re.IGNORECASE)
# O WHERE acaba onde começa a próxima cláusula/consulta: o que vem depois não filtra.
_FIM_DO_WHERE = re.compile(
    r"\b(?:group\s+by|order\s+by|having|limit|offset|window|fetch|returning"
    r"|union|except|intersect)\b",
    re.IGNORECASE,
)
# Operadores de conjunto: colam OUTRO select à audiência, fora do WHERE varrido.
_SET_OP = re.compile(r"\b(?:union|except|intersect)\b", re.IGNORECASE)
# Predicados de EXCLUSÃO — a única forma de uma lista de supressão "contar" (§4.1).
_EXCLUSAO = re.compile(
    r"\bnot\s+exists\b|\bnot\s+in\b|\bnot\s+like\b|\bnot\s*\(|\bis\s+null\b"
    r"|\bis\s+false\b|\bis\s+not\s+true\b|=\s*0\b|=\s*false\b|<>\s*(?:1|true)\b"
    r"|!=\s*(?:1|true)\b",
    re.IGNORECASE,
)
# Pertinência a conjunto SEM negação: EXISTS/IN "positivo" seleciona os suprimidos.
_CONJUNTO = re.compile(r"\bexists\b|\bin\s*\(", re.IGNORECASE)
# Opt-in invertido: mira em quem NÃO consentiu (ou pediu para não ser incomodado).
# `[\w.]*` cobre o alias da tabela: `NOT c.opt_in_email` nega tanto quanto `NOT opt_in`.
_OPT_IN_NEGADO = re.compile(
    r"\bnot\s+[\w.]*opt_in\w*|\bopt_in\w*\s*(?:=\s*(?:0|false)|<>\s*(?:1|true)"
    r"|!=\s*(?:1|true)|is\s+null|is\s+false|is\s+not\s+true)\b",
    re.IGNORECASE,
)
_LITERAL_OU_NUMERO = re.compile(r"(-?\d+|'[^']*')\s*(=|<>|!=)\s*(-?\d+|'[^']*')")


# ------------------------------------------------------------ higienização (camada 1)
def _sem_comentarios(sql: str) -> str:
    """Remove comentários `--` e `/* */` RESPEITANDO literais (um `--` dentro de
    `'promo--5g'` é dado, não comentário). Sem isso, `-- blacklist fraude ...`
    'satisfazia' o Guard sem filtrar ninguém (UAT5 · achado 1c)."""
    saida: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch == "'":  # literal: copia inteiro (com '' escapado) e segue
            j = i + 1
            while j < n:
                if sql[j] == "'":
                    if sql[j + 1 : j + 2] == "'":
                        j += 2
                        continue
                    break
                j += 1
            saida.append(sql[i : j + 1])
            i = j + 1
        elif sql.startswith("--", i):
            while i < n and sql[i] != "\n":
                i += 1
        elif sql.startswith("/*", i):
            fim = sql.find("*/", i + 2)
            saida.append(" ")
            i = n if fim == -1 else fim + 2
        else:
            saida.append(ch)
            i += 1
    return "".join(saida)


def _estados(texto: str) -> list[tuple[int, bool]]:
    """Por caractere: (profundidade de parênteses, está dentro de literal?).

    É o que permite falar em "topo": AND/OR/WHERE só valem em profundidade 0 e fora
    de literal — dentro de subconsulta ou de `'...'` são texto, não estrutura."""
    estados: list[tuple[int, bool]] = []
    profundidade, em_literal, escapado = 0, False, False
    for i, ch in enumerate(texto):
        if escapado:  # segundo apóstrofo de um '' dentro do literal
            escapado = False
            estados.append((profundidade, True))
            continue
        if em_literal:
            estados.append((profundidade, True))
            if ch == "'":
                if texto[i + 1 : i + 2] == "'":
                    escapado = True
                else:
                    em_literal = False
            continue
        if ch == "'":
            em_literal = True
            estados.append((profundidade, True))
        elif ch == "(":
            estados.append((profundidade, False))
            profundidade += 1
        elif ch == ")":
            profundidade = max(0, profundidade - 1)
            estados.append((profundidade, False))
        else:
            estados.append((profundidade, False))
    return estados


def _marcos_de_topo(texto: str, padrao: re.Pattern[str]) -> list[re.Match[str]]:
    """Ocorrências do padrão em profundidade 0 e fora de literal."""
    estados = _estados(texto)
    return [m for m in padrao.finditer(texto) if estados[m.start()] == (0, False)]


def _quebrar_no_topo(texto: str, padrao: re.Pattern[str]) -> list[str]:
    """Fatia o texto nos marcos de topo (subconsultas e literais ficam inteiros)."""
    partes: list[str] = []
    inicio = 0
    for marco in _marcos_de_topo(texto, padrao):
        partes.append(texto[inicio : marco.start()])
        inicio = marco.end()
    partes.append(texto[inicio:])
    return [p for p in partes if p.strip()]


def _desembrulhar(termo: str) -> str:
    """Tira parênteses externos redundantes: `((a OR b))` → `a OR b`."""
    atual = termo.strip()
    while atual.startswith("(") and atual.endswith(")"):
        estados = _estados(atual)
        if any(profundidade == 0 and not lit for profundidade, lit in estados[1:-1]):
            break  # o parêntese inicial fecha antes do fim: não é um embrulho só
        atual = atual[1:-1].strip()
    return atual


def _estrutura_do_predicado(texto: str) -> str:
    """Reduz a folha ao que ela AFIRMA NO PRÓPRIO NÍVEL: esvazia o conteúdo dos
    literais e o INTERIOR dos parênteses (os parênteses em si ficam).

    Duas razões, e as duas já foram evasão comprovada:
    - literais: as 7 listas moram legitimamente dentro deles (`s.lista IN ('blacklist',…)`),
      então a MENÇÃO é procurada no texto cru — mas o formato do predicado é lido aqui,
      senão `nome = 'blacklist not in optout'` se disfarça de exclusão (achado 1d);
    - subconsultas: um `IS NULL`/`= 0` inocente DENTRO do parêntese não nega nada no
      nível do predicado. Lendo a folha inteira, `EXISTS (… AND s.removido_em IS NULL)`
      passava por exclusão — o achado 1a de volta, com um predicado a mais. O que
      qualifica a folha é o operador de topo dela: `NOT EXISTS (`, `NOT IN (`, `= 0`."""
    estados = _estados(texto)
    return "".join(
        ch if profundidade == 0 and not (lit and ch != "'") else " "
        for ch, (profundidade, lit) in zip(texto, estados, strict=True)
    )


def _e_tautologia(termo: str) -> bool:
    """Termo sempre verdadeiro (`1=1`, `TRUE`, `'x'='x'`, `1<>0`): sob OR, apaga a
    cláusula inteira — foi a evasão `OR 1=1` do UAT5 (achado 1b)."""
    limpo = " ".join(_desembrulhar(termo).lower().split())
    if limpo in {"true", "1", "not false"}:
        return True
    comparacao = _LITERAL_OU_NUMERO.fullmatch(limpo)
    if comparacao is None:
        return False
    iguais = comparacao.group(1) == comparacao.group(3)
    return iguais if comparacao.group(2) == "=" else not iguais


def clausula_where(sql: str) -> str:
    """WHERE de TOPO já higienizado: sem comentários e sem o que vem depois do filtro.

    WHERE de subconsulta NÃO é o filtro da segmentação — só conta o de profundidade 0
    (§8-M5-A1). '' quando não há WHERE de topo."""
    texto = _sem_comentarios(sql or "")
    marcos = _marcos_de_topo(texto, _WHERE)
    if not marcos:
        return ""
    trecho = texto[marcos[0].end() :]
    fim = _marcos_de_topo(trecho, _FIM_DO_WHERE)
    return trecho[: fim[0].start()] if fim else trecho


@dataclass(frozen=True)
class AnaliseSql:
    """Motivo ESTRUTURADO do veredito (A1) — a UI/o 20b explicam, não decidem."""

    listas_cobertas: tuple[str, ...]
    listas_faltantes: tuple[str, ...]
    opt_in_ok: bool
    problemas: tuple[str, ...]


@dataclass
class _Ramo:
    """Veredito parcial de uma subexpressão booleana do WHERE (uso interno)."""

    citadas: set[str] = field(default_factory=set)  # listas mencionadas no ramo
    cobertas: set[str] = field(default_factory=set)  # listas EFETIVAMENTE excluídas
    invertidas: set[str] = field(default_factory=set)  # EXISTS/IN positivo (achado 1a)
    sob_or: set[str] = field(default_factory=set)  # citadas num OR que não restringe
    sem_predicado: set[str] = field(default_factory=set)  # só em igualdade/literal (1d)
    neutralizadas: list[str] = field(default_factory=list)  # apagadas por tautologia (1b)
    opt_in_ok: bool = False
    opt_in_invertido: bool = False


def _folha(predicado: str) -> _Ramo:
    """Predicado atômico: a lista só conta se estiver sob EXCLUSÃO (NOT EXISTS/NOT IN…).

    A MENÇÃO é procurada no texto cru (as listas moram dentro de literais no padrão
    legítimo `s.lista IN ('blacklist',…)`); o FORMATO, na estrutura de topo da folha
    (`_estrutura_do_predicado`) — assim nem `nome = 'blacklist not in optout'` (achado
    1d) nem `EXISTS (… AND s.removido_em IS NULL)` (achado 1a com disfarce) se
    disfarçam de exclusão.

    O opt-in segue a MESMA regra das listas: menção não é checagem. Só conta o que
    restringe no nível da folha — `'promo opt_in'` num literal e `opt_in = 1` dentro
    da subconsulta de supressão filtram tudo, menos a audiência (§8-M5)."""
    ramo = _Ramo()
    texto = predicado.lower()
    estrutura = _estrutura_do_predicado(predicado).lower()
    ramo.citadas = {lista for lista in SETE_LISTAS if lista in texto}
    if ramo.citadas:
        if _EXCLUSAO.search(estrutura):
            ramo.cobertas = set(ramo.citadas)
        elif _CONJUNTO.search(estrutura):
            ramo.invertidas = set(ramo.citadas)
        else:
            ramo.sem_predicado = set(ramo.citadas)
    if "opt_in" in estrutura:
        if _OPT_IN_NEGADO.search(estrutura):
            ramo.opt_in_invertido = True
        else:
            ramo.opt_in_ok = True
    return ramo


def _juntar(ramos: list[_Ramo]) -> _Ramo:
    """Acumula os achados de vários ramos (o que difere entre E/OU é decidido fora)."""
    total = _Ramo()
    for ramo in ramos:
        total.citadas |= ramo.citadas
        total.invertidas |= ramo.invertidas
        total.sob_or |= ramo.sob_or
        total.sem_predicado |= ramo.sem_predicado
        total.neutralizadas += ramo.neutralizadas
        total.opt_in_invertido = total.opt_in_invertido or ramo.opt_in_invertido
    return total


def _analisar_expressao(expressao: str) -> _Ramo:
    """Percorre a árvore booleana do WHERE respeitando a PRECEDÊNCIA do SQL.

    OR primeiro (liga menos que AND): `A AND B OR 1=1` é `(A AND B) OR 1=1` — ou seja,
    todo mundo. Num OR, a supressão só vale se TODOS os ramos a aplicarem; num AND,
    basta um. Sem isso, um `or 1=1` no fim da linha zeraria a supressão em silêncio."""
    texto = _desembrulhar(expressao)
    ramos = _quebrar_no_topo(texto, _OR)
    if len(ramos) > 1:
        if any(_e_tautologia(ramo) for ramo in ramos):  # X OR TRUE = TRUE: não filtra
            neutralizado = _Ramo(neutralizadas=[" ".join(texto.split())[:160]])
            neutralizado.citadas = {lista for lista in SETE_LISTAS if lista in texto.lower()}
            return neutralizado
        analisados = [_analisar_expressao(ramo) for ramo in ramos]
        total = _juntar(analisados)
        total.cobertas = set.intersection(*(ramo.cobertas for ramo in analisados))
        total.opt_in_ok = all(ramo.opt_in_ok for ramo in analisados)
        total.sob_or |= total.citadas - total.cobertas
        return total
    conjuncoes = _quebrar_no_topo(texto, _AND)
    if len(conjuncoes) > 1:
        analisados = [_analisar_expressao(conjuncao) for conjuncao in conjuncoes]
        total = _juntar(analisados)
        total.cobertas = set().union(*(ramo.cobertas for ramo in analisados))
        total.opt_in_ok = any(ramo.opt_in_ok for ramo in analisados)
        total.sob_or -= total.cobertas  # outra conjunção resolveu a lista
        return total
    return _folha(texto)


def analisar_sql(sql: str | None) -> AnaliseSql:
    """Camada 1 (§8-M5-A1): cada lista precisa de uma EXCLUSÃO EFETIVA no WHERE.

    Regras, todas determinísticas:
    - comentários fora antes de qualquer coisa (achado 1c);
    - precedência do SQL respeitada; termo sempre verdadeiro sob OR anula o ramo (1b);
    - lista citada em OR que não a exclui em TODOS os ramos não restringe ninguém;
    - lista em EXISTS/IN NÃO negado inverte o filtro — seleciona os suprimidos (1a);
    - lista só citada em igualdade/literal/projeção não é exclusão (1d/1e);
    - UNION/`;` de topo: só o primeiro SELECT é varrido — o resto contrabandearia gente;
    - opt-in tem de existir e não pode estar invertido (`opt_in = 0`).
    """
    if sql is None or not sql.strip():
        return AnaliseSql((), tuple(SETE_LISTAS), False, ("SQL público ausente — nada a varrer.",))
    higienizado = _sem_comentarios(sql)
    where = clausula_where(sql)
    if not where.strip():
        return AnaliseSql(
            (),
            tuple(SETE_LISTAS),
            False,
            ("SQL sem WHERE de topo: nenhuma supressão é aplicada à segmentação (§4.1).",),
        )

    total = _analisar_expressao(where)
    faltantes = tuple(lista for lista in SETE_LISTAS if lista not in total.cobertas)
    problemas: list[str] = []
    if total.invertidas:
        problemas.append(
            "EXISTS/IN NÃO negado sobre lista de supressão "
            f"({', '.join(sorted(total.invertidas))}): o filtro está invertido — esse SQL "
            "SELECIONA quem deveria ser suprimido. Use NOT EXISTS/NOT IN (§4.1)."
        )
    if total.neutralizadas:
        problemas.append(
            "Condição sempre verdadeira sob OR neutraliza a cláusula: "
            f"{'; '.join(total.neutralizadas)} — supressão e opt-in têm de ser "
            "conjunções (AND)."
        )
    if total.sob_or:
        problemas.append(
            f"Listas sob OR que não as exclui em todos os ramos: "
            f"{', '.join(sorted(total.sob_or))} — a exclusão precisa valer sempre (AND)."
        )
    if total.sem_predicado:
        problemas.append(
            f"Listas citadas fora de predicado de exclusão: "
            f"{', '.join(sorted(total.sem_predicado))} — menção em igualdade/literal/"
            "projeção não suprime ninguém."
        )
    if faltantes:
        problemas.append(f"WHERE não exclui as listas de supressão: {', '.join(faltantes)} (§4.1).")
    problemas += _problemas_estruturais(higienizado)
    if total.opt_in_invertido:
        problemas.append(
            "Checagem de opt-in INVERTIDA (opt_in = 0/false/null): a segmentação mira "
            "justamente quem não consentiu (§8-M5)."
        )
    elif not total.opt_in_ok:
        problemas.append("WHERE não verifica opt-in de canal (§8-M5).")
    return AnaliseSql(tuple(sorted(total.cobertas)), faltantes, total.opt_in_ok, tuple(problemas))


def _problemas_estruturais(higienizado: str) -> list[str]:
    """O que está FORA do WHERE varrido e ainda assim entra na audiência.

    `UNION`/`EXCEPT`/`INTERSECT` de topo colam um segundo SELECT sem supressão nenhuma;
    `;` abre outra instrução. A varredura é do primeiro SELECT — então o resto é
    recusado em vez de ignorado (fail-closed §1.1.3)."""
    problemas: list[str] = []
    if _marcos_de_topo(higienizado, _SET_OP):
        problemas.append(
            "Consulta com UNION/EXCEPT/INTERSECT de topo: o Guard varre o primeiro "
            "SELECT e os demais entrariam sem supressão — quebre em segmentos (§4.1)."
        )
    estados = _estados(higienizado)
    if any(
        ch == ";" and estados[i] == (0, False) and higienizado[i + 1 :].strip()
        for i, ch in enumerate(higienizado)
    ):
        problemas.append(
            "SQL público com mais de uma instrução (`;`): só a primeira é varrida (§4.1)."
        )
    return problemas


def listas_ausentes_no_where(sql: str) -> list[str]:
    """Das 7 listas (§4.1), as que o WHERE NÃO exclui (ordem de precedência)."""
    return list(analisar_sql(sql).listas_faltantes)


def opt_in_ausente_no_where(sql: str) -> bool:
    """Guard também exige checagem de opt-in no WHERE (§8-M5: '7 listas + opt-in')."""
    return not analisar_sql(sql).opt_in_ok


def problemas_no_sql(sql: str | None) -> tuple[list[str], list[str]]:
    """(listas_faltantes, problemas) do SQL — [] e [] quando o SQL está conforme."""
    analise = analisar_sql(sql)
    return list(analise.listas_faltantes), list(analise.problemas)


def problemas_nas_contagens(suprimidos: Mapping[str, int], liquido: int) -> list[str]:
    """Camada 2 (§8-M5-A1) — o veredito por NÚMEROS, não por texto.

    Se o dry-run diz que a cláusula "aprovada" cortou ZERO em TODAS as 7 listas e
    ainda sobrou audiência, a supressão não está funcionando (ou o SQL varrido não é
    o SQL contado): fail-closed. Camada 1 lê o que o SQL DIZ; esta lê o que ele FAZ —
    e só tem poder de fogo quando o read model executa de fato o SQL público."""
    if liquido <= 0:  # nada a disparar: não há risco a barrar
        return []
    if any(int(suprimidos.get(lista, 0)) > 0 for lista in SETE_LISTAS):
        return []
    return [
        f"Supressão ZERO nas 7 listas com {liquido} contatos líquidos: a cláusula de "
        "supressão não está surtindo efeito no dry-run (§4.1) — recontagem e SQL "
        "precisam ser revistos antes de certificar."
    ]


def validar_sql_de_segmentacao(sql: str | None) -> None:
    """Veredito por código (A1): 7 listas + opt-in obrigatórios no WHERE, senão reprova."""
    faltantes, problemas = problemas_no_sql(sql)
    if problemas:
        raise CertificadoReprovado(
            "Guard reprovou a certificação (§8-M5-A1): " + " · ".join(problemas),
            listas_faltantes=faltantes,
            problemas=problemas,
        )


def emitir_certificado(
    *,
    os_id: uuid.UUID,
    segmento_id: uuid.UUID,
    sql_publico: str | None,
    suprimidos: dict[str, int],
    liquido: int,
    agora: datetime,
    validade_horas: int = VALIDADE_HORAS_CERTIFICADO,
) -> CertificadoElegibilidade:
    """Emite `certificado_elegibilidade` (§4.1) com hash canônico + validade (A3).

    Hash = sha256 do JSON canônico (chaves ordenadas) de {os_id, segmento_id,
    sha256(sql), suprimidos, liquido, emitido_em} — reproduzível em auditoria.

    Antes de assinar, aplica a CAMADA 2 (`problemas_nas_contagens`): o certificado é o
    documento que autoriza o disparo, então o último portão olha o efeito medido da
    supressão, não só o texto do SQL (UAT5 · achado 1).
    """
    suprimidos_contagem: dict[str, int] = {
        lista: int(suprimidos.get(lista, 0)) for lista in SETE_LISTAS
    }
    problemas = problemas_nas_contagens(suprimidos_contagem, int(liquido))
    if problemas:
        raise CertificadoReprovado(
            "Guard reprovou a certificação (§8-M5-A1): " + " · ".join(problemas),
            listas_faltantes=list(SETE_LISTAS),
            problemas=problemas,
        )
    payload = {
        "os_id": str(os_id),
        "segmento_id": str(segmento_id),
        "sql_sha256": (
            hashlib.sha256(sql_publico.encode("utf-8")).hexdigest() if sql_publico else None
        ),
        "suprimidos": suprimidos_contagem,
        "liquido": int(liquido),
        "emitido_em": agora.isoformat(),
    }
    canonico = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return CertificadoElegibilidade(
        id=uuid.uuid4(),
        os_id=os_id,
        hash=hashlib.sha256(canonico.encode("utf-8")).hexdigest(),
        suprimidos=suprimidos_contagem,
        liquido=int(liquido),
        emitido_em=agora,
        valido_ate=agora + timedelta(hours=validade_horas),
        last_mile=None,  # re-varredura no disparo (M9/M10)
    )


def certificado_vigente(certificado: CertificadoElegibilidade, agora: datetime) -> bool:
    """True ⇔ dentro da validade. Helper para o portão de publish (M8/M9 — A3)."""
    return certificado.valido_ate is not None and agora <= certificado.valido_ate


def exigir_certificado_vigente(certificado: CertificadoElegibilidade, agora: datetime) -> None:
    """Publish (M8/M9) chama este helper: certificado expirado → CertificadoExpirado (A3)."""
    if not certificado_vigente(certificado, agora):
        raise CertificadoExpirado(
            f"Certificado {certificado.hash[:12]} expirado em "
            f"{certificado.valido_ate.isoformat() if certificado.valido_ate else '—'} "
            "(§8-M5-A3): recertifique a audiência antes do publish."
        )
