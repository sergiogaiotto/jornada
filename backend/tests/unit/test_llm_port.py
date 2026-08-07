"""Unit do LLMPort (§2.1/§3): fake em teste; adapter real atrás de LLM_DEGRADED_MODE.

Regra §1.3.5: o hub real NUNCA é chamado em teste — aqui só se exercita o caminho
degradado do adapter real (sem rede) e a conformidade estrutural com a porta.
"""

import pytest

from adapters.llm.fake import LLMFake
from adapters.llm.hubgpu import LLMHubGPU
from app.config import Settings
from application.ports.llm import LLMIndisponivel, LLMPort, RespostaLLM, soma_tokens


def test_fake_implementa_a_porta_e_registra_chamadas() -> None:
    fake = LLMFake(resposta="ok", respostas_por_perfil={"120b": "hub especialista"})
    assert isinstance(fake, LLMPort)  # runtime_checkable: conformidade estrutural
    assert fake.disponivel() is True
    # I04: chat() devolve RespostaLLM — o texto vem em `.texto` e desempacota como tupla
    assert fake.chat([{"role": "user", "content": "oi"}]) == RespostaLLM("ok", 1)
    texto, tokens = fake.chat([{"role": "user", "content": "oi"}], perfil="120b")
    assert (texto, tokens) == ("hub especialista", 2)
    assert [c["perfil"] for c in fake.chamadas] == ["20b", "120b"]


def test_fake_tokens_sao_deterministicos_funcao_pura_do_texto() -> None:
    """I04/§1.3.5: mesma resposta ⇒ mesma contagem, sempre — o aceite que prova o fluxo
    até `invocacao.tokens` não pode depender de aleatoriedade."""
    fake = LLMFake(resposta="uma resposta com cinco palavras")
    primeira = fake.chat([{"role": "user", "content": "a"}])
    segunda = fake.chat([{"role": "user", "content": "b"}])
    assert primeira.tokens == segunda.tokens == 5


def test_soma_tokens_agrega_medidos_e_preserva_none() -> None:
    """I04: linha de ledger que soma várias chamadas (retry §7.3, exec+judge do Ateliê).
    Todos None → None (não zero): ausência de medida não vira medida zero."""
    assert soma_tokens(None, None) is None
    assert soma_tokens(10, None, 5) == 15
    assert soma_tokens(None, 7) == 7


def test_fake_indisponivel_simula_modo_degradado() -> None:
    fake = LLMFake(disponivel=False)
    assert fake.disponivel() is False
    with pytest.raises(LLMIndisponivel):
        fake.chat([{"role": "user", "content": "oi"}])


def test_adapter_real_forced_off_nao_toca_a_rede_e_levanta_indisponivel() -> None:
    """§10.6: LLM_DEGRADED_MODE=forced_off → 503 degraded; nenhum client é construído."""
    adapter = LLMHubGPU(Settings(llm_degraded_mode="forced_off"))
    assert isinstance(adapter, LLMPort)
    assert adapter.disponivel() is False
    with pytest.raises(LLMIndisponivel):
        adapter.chat([{"role": "user", "content": "oi"}])
    assert adapter._clients == {}  # client openai jamais instanciado


def test_adapter_real_roteia_perfil_para_base_url_e_model_do_hub() -> None:
    """Roteamento §3 (sem rede: só a resolução de config por perfil)."""
    settings = Settings()
    adapter = LLMHubGPU(settings)
    assert adapter.disponivel() is True  # auto: disponível até healthcheck dizer o contrário
    assert adapter._config("120b") == (settings.llm_120b_base_url, settings.llm_120b_model)
    assert adapter._config("20b") == (settings.llm_20b_base_url, settings.llm_20b_model)
