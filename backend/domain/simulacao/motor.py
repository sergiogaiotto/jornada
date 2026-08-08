"""Motor Monte Carlo do Ensaio Geral (§6) — CÓDIGO PURO, determinístico por seed.

Execução: K runs sobre o JGC com relógio VIRTUAL (horas desde o início): waits somam a
duração; quiet hours (meta §5.1 ou política) empurram envios para o fim da janela;
throttle (`throttlePorHora`) adiciona o tempo médio de vazão; STO amostra a distribuição
de horários das personas dentro de `janelaHoras`; frequencySplit usa o mix de classes do
governor (coortes de personas §6) — cond/classe fora do mix vira AVISO, nunca zero mudo
(D08). O relógio virtual afeta TEMPO/gargalos; as taxas
(entrega/conversão) vêm dos priors × multiplicadores amostrados por run — por isso a
mesma seed reproduz os mesmos P10/P50/P90 (M8-A1) independente da hora de parede.

Premissas documentadas (viram `premissas` na saída):
- decisionSplit divide IGUAL entre regras (esperança neutra — mesma do taxímetro M7);
- conversão é atribuída no nó de canal (binomial sobre entregues); goal registra funil;
- holdout (braço `holdout` do randomSplit) não recebe envios; converte no orgânico;
- receita = conversões × ticket médio (briefing ou prior); ROAS = receita/custo;
- canal sem tarifa vigente → custo 0 + aviso (nunca inventa tarifa — §1.3.5).

Semáforo (§6, com a precedência do aceite §8-M8-A2 — ver CHANGELOG-SDD.md):
VERMELHO se ROAS P50 < 1 ou colisão crítica do governor (pressão por contato acima do
frequency_cap da política); AMARELO se poder estatístico insuficiente (n < n_minimo ou
poder < 0,8 — portão experimento fica VERMELHO) ou avisos (custo > verba); VERDE senão.
"""

import math
from decimal import Decimal
from typing import Any

from domain.jornada.adjacencia import saidas_do_grafo as _saidas
from domain.jornada.validacao import duracao_em_dias
from domain.simulacao.tipos import GeradorAleatorio

HOLDOUT_ID = "holdout"  # braço reservado (§5.2/§5.3 — mesmo contrato da validação M7)

_Z_ALFA_2 = 1.959964  # z de α=0,05 bilateral (poder do MDE)
_PODER_MINIMO = 0.80
_ESPERA_ATE_HORAS = 24.0  # premissa p/ wait por atributo (`ate`) sem distribuição

_CONDS_ENGAJOU = ("sim", "engajou", "true", "open", "click")


# ------------------------------------------------------------------ utilidades
def _percentil(ordenados: list[float], q: float) -> float:
    if not ordenados:
        return 0.0
    pos = (len(ordenados) - 1) * q
    base = int(pos)
    resto = pos - base
    if base + 1 < len(ordenados):
        return ordenados[base] + resto * (ordenados[base + 1] - ordenados[base])
    return ordenados[base]


def _p10_50_90(valores: list[float], casas: int = 4) -> dict[str, float]:
    ordenados = sorted(valores)
    return {
        "p10": round(_percentil(ordenados, 0.10), casas),
        "p50": round(_percentil(ordenados, 0.50), casas),
        "p90": round(_percentil(ordenados, 0.90), casas),
    }


def _phi(x: float) -> float:
    """CDF da normal padrão (erf da stdlib — sem dependências)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _clip(valor: float, minimo: float, maximo: float) -> float:
    return max(minimo, min(maximo, valor))


def _quiet_hours(grafo: dict[str, Any], politica: dict[str, Any]) -> tuple[float, float] | None:
    janela = (grafo.get("meta") or {}).get("quietHours") or politica.get("quiet_hours")
    if not isinstance(janela, dict) or not janela.get("inicio") or not janela.get("fim"):
        return None
    try:
        inicio = float(str(janela["inicio"]).split(":")[0])
        fim = float(str(janela["fim"]).split(":")[0])
    except ValueError:
        return None
    return inicio, fim


def _espera_quiet(hora: float, quiet: tuple[float, float] | None) -> float:
    """Horas até sair da janela de silêncio (0 se fora dela). Janela cruza a meia-noite."""
    if quiet is None:
        return 0.0
    inicio, fim = quiet
    h = hora % 24.0
    if inicio <= fim:  # janela no mesmo dia (ex.: 01:00–06:00)
        return (fim - h) if inicio <= h < fim else 0.0
    if h >= inicio:  # ex.: 20:00–08:00, envio às 22h → espera até 08:00
        return (24.0 - h) + fim
    if h < fim:
        return fim - h
    return 0.0


def _dividir_igual(volume: int, partes: int) -> list[int]:
    base, resto = divmod(volume, partes)
    return [base + (1 if i < resto else 0) for i in range(partes)]


def _multinomial(
    ger: GeradorAleatorio, volume: int, pesos: list[tuple[str, float]]
) -> dict[str, int]:
    """Multinomial por binomiais sequenciais (exata, determinística por seed)."""
    alocacao: dict[str, int] = {}
    restante_n = volume
    restante_p = sum(p for _, p in pesos)
    for chave, peso in pesos[:-1]:
        p = peso / restante_p if restante_p > 0 else 0.0
        n = ger.binomial(restante_n, p)
        alocacao[chave] = n
        restante_n -= n
        restante_p -= peso
    if pesos:
        alocacao[pesos[-1][0]] = restante_n
    return alocacao


# ------------------------------------------------------------------ motor
def simular(
    grafo: dict[str, Any],
    *,
    volume_entrada: int,
    personas: dict[str, Any],
    priors: dict[str, Any],
    tarifas: dict[str, Decimal],
    politica: dict[str, Any],
    ger: GeradorAleatorio,
    runs: int,
    ticket_medio: float,
    hora_inicio: float,
    experimento: dict[str, Any] | None = None,
    verba: float | None = None,
) -> dict[str, Any]:
    """K runs Monte Carlo sobre o JGC → saída §6 (funil, P10/P50/P90, poder, semáforo)."""
    nos: dict[str, dict[str, Any]] = {str(n["id"]): n for n in grafo.get("nodes") or []}
    saidas = _saidas(grafo)
    quiet = _quiet_hours(grafo, politica)
    caps: dict[str, Any] = dict(politica.get("frequency_cap") or {})
    incerteza = float(priors.get("incerteza_relativa", 0.15))
    p_organico = float(priors.get("conversao_organica", 0.0))
    canais_grafo = sorted(
        {
            str(n["type"]).split(".", 1)[1]
            for n in nos.values()
            if str(n["type"]).startswith("channel.")
        }
    )
    avisos: list[str] = []
    # Canal SEPARADO de `avisos`, e não um aviso "mais grave": `avisos` é list[str] sem
    # severidade, então enquanto os dois compartilharem a lista nenhum deles consegue
    # bloquear. A distinção existe para o §6 poder ter precedência (ver `_semaforo`).
    bloqueantes: list[str] = []
    for canal in canais_grafo:
        if canal not in tarifas:
            avisos.append(f"Canal {canal!r} sem tarifa vigente — custo 0 na simulação (§1.3.5).")

    coortes = personas.get("coortes") or []
    pesos_classe = [(str(c["classe"]), float(c["peso"])) for c in coortes]
    mult_personas = float(personas.get("mult_conversao_medio", 1.0))
    hora_pico = float((personas.get("horarios") or {}).get("pico", 20.0))
    desvio_horas = float((personas.get("horarios") or {}).get("desvio", 3.0))

    # D08 (P3 do UAT #5): cond/classe de frequencySplit que não casa com o mix do
    # governor NÃO pode zerar mudo — vira aviso (⇒ amarelo). Fora do loop de runs e
    # sem draw de RNG: a mesma seed segue reproduzindo os mesmos percentis (M8-A1).
    classes_mix = sorted(classe for classe, _ in pesos_classe)
    peso_da_classe = {classe: peso for classe, peso in pesos_classe}
    for no_id, no in nos.items():
        if str(no.get("type", "")) != "frequencySplit":
            continue
        conds = sorted({str(a.get("cond")) for a in saidas.get(no_id, []) if str(a["to"]) in nos})
        sem_classe = [c for c in conds if c not in classes_mix]
        sem_aresta = [c for c in classes_mix if c not in conds]
        if sem_classe:
            avisos.append(
                f"frequencySplit {no_id}: cond {', '.join(map(repr, sem_classe))} sem classe "
                f"no mix do governor {classes_mix} — volume 0 nesses braços em todos os runs "
                "(§6/D08: o que não casa vira aviso, nunca zero mudo)."
            )
        if sem_aresta:
            # A fração é MEDIDA, não adjetivada: "sai parte do volume" não permite ao
            # operador decidir nada. Com o número, amarelo vira informação.
            perdido = sum(peso_da_classe.get(c, 0.0) for c in sem_aresta)
            total = sum(peso_da_classe.values()) or 1.0
            avisos.append(
                f"frequencySplit {no_id}: classe {', '.join(map(repr, sem_aresta))} do mix do "
                "governor sem aresta correspondente — essa fração do volume sai do funil "
                f"neste nó ({perdido / total:.1%} do que chega, §6/D08)."
            )
        # D09 (§8-M8-A8): o caso EXTREMO do D08. Quando NENHUMA cond do nó casa com
        # NENHUMA classe do mix, não é "parte do volume": é 100% do que chega ao nó
        # evaporando em silêncio, e a jornada segue verde até o SFMC. Perda PARCIAL
        # continua amarela por decisão declarada (ver test_D09_perda_parcial).
        #
        # A condição é CAUSAL (interseção vazia entre conds e classes), nunca o sintoma
        # da saída: detectar por "funil todo zerado" daria falso positivo em holdout 100%
        # e falso NEGATIVO no instante em que 1 pessoa cair em 1 braço — 99,9% sumiria e
        # voltaria a amarelo, que é exatamente o buraco a tapar.
        if pesos_classe and conds and not (set(conds) & set(classes_mix)):
            bloqueantes.append(
                f"frequencySplit {no_id}: NENHUMA cond {conds} casa com o mix do governor "
                f"{classes_mix} — 100% do volume que chega a este nó sai do funil. "
                "A jornada não entrega nada (§6/D09)."
            )

    grau_base: dict[str, int] = dict.fromkeys(nos, 0)
    for arestas in saidas.values():
        for aresta in arestas:
            destino = str(aresta["to"])
            if destino in grau_base:
                grau_base[destino] += 1

    # séries por run
    s_funil: dict[str, list[float]] = {no_id: [] for no_id in nos}
    s_conversoes: list[float] = []
    s_custo: list[float] = []
    s_receita: list[float] = []
    s_roas: list[float] = []
    s_lift: list[float] = []
    s_holdout: list[float] = []
    s_tratado: list[float] = []
    s_horas: list[float] = []
    s_pressao: dict[str, list[float]] = {canal: [] for canal in canais_grafo}
    s_espera: dict[str, list[float]] = {no_id: [] for no_id in nos}

    for _ in range(runs):
        mult_run = {canal: _clip(ger.normal(1.0, incerteza), 0.4, 1.8) for canal in canais_grafo}
        mult_eng = _clip(ger.normal(1.0, incerteza), 0.4, 1.8)
        volumes: dict[str, int] = dict.fromkeys(nos, 0)
        tempo: dict[str, float] = dict.fromkeys(nos, 0.0)
        grau = dict(grau_base)
        for no_id, no in nos.items():
            if no.get("type") == "entrySource":
                volumes[no_id] = volume_entrada
        holdout_n = 0
        conv_canais = 0
        custo = Decimal(0)
        sends_canal: dict[str, int] = dict.fromkeys(canais_grafo, 0)
        espera_run: dict[str, float] = dict.fromkeys(nos, 0.0)

        fila = [i for i, g in grau.items() if g == 0]
        while fila:
            no_id = fila.pop()
            no, volume, chegada = nos[no_id], volumes[no_id], tempo[no_id]
            tipo = str(no.get("type", ""))
            arestas = [a for a in saidas.get(no_id, []) if str(a["to"]) in nos]
            atraso_local = 0.0
            alocacao: dict[int, int] | None = None  # índice da aresta → volume

            if tipo == "randomSplit":
                bracos = [b for b in no.get("data", {}).get("braços") or []]
                pesos = [(str(b["id"]), float(b.get("pct", 0))) for b in bracos]
                por_braco = _multinomial(ger, volume, pesos) if pesos else {}
                alocacao = {}
                for i, aresta in enumerate(arestas):
                    n_braco = por_braco.get(str(aresta.get("cond")), 0)
                    alocacao[i] = n_braco
                for braco in bracos:
                    eh_holdout = (
                        str(braco.get("id", "")).lower() == HOLDOUT_ID
                        or braco.get("holdout") is True
                    )
                    if eh_holdout:
                        holdout_n += por_braco.get(str(braco["id"]), 0)
            elif tipo == "engagementSplit":
                metrica = str(no.get("data", {}).get("metrica", "open"))
                p_eng = _clip(
                    float(priors.get("engajamento", {}).get(metrica, 0.3)) * mult_eng, 0.0, 1.0
                )
                engajados = ger.binomial(volume, p_eng)
                idx_sim = next(
                    (
                        i
                        for i, a in enumerate(arestas)
                        if str(a.get("cond", "")).lower() in _CONDS_ENGAJOU
                    ),
                    0,
                )
                alocacao = {}
                outros = [i for i in range(len(arestas)) if i != idx_sim]
                alocacao[idx_sim] = engajados
                partes_nao = _dividir_igual(volume - engajados, max(1, len(outros)))
                for i, parte in zip(outros, partes_nao, strict=False):
                    alocacao[i] = parte
            elif tipo == "frequencySplit":
                por_classe = _multinomial(ger, volume, pesos_classe) if pesos_classe else {}
                alocacao = {i: por_classe.get(str(a.get("cond")), 0) for i, a in enumerate(arestas)}
            elif tipo == "decisionSplit":
                partes = _dividir_igual(volume, max(1, len(arestas)))
                alocacao = dict(enumerate(partes))
            elif tipo == "wait":
                data = no.get("data", {})
                dias = duracao_em_dias(str(data.get("duracao", "")))
                atraso_local = (dias * 24.0) if dias is not None else _ESPERA_ATE_HORAS
            elif tipo == "sto":
                janela = float(no.get("data", {}).get("janelaHoras", 24))
                hora_alvo = ger.normal(hora_pico, desvio_horas) % 24.0
                espera = (hora_alvo - (hora_inicio + chegada)) % 24.0
                atraso_local = min(espera, janela)
            elif tipo.startswith("channel."):
                canal = tipo.split(".", 1)[1]
                data = no.get("data", {})
                atraso_local = _espera_quiet(hora_inicio + chegada, quiet)
                throttle = data.get("throttlePorHora")
                if throttle:
                    atraso_local += (volume / float(throttle)) / 2.0  # vazão média
                prior_canal = priors.get("canais", {}).get(canal, {})
                p_entrega = _clip(
                    float(prior_canal.get("entrega", 0.95)) * mult_run.get(canal, 1.0), 0.0, 1.0
                )
                p_conv = _clip(
                    float(prior_canal.get("conversao", 0.0))
                    * mult_personas
                    * mult_run.get(canal, 1.0),
                    0.0,
                    1.0,
                )
                entregues = ger.binomial(volume, p_entrega)
                conv_canais += ger.binomial(entregues, p_conv)
                custo += Decimal(volume) * tarifas.get(canal, Decimal(0))
                sends_canal[canal] = sends_canal.get(canal, 0) + volume

            espera_run[no_id] = atraso_local
            for i, aresta in enumerate(arestas):
                destino = str(aresta["to"])
                volumes[destino] += alocacao[i] if alocacao is not None else volume
                tempo[destino] = max(tempo[destino], chegada + atraso_local)
                grau[destino] -= 1
                if grau[destino] == 0:
                    fila.append(destino)

        n_tratado = max(0, volume_entrada - holdout_n)
        conv_org_tratado = ger.binomial(n_tratado, p_organico)
        conv_holdout = ger.binomial(holdout_n, p_organico)
        conversoes = conv_canais + conv_org_tratado
        taxa_tratado = conversoes / n_tratado if n_tratado else 0.0
        taxa_holdout = conv_holdout / holdout_n if holdout_n else 0.0
        receita = conversoes * ticket_medio
        custo_f = float(custo)

        for no_id in nos:
            s_funil[no_id].append(float(volumes[no_id]))
            s_espera[no_id].append(espera_run[no_id])
        s_conversoes.append(float(conversoes))
        s_custo.append(custo_f)
        s_receita.append(receita)
        if custo_f > 0:
            s_roas.append(receita / custo_f)
        s_lift.append((taxa_tratado - taxa_holdout) * 100.0)
        s_holdout.append(float(holdout_n))
        s_tratado.append(float(n_tratado))
        s_horas.append(max(tempo.values(), default=0.0))
        for canal in canais_grafo:
            s_pressao[canal].append(
                sends_canal.get(canal, 0) / volume_entrada if volume_entrada else 0.0
            )

    # ---------------------------------------------------------------- agregação
    funil = {
        no_id: {**_p10_50_90(serie, casas=1), "tipo": str(nos[no_id].get("type", ""))}
        for no_id, serie in s_funil.items()
    }
    roas_pcts = _p10_50_90(s_roas) if s_roas else None
    custo_pcts = _p10_50_90(s_custo, casas=2)
    pressao = {}
    colisao_critica = False
    for canal in canais_grafo:
        msgs = _p10_50_90(s_pressao[canal])
        cap = caps.get(canal)
        acima = cap is not None and msgs["p50"] > float(cap)
        colisao_critica = colisao_critica or acima
        pressao[canal] = {
            "msgs_por_contato": msgs,
            "cap_janela": cap,
            "colisao_critica": acima,
        }
    esperas_p50 = {
        no_id: round(_percentil(sorted(serie), 0.5), 2) for no_id, serie in s_espera.items()
    }
    candidatos_gargalo: list[dict[str, Any]] = [
        {"no": no_id, "tipo": str(nos[no_id].get("type", "")), "espera_horas_p50": espera}
        for no_id, espera in esperas_p50.items()
        if espera > 0
    ]
    gargalos = sorted(candidatos_gargalo, key=lambda g: -float(g["espera_horas_p50"]))[:5]

    poder = _poder(
        experimento,
        n_holdout=_percentil(sorted(s_holdout), 0.5),
        n_tratado=_percentil(sorted(s_tratado), 0.5),
        p_base=p_organico,
    )
    if verba is not None and custo_pcts["p50"] > verba:
        avisos.append(
            f"Custo P50 (R$ {custo_pcts['p50']:.2f}) acima da verba do briefing (R$ {verba:.2f})."
        )

    semaforo, motivos = _semaforo(
        roas_p50=roas_pcts["p50"] if roas_pcts else None,
        colisao_critica=colisao_critica,
        poder=poder,
        avisos=avisos,
        bloqueantes=bloqueantes,
    )

    return {
        "runs": runs,
        "n_personas": personas.get("n"),
        "volume_entrada": volume_entrada,
        "funil": funil,
        "conversoes": _p10_50_90(s_conversoes, casas=1),
        "custo": custo_pcts,
        "receita": _p10_50_90(s_receita, casas=2),
        "roas": roas_pcts,
        "lift_pp": _p10_50_90(s_lift),
        "horas_ate_concluir": _p10_50_90(s_horas, casas=1),
        "pressao_contato": pressao,
        "gargalos": gargalos,
        "poder": poder,
        "personas": personas,
        "semaforo": semaforo,
        "motivos_semaforo": motivos,
        "portoes": {"experimento": poder["portao"]},
        "avisos": avisos,
        "bloqueantes": bloqueantes,
        "premissas": [
            "decisionSplit divide igual entre regras (esperança neutra, como o taxímetro M7)",
            "conversão atribuída no nó de canal (binomial sobre entregues; priors v1)",
            f"holdout converte no orgânico ({p_organico:.3%}); lift = tratado − holdout (pp)",
            f"receita = conversões × ticket médio (R$ {ticket_medio:.2f})",
            "relógio virtual: waits/quiet hours/throttle/STO afetam tempo e gargalos",
        ],
    }


def _poder(
    experimento: dict[str, Any] | None,
    *,
    n_holdout: float,
    n_tratado: float,
    p_base: float,
) -> dict[str, Any]:
    """Validação de poder (§6: "lift esperado + validação de poder (n mínimo por MDE)").

    Poder do teste de duas proporções (aprox. normal, α=0,05 bilateral) para detectar o
    MDE pré-registrado; `n_disponivel` = braço limitante. §8-M8-A2: insuficiente ⇒
    portão experimento VERMELHO (a simulação fica amarela — regra no CHANGELOG-SDD.md).
    """
    if experimento is None:
        return {
            "aplicavel": False,
            "portao": "nao_aplicavel",
            "suficiente": None,
            "detalhe": "OS sem experimento pré-registrado (pré-registro pleno no M8/T9).",
        }
    n_minimo = int(experimento.get("n_minimo", 0))
    mde = float(experimento.get("mde_pp", 0.0)) / 100.0
    n1 = max(1.0, n_holdout)
    n2 = max(1.0, n_tratado)
    p2 = min(1.0, p_base + mde)
    se = math.sqrt(p_base * (1 - p_base) / n1 + p2 * (1 - p2) / n2)
    poder = _phi(mde / se - _Z_ALFA_2) if se > 0 else 0.0
    n_disponivel = int(min(n1, n2))
    suficiente = n_disponivel >= n_minimo and poder >= _PODER_MINIMO
    return {
        "aplicavel": True,
        "n_disponivel": n_disponivel,
        "n_minimo": n_minimo,
        "mde_pp": round(mde * 100.0, 2),
        "poder": round(poder, 4),
        "poder_minimo": _PODER_MINIMO,
        "suficiente": suficiente,
        "portao": "verde" if suficiente else "vermelho",
    }


def _semaforo(
    *,
    roas_p50: float | None,
    colisao_critica: bool,
    poder: dict[str, Any],
    avisos: list[str],
    bloqueantes: list[str],
) -> tuple[str, list[str]]:
    """Regra §6 (emendada pelos aceites §8-M8-A2 e §8-M8-A8 — CHANGELOG-SDD.md): vermelho
    bloqueia T9/T11; poder insuficiente pinta o PORTÃO de experimento de vermelho e a
    simulação de amarelo.

    A ORDEM aqui é o contrato, não estilo: `bloqueantes` entra em `motivos` ANTES do
    `return "vermelho"`. Anexá-los depois (junto de `avisos`) faria a mensagem aparecer
    sem que a cor mudasse — o modo de falha exato que o D08 tinha, em que nenhum aviso
    conseguia bloquear porque `avisos` é list[str] sem campo de severidade.
    """
    motivos: list[str] = []
    if roas_p50 is not None and roas_p50 < 1.0:
        motivos.append(f"ROAS P50 = {roas_p50:.2f} < 1 (§6).")
    if colisao_critica:
        motivos.append("Colisão crítica do governor: pressão de contato acima do cap (§6).")
    motivos.extend(bloqueantes)
    if motivos:
        return "vermelho", motivos
    if poder.get("aplicavel") and not poder.get("suficiente"):
        motivos.append(
            "Poder estatístico insuficiente para o MDE pré-registrado "
            f"(n disponível {poder.get('n_disponivel')} < n mínimo {poder.get('n_minimo')} "
            f"ou poder {poder.get('poder')} < {_PODER_MINIMO}) — portão experimento vermelho (A2)."
        )
    motivos.extend(avisos)
    if motivos:
        return "amarelo", motivos
    return "verde", motivos
