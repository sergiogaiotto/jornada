#!/usr/bin/env python3
"""Smoke FUNCIONAL pós-deploy (§13) — exercita o caminho crítico contra a VPS no ar.

O smoke A22 do CI prova a VERSÃO (`/healthz.sha` == SHA do run) e foi ele que pegou o
"deploy-fantasma" de 2026-08-05. O que ele NÃO pega é "deployou a versão certa e a
aplicação está quebrada": foi assim que o HTTP 500 do simulador (achado D07) ficou vivo
em produção sem ninguém notar. Este script fecha a lacuna — sobe uma jornada do zero
pela API pública e sai != 0 quando qualquer passo quebra, derrubando o deploy.

Roteiro (cada passo diz QUAL passo quebrou e o corpo da resposta):
  1. `GET /healthz` — `db=ok` e `sha` == SHA do run (A22, reconfirmado aqui).
  2. `POST /os` — OS marcada `SMOKE <sha>`, código `SMOKE-<sha>-<carimbo>`.
  3. `GET /datacloud/segmentos` + `POST /datacloud/segmentos/{id}/usar` — segmento com
     contagem líquida; sem ele o Ensaio Geral é 409 (§6: entrada = JGC + segmento + ...).
  4. `POST /os/{id}/jornada` (esqueleto) + `PUT /jornadas/{id}/grafo` — grafo válido §5.3
     com `decisionSplit` roteado SÓ por `regras[].to` (o caso do achado 3) e `wait` ISO.
  5. `POST /jornadas/{id}/simular` — 200 com P10/P50/P90 (onde o 500 do D07 aparecia).
  6. `GET /jornadas/{id}/export?formato=json|xml` — 200 nos dois e NENHUM `decisionSplit`
     com `outcomes` vazio (regressão do achado 3: o compilador/export descartava o
     roteamento por regra e o Decision Split chegava ao Journey Builder sem saída).
  7. Caso NEGATIVO: `wait.duracao` fora do ISO-8601 → 422 com `regra=duracao_invalida`
     — prova que a validação (§5.3 / emenda D03) está VIVA, não só que a API sobe.

Passos 1–5 são fail-fast (sem eles não há o que assertar); 6 e 7 acumulam falhas e o
script sai 1 no fim com TODAS listadas — export torto não pode esconder validação morta.

Resíduo e limpeza: o smoke roda no tenant da CREDENCIAL. Um tenant isolado (`smoke-ci`)
seria o ideal, mas desde a correção do achado 5 do UAT #5 o escopo vem do portador
autenticado e o `X-Tenant` divergente é recusado com 403 — o resíduo cai no mesmo tenant
da demo, e a única defesa honesta é MARCAR. A API não tem DELETE de OS e nenhum endpoint
é inventado aqui (§1.3.5): a OS nasce com nome `SMOKE <sha>` e código `SMOKE-<sha>-<ts>`,
e a limpeza é uma linha no banco (a `codigo` NÃO consome a sequência `OS-{ano}-{seq}`,
então a numeração da demo fica intacta):

    DELETE FROM os WHERE codigo LIKE 'SMOKE-%';   -- cascata §4.1 leva jornadas/segmentos

Quando existir um token de serviço para um tenant próprio, `--tenant`/`--token` movem o
smoke para fora da demo sem tocar neste código.

Idempotente: o código da OS carrega SHA + carimbo UTC + sufixo aleatório, então duas
execuções seguidas nunca colidem em `CodigoDuplicado` (§4.1) — nem no mesmo segundo.

Dependências: só a stdlib — o job de deploy do CI não instala o requirements.txt.
Segredos: nenhum novo. URL pública + token estático de dev (§8-M0), os mesmos que o
smoke A22 já usa.

Uso:
    python scripts/smoke_funcional.py --base-url http://host:8050 --sha abc1234
"""

import argparse
import json
import sys
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from xml.etree import ElementTree

BASE_URL_PADRAO = "http://vps.falagaiotto.com.br:8050"
# O tenant TEM de casar com o do portador: desde a correção do achado 5 (UAT #5) o
# escopo vem da credencial e `X-Tenant` divergente é 403 (§8). Trocar de tenant exige
# trocar de token junto — por isso os dois são parâmetros.
TENANT_PADRAO = "torre-movel"
TOKEN_PADRAO = "dev-analista"  # papel `analista` = Escritor das mutações (§8-M0)
TIMEOUT_PADRAO = 20.0
TIMEOUT_SIMULAR = 90.0  # Monte Carlo (§6) é o passo mais caro do roteiro

# Ensaio Geral enxuto: o achado D07 era travessia de grafo, indiferente a N e K (§6) —
# o smoke roda o caminho, não a estatística; o orçamento do CI é ~2min no total.
RUNS_SMOKE = 50
N_PERSONAS_SMOKE = 1000

LIMITE_CORPO = 900  # recorte do corpo nas mensagens de falha (debug sem despejar tudo)


class PassoFalhou(Exception):
    """Falha de um passo — a mensagem carrega passo, motivo e o corpo da resposta."""


@dataclass(frozen=True)
class Resposta:
    status: int
    corpo: bytes

    @property
    def texto(self) -> str:
        return self.corpo.decode("utf-8", errors="replace")

    def resumo(self) -> str:
        texto = self.texto.strip()
        return texto[:LIMITE_CORPO] + ("… [truncado]" if len(texto) > LIMITE_CORPO else "")

    def json(self, passo: str) -> Any:
        try:
            return json.loads(self.corpo)
        except json.JSONDecodeError as exc:
            raise falha(passo, f"resposta não é JSON ({exc})", self) from exc


def falha(passo: str, motivo: str, resposta: Resposta | None = None) -> PassoFalhou:
    """Mensagem de falha no formato que o próximo debug precisa: passo + motivo + corpo."""
    partes = [f"[{passo}] {motivo}"]
    if resposta is not None:
        partes.append(f"HTTP {resposta.status}")
        partes.append(f"corpo: {resposta.resumo()}")
    return PassoFalhou(" · ".join(partes))


class Cliente:
    """HTTP mínimo sobre urllib (§8: `X-Tenant` + `Authorization: Bearer` em /api/v1)."""

    def __init__(self, base_url: str, *, tenant: str, token: str) -> None:
        self._base = base_url.rstrip("/")
        self.tenant = tenant
        self._token = token

    def chamar(
        self,
        passo: str,
        metodo: str,
        caminho: str,
        *,
        corpo: Any = None,
        timeout: float = TIMEOUT_PADRAO,
    ) -> Resposta:
        """Devolve a Resposta mesmo em 4xx/5xx (o corpo problem+json é a prova do achado);
        só erro de TRANSPORTE (conexão/timeout) vira falha imediata."""
        url = f"{self._base}{caminho}"
        dados = json.dumps(corpo).encode("utf-8") if corpo is not None else None
        requisicao = urllib.request.Request(url, data=dados, method=metodo)
        requisicao.add_header("X-Tenant", self.tenant)
        requisicao.add_header("Authorization", f"Bearer {self._token}")
        if dados is not None:
            requisicao.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(requisicao, timeout=timeout) as resposta:
                return Resposta(int(resposta.status), resposta.read())
        except urllib.error.HTTPError as erro:
            return Resposta(int(erro.code), erro.read())
        except (urllib.error.URLError, TimeoutError, OSError) as erro:
            raise falha(passo, f"{metodo} {url} não respondeu em {timeout:g}s: {erro}") from erro


def exigir(passo: str, resposta: Resposta, esperado: int, o_que: str) -> Resposta:
    if resposta.status != esperado:
        raise falha(passo, f"{o_que}: esperado HTTP {esperado}, veio {resposta.status}", resposta)
    return resposta


# --------------------------------------------------------------------- O grafo do smoke


def grafo_smoke() -> dict[str, Any]:
    """JGC §5 mínimo que cobre o achado 3: `n3` é um `decisionSplit` cujas saídas existem
    SÓ em `regras[].to` (nenhuma `edge` parte dele) — a forma que o Flow gera e que o
    compilador/export descartava. Inclui `wait` ISO-8601 (§5.2) e `goal` (§5.3 exige).

    `meta.osCodigo`/`meta.tenant` são sobrescritos pelo servidor (§1.3.5: escopo nunca
    vem do cliente); ficam aqui só para o grafo ser legível fora da API.
    """
    return {
        "jgcVersion": "1.0",
        "meta": {"osCodigo": "SMOKE", "tenant": "smoke", "reentrada": "nao"},
        "nodes": [
            {
                "id": "n1",
                "type": "entrySource",
                "data": {"deRef": "DE_smoke_entrada", "modo": "fire_once", "reentrada": "nao"},
            },
            {
                "id": "n2",
                "type": "channel.email",
                "data": {"assetRef": "asset-smoke-email", "optIn": True},
            },
            {
                "id": "n3",
                "type": "decisionSplit",
                "data": {
                    "regras": [
                        {"expr": "abriu_email == false", "to": "n4"},
                        {"expr": "senao", "to": "n5"},
                    ]
                },
            },
            {"id": "n4", "type": "wait", "data": {"duracao": "PT24H"}},
            {"id": "n5", "type": "wait", "data": {"duracao": "P1D"}},
            {
                "id": "n6",
                "type": "goal",
                "data": {"metrica": "conversao", "deRef": "DE_smoke_conversao"},
            },
        ],
        "edges": [
            {"id": "e1", "from": "n1", "to": "n2"},
            {"id": "e2", "from": "n2", "to": "n3"},
            {"id": "e3", "from": "n4", "to": "n6"},
            {"id": "e4", "from": "n5", "to": "n6"},
        ],
    }


def grafo_invalido() -> dict[str, Any]:
    """O MESMO grafo com `wait.duracao` fora do ISO-8601 — a forma exata que o gpt-oss-120b
    real produziu no UAT #4 e que a emenda D03 passou a recusar (§5.2/§5.3)."""
    grafo = json.loads(json.dumps(grafo_smoke()))
    for no in grafo["nodes"]:
        if no["id"] == "n4":
            no["data"]["duracao"] = "imediato_apos_quiet_hours"
    return grafo


# ------------------------------------------------------------------------------ Passos


def passo_1_healthz(cliente: Cliente, sha_esperado: str | None) -> None:
    passo = "1/7 healthz"
    resposta = exigir(passo, cliente.chamar(passo, "GET", "/healthz"), 200, "GET /healthz")
    saude = resposta.json(passo)
    if saude.get("db") != "ok":
        raise falha(passo, f"db={saude.get('db')!r} (esperado 'ok' — §8-M0-A1)", resposta)
    sha_no_ar = str(saude.get("sha", ""))
    if sha_esperado and sha_no_ar != sha_esperado:
        raise falha(
            passo,
            f"version-stamp (A22): o ar responde {sha_no_ar!r}, esperado {sha_esperado!r} — "
            "deploy-fantasma",
            resposta,
        )
    print(f"  ok  db=ok · sha={sha_no_ar} · llm={saude.get('llm')}")


def passo_2_criar_os(cliente: Cliente, sha: str) -> dict[str, Any]:
    passo = "2/7 criar OS"
    # Idempotência (§4.1: `codigo` é unique e a checagem é GLOBAL): carimbo UTC + sufixo
    # aleatório. Só o carimbo por segundo NÃO basta — duas execuções seguidas no mesmo
    # segundo colidiam em `CodigoDuplicado` (409), medido antes de chegar aqui.
    carimbo = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    codigo = f"SMOKE-{sha or 'local'}-{carimbo}-{uuid.uuid4().hex[:6]}"
    resposta = cliente.chamar(
        passo,
        "POST",
        "/api/v1/os",
        corpo={
            "nome": f"SMOKE {sha or 'local'}",
            "tshirt": "P",
            "codigo": codigo,
            "briefing": {"objetivo": "smoke funcional pós-deploy (§13) — descartável"},
        },
    )
    if resposta.status in (400, 401, 403, 404):
        raise falha(
            passo,
            f"POST /api/v1/os recusado — tenant={cliente.tenant!r} precisa ser o MESMO do "
            "portador do token (§8, achado 5): ajuste --tenant/--token juntos",
            resposta,
        )
    exigir(passo, resposta, 201, "POST /api/v1/os")
    os_ = resposta.json(passo)
    print(f"  ok  OS {os_['codigo']} · id={os_['id']}")
    return dict(os_)


def passo_3_segmento(cliente: Cliente, os_id: str) -> None:
    """§6: o Ensaio Geral exige segmento com contagem líquida — sem ele, 409. Caminho
    100% determinístico (Data Cloud por fixtures §11.2, ZERO LLM §10.6)."""
    passo = "3/7 segmento"
    resposta = exigir(
        passo,
        cliente.chamar(passo, "GET", "/api/v1/datacloud/segmentos"),
        200,
        "GET /api/v1/datacloud/segmentos",
    )
    segmentos = resposta.json(passo)
    if not segmentos:
        raise falha(passo, "Data Cloud não devolveu nenhum segmento (§11.2)", resposta)
    dc_id = str(segmentos[0]["id"])
    resposta = exigir(
        passo,
        cliente.chamar(
            passo, "POST", f"/api/v1/datacloud/segmentos/{dc_id}/usar", corpo={"os_id": os_id}
        ),
        201,
        f"POST /api/v1/datacloud/segmentos/{dc_id}/usar",
    )
    segmento = resposta.json(passo)
    liquido = segmento.get("contagem_liquida")
    if not liquido:
        raise falha(passo, f"segmento sem contagem líquida (={liquido!r}) — §6", resposta)
    print(f"  ok  segmento {dc_id} · líquido={liquido}")


def passo_4_jornada(cliente: Cliente, os_id: str) -> str:
    passo = "4/7 jornada"
    resposta = exigir(
        passo,
        cliente.chamar(passo, "POST", f"/api/v1/os/{os_id}/jornada"),
        201,
        f"POST /api/v1/os/{os_id}/jornada (esqueleto §5.2)",
    )
    jornada_id = str(resposta.json(passo)["jornada"]["id"])
    resposta = exigir(
        passo,
        cliente.chamar(
            passo, "PUT", f"/api/v1/jornadas/{jornada_id}/grafo", corpo={"grafo": grafo_smoke()}
        ),
        200,
        f"PUT /api/v1/jornadas/{jornada_id}/grafo (grafo válido §5.3)",
    )
    corpo = resposta.json(passo)
    custo = corpo["jornada"].get("custo_projetado")
    if not custo:  # taxímetro A2: canal + volume ⇒ custo > 0; R$ 0,00 é o achado 7
        raise falha(passo, f"taxímetro devolveu custo_projetado={custo!r} (A2)", resposta)
    print(f"  ok  jornada {jornada_id} · versão {corpo['jornada']['versao']} · custo={custo}")
    return jornada_id


def passo_5_simular(cliente: Cliente, jornada_id: str) -> None:
    passo = "5/7 simular"
    resposta = exigir(
        passo,
        cliente.chamar(
            passo,
            "POST",
            f"/api/v1/jornadas/{jornada_id}/simular",
            corpo={"runs": RUNS_SMOKE, "n_personas": N_PERSONAS_SMOKE},
            timeout=TIMEOUT_SIMULAR,
        ),
        200,
        f"POST /api/v1/jornadas/{jornada_id}/simular (§6 — aqui o 500 do D07 aparecia)",
    )
    simulacao = resposta.json(passo).get("simulacao") or {}
    for metrica in ("conversoes", "custo", "receita"):
        faixa = simulacao.get(metrica) or {}
        faltando = [p for p in ("p10", "p50", "p90") if p not in faixa]
        if faltando:
            raise falha(passo, f"simulacao.{metrica} sem percentis {faltando} (§6)", resposta)
    print(
        f"  ok  P50 conversões={simulacao['conversoes']['p50']} · "
        f"custo={simulacao['custo']['p50']} · semáforo={simulacao.get('semaforo')}"
    )


def passo_6_export(cliente: Cliente, jornada_id: str) -> list[str]:
    """Achado 3: o export herdava a cópia inline do compilador (só `edges`) e o Decision
    Split chegava ao Journey Builder com `outcomes: []` — push/SMS/WhatsApp órfãos, sem
    aviso nenhum. Aqui isso é erro de deploy."""
    passo = "6/7 export"
    falhas: list[str] = []

    resposta = cliente.chamar(passo, "GET", f"/api/v1/jornadas/{jornada_id}/export?formato=json")
    if resposta.status != 200:
        falhas.append(str(falha(passo, "export JSON não devolveu 200", resposta)))
    else:
        interaction = resposta.json(passo)
        vazios = [
            str(a.get("key"))
            for a in interaction.get("activities") or []
            if a.get("type") == "decisionSplit" and not a.get("outcomes")
        ]
        if vazios:
            falhas.append(
                f"[{passo}] export JSON: decisionSplit com `outcomes` vazio em {vazios} — "
                "o roteamento por `regras[].to` foi descartado (achado 3 · §5.4)"
            )

    resposta = cliente.chamar(passo, "GET", f"/api/v1/jornadas/{jornada_id}/export?formato=xml")
    if resposta.status != 200:
        falhas.append(str(falha(passo, "export XML não devolveu 200", resposta)))
    else:
        try:
            raiz = ElementTree.fromstring(resposta.texto)  # XML do próprio serviço
        except ElementTree.ParseError as erro:
            falhas.append(str(falha(passo, f"export XML não é XML válido ({erro})", resposta)))
        else:
            vazios = [
                str(atividade.get("key"))
                for atividade in raiz.iter("Activity")
                if atividade.get("type") == "decisionSplit"
                and len(list(atividade.findall("./Outcomes/Outcome"))) == 0
            ]
            if vazios:
                falhas.append(
                    f"[{passo}] export XML: <Activity type=decisionSplit> sem <Outcome> em "
                    f"{vazios} — mesmo achado 3 pela porta do XSD (§5.4)"
                )
    if not falhas:
        print("  ok  export json e xml com decisionSplit roteado")
    return falhas


def passo_7_negativo(cliente: Cliente, jornada_id: str) -> list[str]:
    """Sem este passo o smoke provaria só que a API SOBE. Grafo torto tem de ser recusado
    com 422 apontando o nó (§5.3 · A1/A3): validação morta é falso verde."""
    passo = "7/7 negativo"
    resposta = cliente.chamar(
        passo, "PUT", f"/api/v1/jornadas/{jornada_id}/grafo", corpo={"grafo": grafo_invalido()}
    )
    if resposta.status != 422:
        return [
            str(
                falha(
                    passo,
                    "grafo com `wait.duracao` fora do ISO-8601 deveria dar 422 (§5.3/D03) — "
                    "a validação está morta ou o erro virou 500 cru",
                    resposta,
                )
            )
        ]
    erros = resposta.json(passo).get("erros") or []
    if not any(e.get("regra") == "duracao_invalida" and e.get("no") == "n4" for e in erros):
        return [
            f"[{passo}] 422 veio sem `{{no: n4, regra: duracao_invalida}}` em `erros` — "
            f"o retry §7.3 depende desse formato. Corpo: {resposta.resumo()}"
        ]
    print("  ok  grafo inválido recusado com 422 apontando o nó n4")
    return []


# -------------------------------------------------------------------------------- Main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke funcional pós-deploy (§13).")
    parser.add_argument("--base-url", default=BASE_URL_PADRAO)
    parser.add_argument("--sha", default="", help="SHA curto esperado em /healthz (A22).")
    parser.add_argument("--tenant", default=TENANT_PADRAO)
    parser.add_argument("--token", default=TOKEN_PADRAO)
    args = parser.parse_args(argv)

    cliente = Cliente(args.base_url, tenant=args.tenant, token=args.token)
    print(f"smoke funcional · {args.base_url} · tenant={args.tenant}")
    falhas: list[str] = []
    try:
        passo_1_healthz(cliente, args.sha or None)
        os_ = passo_2_criar_os(cliente, args.sha)
        passo_3_segmento(cliente, str(os_["id"]))
        jornada_id = passo_4_jornada(cliente, str(os_["id"]))
        passo_5_simular(cliente, jornada_id)
        # 6 e 7 ACUMULAM: export torto não pode esconder validação morta.
        falhas.extend(passo_6_export(cliente, jornada_id))
        falhas.extend(passo_7_negativo(cliente, jornada_id))
    except PassoFalhou as erro:
        print(f"FALHOU: {erro}", file=sys.stderr)
        return 1

    if falhas:
        for mensagem in falhas:
            print(f"FALHOU: {mensagem}", file=sys.stderr)
        return 1
    print(f"smoke funcional OK · resíduo marcado `{os_['codigo']}` (limpeza: ver docstring)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
