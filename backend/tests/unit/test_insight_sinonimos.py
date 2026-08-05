"""Unit A17 (UAT real): o insight recusava pergunta legítima com vocabulário livre.

`consulta_por_sinonimo` mapeia sinônimos de negócio → métrica CANÔNICA da camada
semântica ANTES de qualquer recusa; todo alvo do mapa EXISTE no dicionário (§7.2 —
nunca vira SQL livre). A pré-guarda de PII segue soberana (A4 §8-M10).
"""

from agents.insight import consulta_por_sinonimo, motivo_fora_do_escopo
from domain.lancamento.semantica import CAMADA_SEMANTICA


def test_sinonimos_mapeiam_para_metricas_canonicas() -> None:
    casos = {
        "Qual a conversão por real gasto?": "vw_metricas_custo_por_pedido",
        "Como está o custo-benefício por canal?": "vw_metricas_custo_por_pedido",
        "Qual o custo por venda no WhatsApp?": "vw_metricas_custo_por_pedido",
        "Qual o CPA da campanha?": "vw_metricas_custo_por_pedido",
        "Qual o retorno sobre o investimento?": "vw_metricas_roas",
        "Qual o efeito incremental contra o holdout?": "vw_metricas_lift",
        "Atingimos a meta de conversões?": "vw_metricas_atingimento_meta",
    }
    for pergunta, esperada in casos.items():
        assert consulta_por_sinonimo(pergunta) == esperada, pergunta


def test_todo_alvo_do_mapa_existe_no_dicionario() -> None:
    """Guarda-corpo §7.2: o mapa jamais aponta para fora da camada semântica."""
    perguntas = (
        "conversão por real gasto",
        "custo-benefício",
        "custo por aquisição",
        "roi",
        "incrementalidade",
        "batemos a meta",
    )
    for pergunta in perguntas:
        assert consulta_por_sinonimo(pergunta) in CAMADA_SEMANTICA


def test_pergunta_sem_sinonimo_segue_sem_mapeamento() -> None:
    assert consulta_por_sinonimo("Como está o clima em Campinas?") is None
    assert consulta_por_sinonimo("Qual o desempenho geral?") is None


def test_pre_guarda_de_pii_segue_soberana() -> None:
    """A4: pergunta com PII recusa ANTES do LLM mesmo contendo sinônimo válido."""
    pergunta = "Qual o CPF de quem gerou a melhor conversão por real gasto?"
    assert motivo_fora_do_escopo(pergunta) is not None
