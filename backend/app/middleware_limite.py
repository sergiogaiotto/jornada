"""Limite de tentativas POR IP na superfície de login (frente 1 — §10.3, §8-M0).

O bloqueio que a emenda G01 entregou é POR CONTA (`ContaUsuario.bloqueado_ate`,
`identidade_service._registrar_falha`) e continua valendo. Ele resolve o ataque
VERTICAL — mil senhas contra uma conta. Não resolve o horizontal:

· **Password spraying.** UMA senha (`Verao@2026`) contra MIL contas nunca chega a
  cinco falhas em conta nenhuma, então nada dispara. É o ataque que de fato acha
  credencial em base corporativa, e hoje ele passa liso.
· **DoS de graça.** `/auth/login` é a única rota que hasheia SEM autenticação, e cada
  tentativa custa um argon2id de 64 MiB × 3 passes (~100 ms de CPU + memória —
  `domain/identidade/senha.py`). O atacante gasta um POST de 80 bytes; o servidor
  gasta 100 ms. Sem teto por IP, um laço trivial satura a máquina.

Por que a defesa mora AQUI e não só no proxy reverso
----------------------------------------------------
`limit_req` do nginx é a camada certa para descartar a enxurrada antes que ela custe
um byte de Python, e a EMENDA a propõe. Mas ela NÃO substitui esta:

1. **Hoje não há proxy.** A VPS publica a aplicação direto na 8050. Uma defesa que só
   existe na config de um nginx que ninguém subiu é uma defesa que não existe.
2. **A porta continua exposta depois do proxy.** Publicar 8050 no host e pôr o nginx
   na frente não fecha a 8050 — quem souber o endereço fala com o uvicorn direto. O
   proxy é o primeiro filtro, nunca o único.
3. **Defesa em profundidade.** Erro de config no proxy (um `location` que não casa,
   um reload esquecido) volta a ser silencioso se a aplicação não contar nada.

Escopo: SÓ `/auth/login`. As outras rotas que hasheiam (`trocar-senha`, `usuarios`,
`resetar-senha`) exigem sessão/`admin` ANTES do corpo rodar — quem chega lá já é
alguém, e o gate é o RBAC. O limite existe para a superfície ANÔNIMA.

Os dois contadores, e por que são dois
--------------------------------------
Um contador só obriga a escolher entre trancar o escritório inteiro e não deter o
spraying. São ameaças diferentes, então são dois orçamentos:

· **CUSTO** (`TETO_CUSTO`/`JANELA_CUSTO_S`) — toda tentativa que chega ao argon2 conta,
  tenha ela acertado ou errado. É o teto de CPU: 10 hashes/min por IP ≈ 1 s de CPU por
  minuto, ~1,7 % de um núcleo. Sucesso NÃO devolve orçamento (o hash já foi pago).
· **FALHAS** (`TETO_FALHAS`/`JANELA_FALHAS_S`) — só recusas contam, e um login BEM
  SUCEDIDO do mesmo IP zera a conta. É o teto anti-spraying: 20 recusas em 15 min.

Como o usuário legítimo NÃO fica trancado
-----------------------------------------
· **Janela DESLIZANTE, não balde que vira.** Guarda-se o instante de cada tentativa e
  descarta-se o que saiu da janela; a punição vai vencendo sozinha, minuto a minuto.
  Não existe "bloqueado por 15 min" — existe "espere `Retry-After`", que é o tempo até
  a tentativa mais antiga cair fora (segundos, não minutos, no caso comum).
· **Sucesso zera as falhas.** É o que salva o escritório atrás de um NAT: 50 pessoas
  entrando pela manhã do mesmo IP público mantêm o contador de falhas perto de zero,
  porque cada acerto o limpa. Quem NÃO consegue zerar é exatamente o spraying, que só
  produz recusa.
· **Nada é permanente e há saída administrativa.** O reset pelo admin
  (`POST /auth/usuarios/{id}/resetar-senha`) já destrava a conta; o IP destrava sozinho.

Sem allowlist de IP de propósito: sem `Settings` para alimentá-la (ver
CONFIAR_EM_X_FORWARDED_FOR abaixo), uma allowlist viraria constante no repositório —
e constante no repositório é o furo que o UAT #5 levantou sobre os tokens `dev-*`.

NÃO é um middleware ASGI, apesar do nome do arquivo: registrar middleware exige
`app/main.py`, que está fora do escopo desta frente. O ponto de aplicação é a rota
(`api/v1/autenticacao.py`), que é onde o custo acontece — e o efeito é o mesmo, com a
vantagem de não gastar ciclo em request nenhum que não seja de login. A EMENDA propõe
promovê-lo a middleware (ou ao `limit_req` do nginx) quando `app/main.py` for tocado.
"""

from __future__ import annotations

import math
import threading
from collections import OrderedDict, deque
from typing import Any

from application.ports.clock import ClockPort

# ------------------------------------------------------------------ os números
# Orçamento de CPU: 10 tentativas/min por IP. Login humano usa 1–3 (com erro de digitação,
# 5); 10 dá folga para NAT pequeno sem dar folga para laço automatizado.
TETO_CUSTO = 10
JANELA_CUSTO_S = 60

# Orçamento anti-spraying: 20 RECUSAS por IP em 15 min. Spraying útil precisa de centenas
# de contas por rodada; 20 torna a rodada inviável sem tocar em quem acerta a senha.
TETO_FALHAS = 20
JANELA_FALHAS_S = 900

# Teto de IPs rastreados: sem ele, o próprio limitador vira DoS de MEMÓRIA (um IP forjado
# por pacote enche o dicionário). Estourado o teto, some o IP menos recentemente visto.
MAX_IPS = 10_000

# `X-Forwarded-For` é um header como qualquer outro: sem proxy na frente que o REESCREVA,
# confiar nele entrega ao atacante a chave do balde ("um IP novo por requisição") e o
# limite deixa de existir. Hoje não há proxy, então: NÃO confiar.
# EMENDA: quando o nginx entrar, isto vira `Settings.login_limite_proxies_confiaveis`
# (lista de IPs de proxy), não um booleano — confiar no header só faz sentido quando se
# sabe DE QUEM aceitá-lo. Constante aqui, e não em `app/config.py`, porque config.py está
# fora do escopo desta frente.
CONFIAR_EM_X_FORWARDED_FOR = False

_IP_DESCONHECIDO = "desconhecido"


class LimiteExcedido(Exception):
    """Orçamento do IP estourado — a rota traduz para 429 + `Retry-After` (§8/RFC 7807).

    429 e não 401: a requisição não foi julgada, foi recusada antes de custar argon2.
    Responder 401 aqui seria mentir e, pior, seria indistinguível de senha errada — o
    atacante não saberia que bateu no teto, mas o usuário legítimo também não.
    """

    def __init__(self, retry_after: int, motivo: str) -> None:
        super().__init__(motivo)
        self.retry_after = max(1, retry_after)
        self.motivo = motivo


class _Janela:
    """Fila de instantes (epoch, float) de uma janela deslizante."""

    __slots__ = ("marcas",)

    def __init__(self) -> None:
        self.marcas: deque[float] = deque()

    def podar(self, agora: float, janela_s: int) -> None:
        limite = agora - janela_s
        while self.marcas and self.marcas[0] <= limite:
            self.marcas.popleft()

    def espera_ate_liberar(self, agora: float, janela_s: int) -> int:
        """Segundos até a marca mais antiga sair da janela (o `Retry-After`)."""
        if not self.marcas:
            return 1
        return max(1, math.ceil(self.marcas[0] + janela_s - agora))


class _Balde:
    __slots__ = ("custo", "falhas")

    def __init__(self) -> None:
        self.custo = _Janela()
        self.falhas = _Janela()

    def vazio(self) -> bool:
        return not self.custo.marcas and not self.falhas.marcas


class LimitePorIp:
    """Duas janelas deslizantes por IP (custo e falhas). Seguro entre THREADS.

    A trava não é zelo: com as rotas de senha passando a `def` (elas rodam no threadpool
    do FastAPI para tirar o argon2 do event loop — ver `api/v1/autenticacao.py`), dois
    logins simultâneos tocam este dicionário em threads DIFERENTES. Sem `Lock`, dois
    `consumir` concorrentes leem o mesmo total e ambos passam.

    O relógio vem do `ClockPort` (§2.1): é o que permite ao teste provar que a janela
    DESLIZA — avança o relógio e vê o orçamento voltar — sem `sleep` de 60 s na suíte.
    """

    def __init__(
        self,
        relogio: ClockPort,
        *,
        teto_custo: int = TETO_CUSTO,
        janela_custo_s: int = JANELA_CUSTO_S,
        teto_falhas: int = TETO_FALHAS,
        janela_falhas_s: int = JANELA_FALHAS_S,
        max_ips: int = MAX_IPS,
    ) -> None:
        self._relogio = relogio
        self._teto_custo = teto_custo
        self._janela_custo_s = janela_custo_s
        self._teto_falhas = teto_falhas
        self._janela_falhas_s = janela_falhas_s
        self._max_ips = max_ips
        self._baldes: OrderedDict[str, _Balde] = OrderedDict()
        self._trava = threading.Lock()

    def _agora(self) -> float:
        return self._relogio.agora().timestamp()

    def _balde(self, ip: str, agora: float) -> _Balde:
        """Balde do IP, já podado, promovido a mais-recente (política de despejo LRU)."""
        balde = self._baldes.get(ip)
        if balde is None:
            balde = _Balde()
            self._baldes[ip] = balde
        else:
            self._baldes.move_to_end(ip)
        balde.custo.podar(agora, self._janela_custo_s)
        balde.falhas.podar(agora, self._janela_falhas_s)
        return balde

    def _despejar(self) -> None:
        """Poda oportunista + teto duro de IPs (o limitador não pode ser o vazamento)."""
        while len(self._baldes) > self._max_ips:
            self._baldes.popitem(last=False)

    def consumir(self, ip: str) -> None:
        """Confere OS DOIS tetos e, passando, debita uma tentativa do orçamento de custo.

        Checar e debitar no MESMO passo (sob a trava) é o que impede a corrida em que N
        requisições simultâneas leem "9 usadas" e todas as N entram.
        """
        agora = self._agora()
        with self._trava:
            balde = self._balde(ip, agora)
            if len(balde.falhas.marcas) >= self._teto_falhas:
                raise LimiteExcedido(
                    balde.falhas.espera_ate_liberar(agora, self._janela_falhas_s),
                    "Tentativas de login recusadas demais deste endereço. "
                    "Aguarde o tempo indicado em Retry-After e tente de novo.",
                )
            if len(balde.custo.marcas) >= self._teto_custo:
                raise LimiteExcedido(
                    balde.custo.espera_ate_liberar(agora, self._janela_custo_s),
                    "Tentativas de login demais deste endereço em pouco tempo. "
                    "Aguarde o tempo indicado em Retry-After e tente de novo.",
                )
            balde.custo.marcas.append(agora)
            self._despejar()

    def registrar_falha(self, ip: str) -> None:
        """Login RECUSADO — alimenta só a janela anti-spraying."""
        agora = self._agora()
        with self._trava:
            self._balde(ip, agora).falhas.marcas.append(agora)
            self._despejar()

    def registrar_sucesso(self, ip: str) -> None:
        """Login ACEITO — zera as falhas do IP; o custo permanece (o hash já foi pago).

        É a válvula que impede o falso positivo do escritório atrás de NAT. E não é
        presente ao atacante: quem zera precisou provar uma credencial válida, e o teto
        de CUSTO — que sucesso nenhum devolve — continua limitando a taxa dele.
        """
        agora = self._agora()
        with self._trava:
            balde = self._balde(ip, agora)
            balde.falhas.marcas.clear()
            if balde.vazio():
                del self._baldes[ip]

    def estado(self, ip: str) -> dict[str, int]:
        """Diagnóstico (teste/ops): quanto do orçamento o IP já gastou."""
        agora = self._agora()
        with self._trava:
            balde = self._balde(ip, agora)
            return {"custo": len(balde.custo.marcas), "falhas": len(balde.falhas.marcas)}

    @property
    def ips_rastreados(self) -> int:
        with self._trava:
            return len(self._baldes)


def ip_do_cliente(request: Any) -> str:
    """IP a que o orçamento pertence.

    `request.client` é o peer TCP real — a única fonte não forjável enquanto não houver
    proxy confiável declarado. Peer ausente (ASGI sem `client`) cai num balde ÚNICO
    `desconhecido` de propósito: fail-closed, todos esses requests dividem um orçamento
    em vez de cada um ganhar o seu.
    """
    if CONFIAR_EM_X_FORWARDED_FOR:  # desligado: ver a constante
        encaminhado = request.headers.get("x-forwarded-for")
        if encaminhado:
            return encaminhado.split(",")[0].strip()
    cliente = getattr(request, "client", None)
    return cliente.host if cliente and cliente.host else _IP_DESCONHECIDO
