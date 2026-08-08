"""Emenda D08 — cond/classe de `frequencySplit` fora do mix do governor vira AVISO (§6).

Instância do padrão P3 do UAT #5 ("o default silencioso é zero, não recusa"): o motor
roteia `por_classe.get(str(cond), 0)` e o mix de coortes só tem as classes do governor
(CLASSES_FREQUENCIA — personas.py). A forma D05 (classes livres/objeto, ex.:
'baixa'/'alta' do grafo v5 real) é VÁLIDA no save, mas simulava com alocação ZERO em
todos os braços: funil a jusante zerado, custo R$ 0,00 e semáforo VERDE — com custo 0 o
ROAS fica `None` e a regra "ROAS P50 < 1 → vermelho" nunca dispara. Nenhum aviso.

Inversão verificada: remover o bloco "D08" de motor.py (o `for` sobre `nos` logo após
`pesos_classe`, em `simular`) deixa os dois primeiros testes VERMELHOS; o terceiro
continua verde porque afirma ausência e reprodutibilidade.
"""

from decimal import Decimal
from typing import Any

from adapters.aleatorio import rng_disponivel
from domain.jornada.validacao import validar_grafo
from domain.simulacao.motor import simular
from domain.simulacao.personas import gerar_personas
from domain.simulacao.priors import PRIORS_DEFAULT


def _no(id_: str, tipo: str, **data: Any) -> dict[str, Any]:
    return {"id": id_, "type": tipo, "data": data}


def _ar(id_: str, de: str, para: str, **extra: Any) -> dict[str, Any]:
    return {"id": id_, "from": de, "to": para, **extra}


ENTRADA = _no("n1", "entrySource", deRef="DE_x", modo="fire_once", reentrada="nao")
META = _no("n9", "goal", metrica="conversao", deRef="DE_m")
SAIDA = _no("n0", "exit", motivo="fim")


def _grafo_fq(classes: list[Any], conds: list[tuple[str, str]]) -> dict[str, Any]:
    """frequencySplit `fq` → canais a (sms) e b (push); `conds` = (cond, destino)."""
    return {
        "jgcVersion": "1.0",
        "meta": {"osCodigo": "OS-D08", "tenant": "torre-movel", "reentrada": "nao"},
        "nodes": [
            ENTRADA,
            _no("fq", "frequencySplit", classes=classes, fonte="DE_freq"),
            _no("a", "channel.sms", assetRef="s1", optIn=True),
            _no("b", "channel.push", assetRef="s2", optIn=True),
            META,
            SAIDA,
        ],
        "edges": [
            _ar("e1", "n1", "fq"),
            *[_ar(f"c{i}", "fq", destino, cond=cond) for i, (cond, destino) in enumerate(conds)],
            _ar("e4", "a", "n9"),
            _ar("e5", "b", "n9"),
            _ar("e6", "n9", "n0"),
        ],
    }


def _simular(grafo: dict[str, Any], *, seed: int = 42, runs: int = 20) -> dict[str, Any]:
    """Mesma montagem do `SimuladorService`: personas saem do MESMO gerador (F01)."""
    ger = rng_disponivel().gerador(seed)
    personas = gerar_personas(n=10_000, priors=PRIORS_DEFAULT, ger=ger)
    return simular(
        grafo,
        volume_entrada=1000,
        personas=personas,
        priors=PRIORS_DEFAULT,
        tarifas={"sms": Decimal("0.10"), "push": Decimal("0.01")},
        politica={},
        ger=ger,
        runs=runs,
        ticket_medio=120.0,
        hora_inicio=9.0,
    )


def test_D08_cond_fora_do_mix_vira_aviso_e_semaforo_vermelho() -> None:
    """O grafo v5 real: classes na forma D05 ('baixa'/'alta'), save aprova, motor zera.

    HISTÓRIA EM DUAS ONDAS, e ela importa para não afrouxar nada por engano:

    · **D08 (onda anterior)** tirou este caso do VERDE. Antes, `avisos == []` e a
      simulação saía verde com 100% do volume sumindo no split — zero mudo.
    · **D09 (§8-M8-A8, onda 7)** o tirou do AMARELO. Amarelo é a cor de "olhe isto";
      aqui não há o que ponderar: NENHUMA cond casa com o mix, então todo o volume que
      chega ao nó evapora e a jornada não entrega nada. Esta linha afirmava `amarelo` e
      passou a afirmar `vermelho` — deliberadamente, junto da emenda ao §6.

    A perda PARCIAL continua amarela: é o outro teste deste arquivo, e existe justamente
    para impedir que uma onda futura alargue a regra e a T9 comece a recusar jornada
    saudável.

    Inversão: comentar o `bloqueantes.append(...)` do D09 devolve este caso a `amarelo`;
    mover o `motivos.extend(bloqueantes)` para depois do `return "vermelho"` também —
    e essa segunda inversão é a que prova a PRECEDÊNCIA, não apenas a mensagem.
    """
    grafo = _grafo_fq(
        [{"id": "baixa", "max": 2}, {"id": "alta", "min": 3}],
        [("baixa", "a"), ("alta", "b")],
    )
    assert validar_grafo(grafo) == [], "premissa do achado: o validador aprova esta forma"

    resultado = _simular(grafo)
    avisos_fq = [a for a in resultado["avisos"] if "frequencySplit fq" in a]
    assert any("'baixa'" in a and "'alta'" in a for a in avisos_fq), (
        "cond fora do mix do governor tem de virar aviso nomeando o nó e as conds "
        f"(§6/D08) — avisos: {resultado['avisos']!r}"
    )
    # o aviso descreve um sumiço REAL: nenhum braço recebe volume, custo zera
    assert resultado["funil"]["a"]["p50"] == 0 and resultado["funil"]["b"]["p50"] == 0
    assert resultado["custo"]["p50"] == 0 and resultado["roas"] is None

    # D09: o extremo é BLOQUEANTE, em canal próprio e nomeando o nó
    bloqueantes = resultado["bloqueantes"]
    assert len(bloqueantes) == 1 and "fq" in bloqueantes[0] and "100%" in bloqueantes[0], (
        f"o caso extremo precisa de um bloqueante próprio — veio {bloqueantes!r}"
    )
    assert resultado["semaforo"] == "vermelho", (
        "era VERDE antes do D08 e AMARELO antes do D09, com o funil inteiro zerado"
    )
    # âncora anti-falso-positivo: o vermelho NÃO veio da regra do ROAS (que é None aqui)
    assert resultado["roas"] is None
    assert any("100%" in m for m in resultado["motivos_semaforo"]), (
        "o motivo do vermelho tem de ser o bloqueante do D09, não outra causa"
    )


def test_D08_classe_do_mix_sem_aresta_vira_aviso() -> None:
    """Cobertura parcial: conds válidas, mas a classe 'sub' do mix não tem braço —
    essa fração do volume sai do funil calada.

    Vermelho sem o bloco D08 de motor.py (nenhum aviso é emitido)."""
    grafo = _grafo_fq(["saturado", "ok"], [("saturado", "a"), ("ok", "b")])
    assert validar_grafo(grafo) == []

    resultado = _simular(grafo)
    avisos_fq = [a for a in resultado["avisos"] if "frequencySplit fq" in a]
    assert len(avisos_fq) == 1 and "'sub'" in avisos_fq[0] and "sem aresta" in avisos_fq[0]
    assert not any("sem classe no mix" in a for a in avisos_fq), (
        "conds que casam não podem ser acusadas"
    )
    # os braços que casam seguem recebendo volume; a fração 'sub' (~20%) evapora
    assert resultado["funil"]["a"]["p50"] > 0 and resultado["funil"]["b"]["p50"] > 0
    assert resultado["funil"]["a"]["p50"] + resultado["funil"]["b"]["p50"] < 1000

    # D09 (§8-M8-A8): a perda PARCIAL segue AMARELA, por decisão declarada. Esta é a
    # trava de calibragem do D09 — sem ela, alargar a regra bloqueante para `sem_aresta`
    # passaria despercebido e a T9 começaria a recusar jornada saudável.
    # Inversão: trocar a condição do D09 por `if sem_aresta:` deixa este teste vermelho.
    assert resultado["bloqueantes"] == [], (
        f"perda parcial não pode bloquear — veio {resultado['bloqueantes']!r}"
    )
    assert resultado["semaforo"] == "amarelo"
    # e a fração perdida é MEDIDA, não adjetivada: o operador precisa do número
    assert "%" in avisos_fq[0], f"o aviso não diz quanto do volume sai: {avisos_fq[0]!r}"


def test_D08_grafo_que_casa_o_mix_segue_sem_aviso_e_reprodutivel() -> None:
    """Guarda-corpo nas duas direções: grafo saudável não ganha aviso nenhum, e a
    checagem (fora do loop de runs, sem draw novo) não quebra o M8-A1 — mesma seed,
    mesma saída inteira."""
    grafo = _grafo_fq(
        ["saturado", "ok", "sub"],
        [("saturado", "a"), ("ok", "a"), ("sub", "b")],
    )
    a, b = _simular(grafo), _simular(grafo)
    assert not any("frequencySplit" in aviso for aviso in a["avisos"]), a["avisos"]
    assert a == b, "mesma seed tem de reproduzir a MESMA saída (M8-A1)"
    # o split cobre o mix: nada evapora no nó
    assert a["funil"]["a"]["p50"] + a["funil"]["b"]["p50"] == 1000.0
