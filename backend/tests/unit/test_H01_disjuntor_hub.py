"""Modo degradado do hub (§10.6) e circuit breaker (§10.7) — achado 10 do UAT #5.

O que se prova aqui, e por que cada asserção existe
---------------------------------------------------
1. **429 e 5xx do hub viram `LLMIndisponivel` (→ 503 `degraded`), não 500.** O adapter
   de LLM capturava `(APITimeoutError, APIConnectionError)`; nenhuma exceção de STATUS
   do SDK herda dessas duas — `RateLimitError`/`InternalServerError` descem por
   `APIStatusError`, e o único ancestral comum é `APIError`. `test_hierarquia_*` fixa
   esse fato do SDK: se um upgrade de `openai` mudar a árvore, ele avisa antes que o
   conserto vire ilusão.
2. **O disjuntor abre e a chamada seguinte NÃO vai à rede.** É a única asserção que
   importa do §10.7: com `LLM_TIMEOUT_S=300` × 2 retries, ir à rede custa até ~900 s.
3. **Meio-abre depois de 60 s** — provado avançando o `ClockPort` (§2.1), sem `sleep`.

§1.3.5 continua valendo: o hub REAL não é tocado. O client `openai` é substituído por um
dublê que conta chamadas — é justamente contando essas chamadas que se prova o "não foi
à rede". As exceções são as classes de verdade do SDK, construídas em memória.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import httpx
import openai
import pytest

from adapters.embedding.hubgpu import EmbeddingHubGPU
from adapters.llm.hubgpu import DisjuntorHub, LLMHubGPU
from app.config import Settings
from application.ports.embedding import EmbeddingIndisponivel
from application.ports.llm import LLMIndisponivel, RespostaLLM

MENSAGENS = [{"role": "user", "content": "oi"}]


class RelogioFixo:
    """ClockPort (§2.1) manipulável — o cooldown de 60 s é provado por AVANÇO."""

    def __init__(self, instante: datetime | None = None) -> None:
        self.instante = instante or datetime(2026, 8, 7, 12, 0, tzinfo=UTC)

    def agora(self) -> datetime:
        return self.instante

    def avancar(self, segundos: float) -> None:
        self.instante += timedelta(seconds=segundos)


def erro_de_status(codigo: int, classe: type[openai.APIStatusError]) -> openai.APIStatusError:
    """Exceção REAL do SDK para um status HTTP (nenhuma rede: `httpx.Response` em memória)."""
    requisicao = httpx.Request("POST", "http://hub.invalido/v1/chat/completions")
    return classe("hub reclamou", response=httpx.Response(codigo, request=requisicao), body=None)


def erro_de_timeout() -> openai.APITimeoutError:
    return openai.APITimeoutError(httpx.Request("POST", "http://hub.invalido/v1/chat/completions"))


class ClientDublê:
    """Dublê do client `openai`: serve um roteiro e CONTA as idas à rede.

    O contador é a prova do §10.7 — "a 4ª chamada não vai à rede" é exatamente
    "`chamadas` não subiu".
    """

    def __init__(self, roteiro: list[Any]) -> None:
        self.roteiro = list(roteiro)
        self.chamadas = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create_chat))
        self.embeddings = SimpleNamespace(create=self._create_embed)

    def _proximo(self) -> Any:
        self.chamadas += 1
        item = self.roteiro.pop(0) if len(self.roteiro) > 1 else self.roteiro[0]
        if isinstance(item, Exception):
            raise item
        return item

    def _create_chat(self, **_: Any) -> Any:
        item = self._proximo()
        if isinstance(item, tuple):  # (texto, total_tokens) — hub que manda `usage` (I04)
            texto, total = item
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=str(texto)))],
                usage=SimpleNamespace(total_tokens=total),
            )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=str(item)))]
        )

    def _create_embed(self, **_: Any) -> Any:
        item = self._proximo()
        return SimpleNamespace(data=[SimpleNamespace(index=0, embedding=list(item))])


def llm_com_dublê(roteiro: list[Any], relogio: RelogioFixo) -> tuple[LLMHubGPU, ClientDublê]:
    adapter = LLMHubGPU(Settings(_env_file=None), relogio)
    dublê = ClientDublê(roteiro)
    adapter._clients = {"20b": dublê, "120b": dublê}  # nenhum OpenAI() é construído
    return adapter, dublê


def embed_com_dublê(
    roteiro: list[Any], relogio: RelogioFixo
) -> tuple[EmbeddingHubGPU, ClientDublê]:
    adapter = EmbeddingHubGPU(Settings(_env_file=None), relogio)
    dublê = ClientDublê(roteiro)
    adapter._client = dublê
    return adapter, dublê


# ------------------------------------------------- o fato do SDK que o achado 10 revelou
def test_hierarquia_do_sdk_openai_justifica_capturar_apierror() -> None:
    """Erro de STATUS e erro de CONEXÃO só se encontram em `APIError`.

    Esta é a asserção que explica o bug: capturar `(APITimeoutError, APIConnectionError)`
    NUNCA pegaria um 429 ou um 500 do hub.
    """
    assert not issubclass(openai.RateLimitError, openai.APIConnectionError)
    assert not issubclass(openai.InternalServerError, openai.APIConnectionError)
    assert issubclass(openai.RateLimitError, openai.APIError)
    assert issubclass(openai.InternalServerError, openai.APIError)
    assert issubclass(openai.APITimeoutError, openai.APIError)


# --------------------------------------------------------- 429/5xx → degraded, não 500
@pytest.mark.parametrize(
    ("codigo", "classe"),
    [(429, openai.RateLimitError), (500, openai.InternalServerError)],
)
def test_llm_429_e_500_do_hub_viram_indisponivel_degradado(
    codigo: int, classe: type[openai.APIStatusError]
) -> None:
    """§10.6: a rota traduz `LLMIndisponivel` em 503 `degraded`. Antes do conserto estas
    exceções escapavam do adapter e o handler genérico devolvia 500 cru — e a SPA, que
    só sabe oferecer o modo manual diante de um 503, não oferecia nada."""
    adapter, _ = llm_com_dublê([erro_de_status(codigo, classe)], RelogioFixo())
    with pytest.raises(LLMIndisponivel) as capturado:
        adapter.chat(MENSAGENS)
    assert classe.__name__ in str(capturado.value)  # a causa vai no texto, não some


def test_llm_timeout_continua_degradado_apos_o_conserto() -> None:
    """Não-regressão: o comportamento que JÁ funcionava (timeout/conexão) não se perdeu
    ao trocar a captura por `APIError`."""
    adapter, _ = llm_com_dublê([erro_de_timeout()], RelogioFixo())
    with pytest.raises(LLMIndisponivel):
        adapter.chat(MENSAGENS)


@pytest.mark.parametrize(
    ("codigo", "classe"),
    [(429, openai.RateLimitError), (503, openai.APIStatusError)],
)
def test_embedding_429_e_5xx_do_hub_viram_indisponivel_degradado(
    codigo: int, classe: type[openai.APIStatusError]
) -> None:
    adapter, _ = embed_com_dublê([erro_de_status(codigo, classe)], RelogioFixo())
    with pytest.raises(EmbeddingIndisponivel):
        adapter.embed(["texto"])


# ------------------------------------------------------------------ disjuntor (§10.7)
def test_llm_disjuntor_abre_na_3a_falha_e_a_4a_chamada_nao_vai_a_rede() -> None:
    """O aceite do §10.7. A prova de que a 4ª não foi à rede é `dublê.chamadas == 3`."""
    relogio = RelogioFixo()
    adapter, dublê = llm_com_dublê([erro_de_status(500, openai.InternalServerError)], relogio)

    for _ in range(3):
        with pytest.raises(LLMIndisponivel):
            adapter.chat(MENSAGENS)
    assert dublê.chamadas == 3
    assert adapter.disjuntor.estado() == "aberto"
    assert adapter.disponivel() is False  # a plataforma SABE que está degradada

    with pytest.raises(LLMIndisponivel) as capturado:
        adapter.chat(MENSAGENS)
    assert dublê.chamadas == 3  # <- a 4ª NÃO tocou a rede
    assert "ABERTO" in str(capturado.value)
    assert "60" in str(capturado.value) or "s." in str(capturado.value)


def test_llm_disjuntor_meio_abre_depois_de_60s_e_fecha_no_sucesso() -> None:
    """Meio-aberto: passados 60 s, UMA sonda vai à rede; voltando bem, o circuito fecha."""
    relogio = RelogioFixo()
    adapter, dublê = llm_com_dublê(
        [erro_de_status(500, openai.InternalServerError)] * 3 + ["hub voltou"], relogio
    )
    for _ in range(3):
        with pytest.raises(LLMIndisponivel):
            adapter.chat(MENSAGENS)

    relogio.avancar(59)  # ainda dentro do cooldown
    with pytest.raises(LLMIndisponivel):
        adapter.chat(MENSAGENS)
    assert dublê.chamadas == 3

    relogio.avancar(1)  # 60 s completos → meio-aberto
    assert adapter.disponivel() is True
    assert adapter.chat(MENSAGENS).texto == "hub voltou"  # I04: retorno é RespostaLLM
    assert dublê.chamadas == 4  # a sonda FOI à rede
    assert adapter.disjuntor.estado() == "fechado"  # sucesso fecha


def test_llm_disjuntor_meio_aberto_solta_uma_sonda_so() -> None:
    """A sonda re-arma o cooldown no mesmo gesto: quem chega junto ainda encontra a porta
    fechada. Sem isso, vencido o cooldown, TODA requisição pendente cairia de uma vez em
    cima de um hub morto — a avalanche que o disjuntor existe para evitar."""
    relogio = RelogioFixo()
    adapter, dublê = llm_com_dublê([erro_de_status(500, openai.InternalServerError)], relogio)
    for _ in range(3):
        with pytest.raises(LLMIndisponivel):
            adapter.chat(MENSAGENS)

    relogio.avancar(60)
    with pytest.raises(LLMIndisponivel):  # sonda: vai à rede e falha de novo
        adapter.chat(MENSAGENS)
    assert dublê.chamadas == 4
    for _ in range(5):  # a fila que chegou junto NÃO vira 5 sondas
        with pytest.raises(LLMIndisponivel):
            adapter.chat(MENSAGENS)
    assert dublê.chamadas == 4


def test_llm_sucesso_zera_a_contagem_de_falhas() -> None:
    """Falhas CONSECUTIVAS: duas falhas + um acerto + duas falhas não abrem nada."""
    relogio = RelogioFixo()
    erro = erro_de_status(500, openai.InternalServerError)
    adapter, dublê = llm_com_dublê([erro, erro, "ok", erro, erro], relogio)
    for _ in range(2):
        with pytest.raises(LLMIndisponivel):
            adapter.chat(MENSAGENS)
    assert adapter.chat(MENSAGENS).texto == "ok"  # I04: retorno é RespostaLLM
    for _ in range(2):
        with pytest.raises(LLMIndisponivel):
            adapter.chat(MENSAGENS)
    assert adapter.disjuntor.estado() == "fechado"
    assert dublê.chamadas == 5  # todas foram à rede: o circuito nunca abriu


def test_llm_extrai_total_tokens_do_usage_quando_o_hub_manda() -> None:
    """I04 (§10.8): o `usage` do provedor deixou de morrer no adapter — `total_tokens`
    viaja no RETORNO de `chat()` até `invocacao.tokens`.

    INVERSÃO: reverter `hubgpu.chat` para `return resposta.choices[0].message.content`
    (o código anterior à onda 5) deixa esta asserção vermelha."""
    relogio = RelogioFixo()
    adapter, _ = llm_com_dublê([("resposta do hub", 321)], relogio)
    assert adapter.chat(MENSAGENS) == RespostaLLM("resposta do hub", 321)


def test_llm_sem_usage_degrada_para_none_nunca_para_falha() -> None:
    """Hub/proxy que suprime `usage` (acontece em streaming e em proxies): o texto flui
    e `tokens` fica None — usage ausente JAMAIS vira exceção (§10.6)."""
    relogio = RelogioFixo()
    adapter, _ = llm_com_dublê(["sem usage"], relogio)
    assert adapter.chat(MENSAGENS) == RespostaLLM("sem usage", None)


def test_embedding_disjuntor_abre_na_3a_falha_e_a_4a_nao_vai_a_rede() -> None:
    """Mesmo aceite no adapter irmão — o §10.7 pede o breaker nos DOIS."""
    relogio = RelogioFixo()
    adapter, dublê = embed_com_dublê([erro_de_status(429, openai.RateLimitError)], relogio)
    for _ in range(3):
        with pytest.raises(EmbeddingIndisponivel):
            adapter.embed(["t"])
    assert dublê.chamadas == 3
    with pytest.raises(EmbeddingIndisponivel):
        adapter.embed(["t"])
    assert dublê.chamadas == 3
    assert adapter.disponivel() is False

    relogio.avancar(60)
    assert adapter.disponivel() is True


def test_embedding_dimensao_errada_nao_abre_o_circuito() -> None:
    """Dimensão ≠ EMBED_DIM é erro de CONFIG (§10.4), não hub caído.

    Abrir o circuito aqui esconderia a causa: o cooldown venceria, a sonda voltaria com a
    mesma dimensão errada e o operador caçaria rede enquanto o problema está no `.env`.
    """
    relogio = RelogioFixo()
    adapter, dublê = embed_com_dublê([[0.1, 0.2, 0.3]], relogio)  # dim 3 ≠ EMBED_DIM
    for _ in range(4):
        with pytest.raises(EmbeddingIndisponivel):
            adapter.embed(["t"])
    assert dublê.chamadas == 4  # nunca parou de ir à rede
    assert adapter.disjuntor.estado() == "fechado"


def test_forced_off_nao_conta_falha_nem_toca_o_disjuntor() -> None:
    """§10.6 forçado é decisão de operação, não sintoma de hub doente."""
    adapter = LLMHubGPU(Settings(_env_file=None, llm_degraded_mode="forced_off"), RelogioFixo())
    for _ in range(5):
        with pytest.raises(LLMIndisponivel):
            adapter.chat(MENSAGENS)
    assert adapter._clients == {}  # client openai jamais instanciado (§1.3.5)
    assert adapter.disjuntor.estado() == "fechado"


# ------------------------------------------------------- o disjuntor isolado do adapter
def test_disjuntor_usa_o_clockport_e_nao_o_relogio_do_sistema() -> None:
    """§2.1: relógio injetado. Um `datetime.now()` escondido faria o `avancar` não
    surtir efeito nenhum — e é exatamente o que esta asserção detectaria."""
    relogio = RelogioFixo()
    disjuntor = DisjuntorHub(relogio, limiar=3, cooldown_s=60)
    for _ in range(3):
        disjuntor.registrar_falha()
    assert disjuntor.aberto() is True
    assert disjuntor.restante_s() == 60
    relogio.avancar(30)
    assert disjuntor.restante_s() == 30
    assert disjuntor.aberto() is True
    relogio.avancar(30)
    assert disjuntor.aberto() is False
