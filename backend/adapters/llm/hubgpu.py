"""Adapter REAL do LLMPort — HubGPU OpenAI-compatible (§3): client `openai` com base_url
custom e `api_key="not-needed"` (o proxy autentica por outra via — string literal válida).

Fica atrás de `LLM_DEGRADED_MODE` (§10.6): `forced_off` → `disponivel()=False` e `chat()`
levanta `LLMIndisponivel` SEM tocar a rede. NUNCA usado em teste (§1.3.5) — testes usam
`adapters/llm/fake.py`. Client é lazy: nenhuma conexão na construção do adapter.

Frente 1 — dois consertos no modo degradado
-------------------------------------------
1. **`except openai.APIError`** no lugar de `(APITimeoutError, APIConnectionError)`
   (achado 10 do UAT #5, aberto desde então). NENHUMA exceção de STATUS HTTP do SDK
   herda daquelas duas: `RateLimitError`/`InternalServerError → APIStatusError → APIError`,
   enquanto `APITimeoutError → APIConnectionError → APIError`. Os dois ramos só se
   encontram em `APIError` — que o adapter não capturava. Resultado: 429 e 5xx do hub
   escapavam para o handler genérico e viravam **500 cru**, exatamente o oposto do §10.6,
   e a SPA nunca via o `503 degraded` que a faz oferecer o modo manual. O adapter irmão
   de embeddings sempre capturou `APIError` — este ficou para trás.
2. **`DisjuntorHub`** (abaixo) — o circuit breaker do §10.7, que era promessa escrita e
   `grep -riE 'circuit|breaker'` nos adapters devolvia zero.

Os dois consertos são UM SÓ e não se separam: sem (1) o breaker não enxergaria 429/5xx
como falha e nunca contaria nada — o hub podia responder 503 o dia inteiro que o
disjuntor seguiria fechado.
"""

from __future__ import annotations

import math
import threading
from datetime import datetime, timedelta
from typing import Any

from adapters.relogio import RelogioSistema
from app.config import Settings
from application.ports.clock import ClockPort
from application.ports.llm import LLMIndisponivel, PerfilModelo, RespostaLLM

# §10.7: "circuit breaker por 60s após 3 falhas".
LIMIAR_FALHAS = 3
COOLDOWN_S = 60


class DisjuntorHub:
    """Circuit breaker do §10.7 — fechado → aberto (3 falhas) → meio-aberto (60 s).

    Por que ele é o conserto principal, e não um enfeite
    ---------------------------------------------------
    Com `LLM_TIMEOUT_S=300` e `LLM_MAX_RETRIES=2`, uma única chamada a um hub que
    engasgou fica pendurada até ~900 s. Sem disjuntor, TODA requisição que chega paga
    esses 900 s por conta própria: "hub lento" deixa de ser degradação e vira
    "plataforma fora do ar" — o cenário que o §10.6 existe para impedir. Com ele, o
    terceiro fracasso fecha a porta e os 60 s seguintes custam ZERO rede e respondem
    503 `degraded` na hora, que é o que a SPA sabe tratar.

    Meio-aberto SEM flag de "sonda em voo"
    --------------------------------------
    Ao vencer o cooldown, `permite_chamada()` libera UMA chamada e **re-arma o relógio
    no mesmo gesto**. Quem chegar junto encontra a porta fechada de novo, então não há
    estouro de N sondas simultâneas contra um hub morto — e não há flag que possa ficar
    presa se a sonda morrer de um jeito que ninguém reporta (uma flag booleana travaria
    o disjuntor aberto para sempre nesse caso). Sonda boa → `registrar_sucesso` fecha;
    sonda ruim → `registrar_falha` re-arma; sonda que sumiu → o tempo reabre sozinho.

    Falhas CONSECUTIVAS: um acerto zera a contagem. Vale lembrar que cada "falha" aqui
    já é uma chamada do SDK com `max_retries=2` embutido, ou seja, até 3 idas à rede —
    o limiar de 3 falhas equivale a ~9 tentativas de HTTP antes de desistir.

    Relógio pelo `ClockPort` (§2.1), NUNCA `datetime.now()`: é o que deixa o teste provar
    o meio-aberto avançando o relógio, sem 60 s de `sleep` na suíte.

    `Lock` porque um adapter é UM por aplicação (`app.state.llm`) e é tocado por várias
    threads: as rotas de IA rodam em threadpool e o `chat()` é síncrono.
    """

    def __init__(
        self,
        relogio: ClockPort,
        *,
        limiar: int = LIMIAR_FALHAS,
        cooldown_s: int = COOLDOWN_S,
        rotulo: str = "hub",
    ) -> None:
        self._relogio = relogio
        self._limiar = limiar
        self._cooldown = timedelta(seconds=cooldown_s)
        self._rotulo = rotulo
        self._falhas = 0
        self._aberto_ate: datetime | None = None
        self._meio_aberto = False
        self._trava = threading.Lock()

    def aberto(self) -> bool:
        """Porta fechada para a rede AGORA? (informativo — `disponivel()` usa isto)."""
        with self._trava:
            return self._aberto_ate is not None and self._relogio.agora() < self._aberto_ate

    def restante_s(self) -> int:
        with self._trava:
            if self._aberto_ate is None:
                return 0
            return max(0, math.ceil((self._aberto_ate - self._relogio.agora()).total_seconds()))

    def permite_chamada(self) -> bool:
        """`False` = não vá à rede. `True` no vencimento do cooldown = sonda meio-aberta."""
        with self._trava:
            if self._aberto_ate is None:
                return True
            agora = self._relogio.agora()
            if agora < self._aberto_ate:
                return False
            self._aberto_ate = agora + self._cooldown  # re-arma junto com a sonda
            self._meio_aberto = True
            return True

    def registrar_sucesso(self) -> None:
        with self._trava:
            self._falhas = 0
            self._aberto_ate = None
            self._meio_aberto = False

    def registrar_falha(self) -> None:
        with self._trava:
            self._falhas += 1
            if self._meio_aberto or self._falhas >= self._limiar:
                self._aberto_ate = self._relogio.agora() + self._cooldown
                self._meio_aberto = False

    def motivo(self) -> str:
        return (
            f"Circuito do {self._rotulo} ABERTO após {self._limiar} falhas seguidas "
            f"(§10.7); reabre em ~{self.restante_s()}s."
        )

    def estado(self) -> str:
        """`fechado` | `aberto` | `meio-aberto` — diagnóstico para teste e ops."""
        with self._trava:
            if self._aberto_ate is None:
                return "fechado"
            if self._meio_aberto:
                return "meio-aberto"
            return "aberto" if self._relogio.agora() < self._aberto_ate else "meio-aberto"


class LLMHubGPU:
    """Implementa LLMPort; roteamento por perfil (§3): 120b e 20b têm base_url/model próprios."""

    def __init__(self, settings: Settings, relogio: ClockPort | None = None) -> None:
        self._settings = settings
        self._clients: dict[str, Any] = {}
        # `relogio` opcional para não quebrar os chamadores existentes (`LLMHubGPU(settings)`
        # em api/v1/intake.py); o teste injeta um relógio fixo e prova o meio-aberto.
        self._disjuntor = DisjuntorHub(relogio or RelogioSistema(), rotulo="LLM HubGPU")

    @property
    def disjuntor(self) -> DisjuntorHub:
        return self._disjuntor

    def disponivel(self) -> bool:
        """`False` também com o circuito ABERTO: durante o cooldown a plataforma está de
        fato em modo degradado (§10.6), e quem consulta `disponivel()` para decidir se
        oferece o caminho manual precisa saber disso — não só quem chama `chat()`."""
        return self._settings.llm_degraded_mode != "forced_off" and not self._disjuntor.aberto()

    def _config(self, perfil: PerfilModelo) -> tuple[str, str]:
        """(base_url, model) do perfil — POST {base_url}/chat/completions (§3)."""
        if perfil == "120b":
            return self._settings.llm_120b_base_url, self._settings.llm_120b_model
        return self._settings.llm_20b_base_url, self._settings.llm_20b_model

    def _client(self, perfil: PerfilModelo) -> Any:
        if perfil not in self._clients:
            from openai import OpenAI  # import local: adapter nunca carrega em teste

            base_url, _ = self._config(perfil)
            self._clients[perfil] = OpenAI(
                base_url=base_url,
                api_key=self._settings.llm_api_key,  # "not-needed" é válido (§3)
                timeout=self._settings.llm_timeout_s,
                max_retries=self._settings.llm_max_retries,
            )
        return self._clients[perfil]

    def chat(self, mensagens: list[dict[str, str]], *, perfil: PerfilModelo = "20b") -> RespostaLLM:
        if self._settings.llm_degraded_mode == "forced_off":
            raise LLMIndisponivel(
                "LLM em modo degradado (LLM_DEGRADED_MODE=forced_off — §10.6); "
                "use o modo manual da UI."
            )
        if not self._disjuntor.permite_chamada():
            # §10.7: circuito aberto NÃO toca a rede — é o ponto inteiro do disjuntor.
            raise LLMIndisponivel(f"{self._disjuntor.motivo()} Use o modo manual da UI.")
        _, model = self._config(perfil)
        import openai  # lazy, coerente com o client

        try:
            resposta = self._client(perfil).chat.completions.create(model=model, messages=mensagens)
        except openai.APIError as erro:
            # §10.6: hub fora do ar, timeout, 429 ou 5xx é modo degradado (503), nunca 500.
            # `APIError` é o ÚNICO ancestral comum de APITimeoutError/APIConnectionError e
            # de APIStatusError (429/5xx) — capturar as duas primeiras deixava passar todo
            # erro de status. Mesma captura do adapter de embeddings.
            self._disjuntor.registrar_falha()
            raise LLMIndisponivel(
                f"Hub LLM inacessível ({type(erro).__name__}); use o modo manual da UI."
            ) from erro
        self._disjuntor.registrar_sucesso()
        # I04: o `usage` deixa de morrer aqui — total_tokens flui até invocacao.tokens
        # (§10.8). getattr defensivo nos DOIS níveis: hub/proxy sem usage e o duble de
        # teste sem o atributo degradam para None, nunca para exceção (§10.6).
        uso = getattr(resposta, "usage", None)
        return RespostaLLM(
            resposta.choices[0].message.content or "",
            getattr(uso, "total_tokens", None),
        )
