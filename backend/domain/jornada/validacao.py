"""Serviço `jgc_validate` (§5.3) — executa a cada save; CÓDIGO PURO, zero LLM/I-O.

Fonte da verdade estrutural: `jgc.schema.json` (§5) — este módulo LÊ o schema (tipos
fechados de `$defs.node.properties.type.enum` e campos obrigatórios de `$defs.data.*`)
e o aplica; nenhum tipo/campo é duplicado em código.

Erros BLOQUEANTES (§5.3), cada um `{no, regra, mensagem}` apontando o nó (A1):
nó órfão/braço sem destino · `channel.*` sem opt-in configurado · soma de pcts ≠ 100 ·
holdout ausente quando experimento pré-registrado · `reentrada != nao` com holdout
(quebra o experimento) e/ou com experimento travado (A3 — contrato de re-entrada) ·
throttle acima do cap da política · wait que ultrapassa a janela da oferta · grafo sem
`goal`. Warnings (§5.3: custo>budget, pressão>cap) são calculados no serviço/simulador.
"""

import json
import re
from functools import cache
from pathlib import Path
from typing import Any

from domain.jornada.adjacencia import saidas_do_grafo as _saidas

SCHEMA_PATH = Path(__file__).resolve().parent / "jgc.schema.json"

HOLDOUT_ID = "holdout"  # braço de randomSplit reservado ao holdout (§5.2/§5.3)
TIPOS_TERMINAIS: tuple[str, ...] = ("goal", "exit", "exception")

# A13 (UAT com gpt-oss-120b real): modelos geram arestas com aliases `source`/`target`
# — normalizados para o contrato §5.1 (`from`/`to`) ANTES de validar/persistir.
ALIASES_ARESTA: dict[str, str] = {"source": "from", "target": "to"}


def normalizar_arestas(grafo: Any) -> Any:
    """Normaliza aliases de aresta (`source`→`from`, `target`→`to`) — A13.

    Roda nas ENTRADAS (gerar/ajustar/PUT) antes do `jgc_validate`: o contrato interno
    e o hash canônico usam SEMPRE `from`/`to`; o alias é aceito na borda e descartado.
    Não muda nada quando o grafo já está no contrato (idempotente); entrada que não é
    grafo/aresta-objeto passa intacta (a validação estrutural aponta o erro)."""
    if not isinstance(grafo, dict) or not isinstance(grafo.get("edges"), list):
        return grafo
    grafo = dict(grafo)
    arestas: list[Any] = []
    for aresta in grafo["edges"]:
        if isinstance(aresta, dict) and any(a in aresta for a in ALIASES_ARESTA):
            aresta = dict(aresta)
            for alias, canonico in ALIASES_ARESTA.items():
                valor = aresta.pop(alias, None)
                if canonico not in aresta and valor is not None:
                    aresta[canonico] = valor
        arestas.append(aresta)
    grafo["edges"] = arestas
    return grafo


# ISO 8601 (subset usado pelo JGC §5.2: PnW/PnD/TnH/nM/nS)
_DURACAO = re.compile(
    r"^P(?:(?P<w>\d+)W)?(?:(?P<d>\d+)D)?"
    r"(?:T(?:(?P<h>\d+)H)?(?:(?P<m>\d+)M)?(?:(?P<s>\d+)S)?)?$"
)


@cache
def _schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


@cache
def tipos_de_no() -> tuple[str, ...]:
    """Lista FECHADA de tipos (§5.2) — direto do jgc.schema.json."""
    return tuple(_schema()["$defs"]["node"]["properties"]["type"]["enum"])


@cache
def _campos_obrigatorios(tipo: str) -> tuple[str, ...]:
    """Campos obrigatórios de `data` por tipo — do `$defs.data.*` do schema."""
    defs = _schema()["$defs"]["data"]
    chave = "channel" if tipo.startswith("channel.") else tipo
    definicao = defs.get(chave, {})
    obrigatorios = list(definicao.get("required", []))
    # `wait` exige duracao OU ate (anyOf) — tratado à parte em _validar_no
    return tuple(obrigatorios)


def duracao_em_dias(iso: str) -> float | None:
    """Duração ISO 8601 → dias (None quando não parseável)."""
    match = _DURACAO.match(iso.strip()) if isinstance(iso, str) else None
    if match is None or not any(match.groupdict().values()):
        return None
    g = {k: int(v or 0) for k, v in match.groupdict().items()}
    return g["w"] * 7 + g["d"] + g["h"] / 24 + g["m"] / 1440 + g["s"] / 86400


def _erro(no: str | None, regra: str, mensagem: str) -> dict[str, Any]:
    return {"no": no, "regra": regra, "mensagem": mensagem}


# ------------------------------------------------------------------- Estrutura
def _validar_estrutura(grafo: Any) -> list[dict[str, Any]]:
    erros: list[dict[str, Any]] = []
    if not isinstance(grafo, dict):
        return [_erro(None, "estrutura", "JGC deve ser um objeto JSON (§5.1).")]
    for campo in ("jgcVersion", "meta", "nodes", "edges"):
        if campo not in grafo:
            erros.append(_erro(None, "estrutura", f"Campo obrigatório ausente: {campo} (§5.1)."))
    if grafo.get("jgcVersion") not in (None, "1.0"):
        erros.append(
            _erro(None, "estrutura", f"jgcVersion não suportada: {grafo['jgcVersion']!r}.")
        )
    meta = grafo.get("meta")
    if isinstance(meta, dict):
        reentradas = _schema()["properties"]["meta"]["properties"]["reentrada"]["enum"]
        for campo in _schema()["properties"]["meta"]["required"]:
            if campo not in meta:
                erros.append(_erro(None, "estrutura", f"meta.{campo} é obrigatório (§5.1)."))
        if "reentrada" in meta and meta["reentrada"] not in reentradas:
            erros.append(
                _erro(None, "estrutura", f"meta.reentrada inválida: {meta['reentrada']!r} (§5.1).")
            )
    elif meta is not None:
        erros.append(_erro(None, "estrutura", "meta deve ser objeto (§5.1)."))

    vistos: set[str] = set()
    for no in grafo.get("nodes") or []:
        if not isinstance(no, dict) or not no.get("id"):
            erros.append(_erro(None, "estrutura", f"Nó sem id/objeto inválido: {no!r}."))
            continue
        no_id = str(no["id"])
        if no_id in vistos:
            erros.append(_erro(no_id, "estrutura", f"Id de nó duplicado: {no_id}."))
        vistos.add(no_id)
        erros.extend(_validar_no(no_id, no))
    for aresta in grafo.get("edges") or []:
        if not isinstance(aresta, dict):
            erros.append(
                _erro(None, "estrutura", f"Aresta deve ser objeto (§5.1 edges): {aresta!r}.")
            )
            continue
        # A13: from/to são OBRIGATÓRIOS (aliases source/target já foram normalizados
        # na entrada) — mensagem clara por campo alimenta o retry do flow (§7.3).
        rotulo = f"Aresta {aresta.get('id')!r}" if aresta.get("id") else f"Aresta {aresta!r}"
        for campo in ("id", "from", "to"):
            if not aresta.get(campo):
                erros.append(
                    _erro(
                        None,
                        "estrutura",
                        f"{rotulo} sem campo obrigatório `{campo}` (§5.1 edges — toda aresta "
                        "exige `id`, `from` e `to`; use exatamente esses nomes).",
                    )
                )
        # from/to devem apontar para nós EXISTENTES do grafo (A13 — §5.1/§5.3)
        for campo, papel in (("from", "parte de"), ("to", "aponta para")):
            destino = aresta.get(campo)
            if destino and str(destino) not in vistos:
                erros.append(
                    _erro(
                        str(aresta.get("from")) if str(aresta.get("from", "")) in vistos else None,
                        "estrutura",
                        f"{rotulo} {papel} nó inexistente: `{campo}`={destino!r} — todo "
                        "`from`/`to` deve referenciar o `id` de um nó do grafo (§5.1).",
                    )
                )
    return erros


def _validar_no(no_id: str, no: dict[str, Any]) -> list[dict[str, Any]]:
    erros: list[dict[str, Any]] = []
    tipo = no.get("type")
    if tipo not in tipos_de_no():  # §5.2: tipos FECHADOS — rejeita fora da lista
        erros.append(
            _erro(no_id, "tipo_de_no", f"Tipo de nó fora da lista fechada (§5.2): {tipo!r}.")
        )
        return erros
    data = no.get("data")
    if not isinstance(data, dict):
        return [_erro(no_id, "campo_obrigatorio", f"Nó {no_id} ({tipo}) sem objeto `data`.")]
    for campo in _campos_obrigatorios(tipo):
        if campo not in data:
            erros.append(
                _erro(
                    no_id,
                    "campo_obrigatorio",
                    f"Nó {no_id} ({tipo}) sem campo obrigatório `{campo}` (§5.2).",
                )
            )
    if tipo == "wait":
        if "duracao" not in data and "ate" not in data:  # anyOf do schema
            erros.append(
                _erro(
                    no_id, "campo_obrigatorio", f"Nó {no_id} (wait) exige `duracao` OU `ate` (§5.2)."
                )
            )
        elif "duracao" in data and duracao_em_dias(str(data["duracao"])) is None:
            # Emenda D03 (UAT #4): até aqui bastava a PRESENÇA de `duracao` — o formato
            # nunca era conferido. O gpt-oss-120b real produziu `"imediato_apos_quiet_
            # hours"`, que passou na validação, furou a regra `wait_alem_da_janela`
            # (que ignora duração não-parseável) e chegou torta no compilador SFMC.
            erros.append(
                _erro(
                    no_id,
                    "duracao_invalida",
                    f"Nó {no_id} (wait) com `duracao`={data['duracao']!r} fora do ISO-8601 "
                    "(§5.2) — use P1D, P2W, PT12H, PT30M.",
                )
            )
    return erros


# ------------------------------------------------------- Semântica (§5.3)
def _alcancaveis(entradas: list[str], saidas: dict[str, list[dict[str, Any]]]) -> set[str]:
    alcancados, fila = set(entradas), list(entradas)
    while fila:
        for aresta in saidas.get(fila.pop(), []):
            destino = str(aresta["to"])
            if destino not in alcancados:
                alcancados.add(destino)
                fila.append(destino)
    return alcancados


def tem_holdout(grafo: dict[str, Any]) -> bool:
    """Holdout = braço `holdout` (ou marcado `holdout:true`) em algum randomSplit (§5.2)."""
    for no in grafo.get("nodes") or []:
        if isinstance(no, dict) and no.get("type") == "randomSplit":
            for braco in no.get("data", {}).get("braços") or []:
                if isinstance(braco, dict) and (
                    str(braco.get("id", "")).lower() == HOLDOUT_ID or braco.get("holdout") is True
                ):
                    return True
    return False


def reentrada_efetiva(grafo: dict[str, Any]) -> str:
    """`meta.reentrada` (§5.1); entrySource.data.reentrada (§5.2) prevalece se presente."""
    for no in grafo.get("nodes") or []:
        if isinstance(no, dict) and no.get("type") == "entrySource":
            declarada = no.get("data", {}).get("reentrada")
            if declarada:
                return str(declarada)
    return str((grafo.get("meta") or {}).get("reentrada", "nao"))


def _validar_semantica(
    grafo: dict[str, Any],
    *,
    experimento_travado: bool,
    politica: dict[str, Any] | None,
    janela_oferta_dias: float | None,
) -> list[dict[str, Any]]:
    erros: list[dict[str, Any]] = []
    nos = {str(n["id"]): n for n in grafo.get("nodes") or [] if isinstance(n, dict) and n.get("id")}
    saidas = _saidas(grafo)
    politica = politica or {}

    # Arestas para nós inexistentes (braço sem destino válido)
    for origem, arestas in saidas.items():
        for aresta in arestas:
            if str(aresta["to"]) not in nos:
                erros.append(
                    _erro(
                        origem,
                        "braco_sem_destino",
                        f"Aresta {aresta.get('id')} do nó {origem} aponta para nó "
                        f"inexistente: {aresta['to']!r} (§5.3).",
                    )
                )
            if str(aresta.get("from")) not in nos:
                erros.append(
                    _erro(
                        None,
                        "no_orfao",
                        f"Aresta {aresta.get('id')} parte de nó inexistente: {aresta['from']!r}.",
                    )
                )

    entradas = [i for i, n in nos.items() if n.get("type") == "entrySource"]
    if not entradas:
        erros.append(_erro(None, "no_orfao", "Grafo sem entrySource (§5.2) — nada é alcançável."))
    alcancados = _alcancaveis(entradas, saidas)
    for no_id, no in nos.items():
        tipo = str(no.get("type", ""))
        if no_id not in alcancados:  # nó órfão (§5.3)
            erros.append(
                _erro(no_id, "no_orfao", f"Nó órfão: {no_id} ({tipo}) inalcançável da entrada.")
            )
        arestas_do_no = saidas.get(no_id, [])
        conds = {str(a.get("cond")) for a in arestas_do_no}
        if tipo not in TIPOS_TERMINAIS and not arestas_do_no:
            erros.append(
                _erro(
                    no_id,
                    "braco_sem_destino",
                    f"Nó {no_id} ({tipo}) sem aresta de saída (braço sem destino — §5.3).",
                )
            )
        if tipo == "randomSplit":
            bracos = [b for b in no.get("data", {}).get("braços") or [] if isinstance(b, dict)]
            soma = sum(float(b.get("pct", 0)) for b in bracos)
            if bracos and abs(soma - 100.0) > 1e-9:  # soma de pcts ≠ 100 (§5.3)
                erros.append(
                    _erro(
                        no_id,
                        "soma_pcts",
                        f"Soma dos pcts do randomSplit {no_id} = {soma:g} ≠ 100.",
                    )
                )
            for braco in bracos:
                if str(braco.get("id")) not in conds:  # A1: braço órfão
                    erros.append(
                        _erro(
                            no_id,
                            "braco_sem_destino",
                            f"Braço {braco.get('id')!r} do randomSplit {no_id} sem aresta de "
                            "destino (braço órfão — §5.3).",
                        )
                    )
        if tipo == "frequencySplit":
            for classe in no.get("data", {}).get("classes") or []:
                # Emenda D05 (UAT #4): comparava `str(classe)` — a repr do dict inteiro
                # (`"{'id': 'baixa', 'max': 2}"`) — contra as conds. Classe como objeto
                # (a forma do §5.2, com faixas) NUNCA casava, e o nó era impossível de
                # salvar. Casa por `id`, igual ao randomSplit; classe string segue valendo.
                rotulo = classe.get("id") if isinstance(classe, dict) else classe
                if str(rotulo) not in conds:
                    erros.append(
                        _erro(
                            no_id,
                            "braco_sem_destino",
                            f"Classe {rotulo!r} do frequencySplit {no_id} sem aresta de destino.",
                        )
                    )
        if tipo == "engagementSplit" and len(arestas_do_no) < 2:
            erros.append(
                _erro(
                    no_id,
                    "braco_sem_destino",
                    f"engagementSplit {no_id} exige os dois braços (engajou/não) com destino.",
                )
            )
        if tipo.startswith("channel."):
            if not no.get("data", {}).get("optIn"):  # §5.3: channel.* sem opt-in configurado
                erros.append(
                    _erro(
                        no_id,
                        "optin_ausente",
                        f"Nó {no_id} ({tipo}) sem opt-in configurado (§5.3).",
                    )
                )
            throttle = no.get("data", {}).get("throttlePorHora")
            cap = politica.get("throttle_max_por_hora")
            if throttle is not None and cap is not None and float(throttle) > float(cap):
                erros.append(
                    _erro(
                        no_id,
                        "throttle_acima_do_cap",
                        f"throttlePorHora={throttle:g} do nó {no_id} acima do cap da política "
                        f"({cap:g}/h — §5.3).",
                    )
                )
        if tipo == "wait" and janela_oferta_dias is not None:
            dias = duracao_em_dias(str(no.get("data", {}).get("duracao", "")))
            if dias is not None and dias > janela_oferta_dias:
                erros.append(
                    _erro(
                        no_id,
                        "wait_alem_da_janela",
                        f"Wait {no_id} de {dias:g}d ultrapassa a janela da oferta "
                        f"({janela_oferta_dias:g}d — §5.3).",
                    )
                )

    if not any(n.get("type") == "goal" for n in nos.values()):  # grafo sem goal (§5.3)
        erros.append(_erro(None, "sem_goal", "Grafo sem nó `goal` (§5.3)."))

    # Contrato de re-entrada (§5.3 + A3)
    reentrada = reentrada_efetiva(grafo)
    entrada_ref = entradas[0] if entradas else None
    if reentrada != "nao" and tem_holdout(grafo):
        erros.append(
            _erro(
                entrada_ref,
                "reentrada_com_holdout",
                f"reentrada={reentrada!r} com holdout no grafo quebra o experimento (§5.3) — "
                "use reentrada=nao.",
            )
        )
    if experimento_travado:
        if reentrada != "nao":  # A3: reentrada=qualquer_momento + experimento travado
            erros.append(
                _erro(
                    entrada_ref,
                    "reentrada_com_experimento",
                    f"reentrada={reentrada!r} com experimento pré-registrado TRAVADO viola o "
                    "contrato de re-entrada (§5.3/§8-M7-A3) — exigido reentrada=nao.",
                )
            )
        if not tem_holdout(grafo):  # §5.3: holdout ausente com experimento pré-registrado
            erros.append(
                _erro(
                    None,
                    "holdout_ausente",
                    "Experimento pré-registrado exige braço de holdout no grafo (§5.3).",
                )
            )
    return erros


def validar_grafo(
    grafo: Any,
    *,
    experimento_travado: bool = False,
    politica: dict[str, Any] | None = None,
    janela_oferta_dias: float | None = None,
) -> list[dict[str, Any]]:
    """Validação completa (estrutura pelo schema + semântica §5.3) — [] ⇔ grafo válido.

    Erros estruturais interrompem a semântica (grafo sem forma não tem semântica).
    """
    erros = _validar_estrutura(grafo)
    if erros:
        return erros
    return _validar_semantica(
        grafo,
        experimento_travado=experimento_travado,
        politica=politica,
        janela_oferta_dias=janela_oferta_dias,
    )
