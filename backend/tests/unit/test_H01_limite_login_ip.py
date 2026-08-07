"""Unit do limite por IP do login (frente 1) — `app/middleware_limite.py`.

O bloqueio por CONTA da emenda G01 continua onde estava; o que se prova aqui é o eixo
que faltava. Cada teste corresponde a uma decisão de desenho documentada no módulo:

· spraying (uma senha × muitas contas) bate no teto POR IP, que o teto por conta jamais
  vê — nenhuma conta chega a cinco falhas;
· o teto de CUSTO existe mesmo quando o atacante ACERTA a senha (é orçamento de CPU do
  argon2, não punição por erro);
· a janela DESLIZA (o orçamento volta com o tempo, provado pelo `ClockPort` §2.1);
· o usuário legítimo não é trancado: acerto zera a conta de falhas do IP;
· o próprio limitador não vira DoS de memória (teto de IPs rastreados).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.middleware_limite import (
    JANELA_CUSTO_S,
    JANELA_FALHAS_S,
    TETO_CUSTO,
    TETO_FALHAS,
    LimiteExcedido,
    LimitePorIp,
    ip_do_cliente,
)


class RelogioFixo:
    def __init__(self) -> None:
        self.instante = datetime(2026, 8, 7, 9, 0, tzinfo=UTC)

    def agora(self) -> datetime:
        return self.instante

    def avancar(self, segundos: float) -> None:
        self.instante += timedelta(seconds=segundos)


ATACANTE = "203.0.113.9"
ESCRITORIO = "198.51.100.4"


def test_spraying_bate_no_teto_por_ip_que_o_teto_por_conta_nunca_veria() -> None:
    """UMA senha contra MUITAS contas: nenhuma conta acumula falha, o IP acumula todas.

    É o cenário exato que o bloqueio por conta não cobre — e a razão de existir do
    limite por IP. `TETO_FALHAS` recusas depois, o IP para.
    """
    relogio = RelogioFixo()
    limite = LimitePorIp(relogio)

    # Atacante esperto: espaça as tentativas para NÃO esbarrar no teto de custo
    # (7 s ⇒ ~8,5/min, abaixo dos 10/min). Mesmo assim o teto de FALHAS o detém.
    atendidas = 0
    for _ in range(TETO_FALHAS * 2):
        try:
            limite.consumir(ATACANTE)
        except LimiteExcedido:
            break
        limite.registrar_falha(ATACANTE)  # cada tentativa é numa conta DIFERENTE
        atendidas += 1
        relogio.avancar(7)

    assert atendidas == TETO_FALHAS  # parou exatamente no orçamento anti-spraying
    with pytest.raises(LimiteExcedido):
        limite.consumir(ATACANTE)


def test_teto_de_custo_vale_mesmo_para_quem_acerta_a_senha() -> None:
    """O orçamento de CPU não é punição por erro: o argon2 custa igual quando dá certo.

    Sem isto, um roteiro que ACERTA credenciais (ex.: credential stuffing com base
    vazada) contornaria o limite inteiro só por não gerar falhas.
    """
    limite = LimitePorIp(RelogioFixo())
    for _ in range(TETO_CUSTO):
        limite.consumir(ATACANTE)
        limite.registrar_sucesso(ATACANTE)  # sucesso NÃO devolve orçamento de custo
    with pytest.raises(LimiteExcedido):
        limite.consumir(ATACANTE)


def test_janela_desliza_o_orcamento_volta_sozinho() -> None:
    """Janela deslizante, não balde que vira: passada a janela, o IP volta a ser atendido
    sem intervenção de ninguém. É o que impede o limite de virar banimento."""
    relogio = RelogioFixo()
    limite = LimitePorIp(relogio)
    for _ in range(TETO_CUSTO):
        limite.consumir(ATACANTE)
    with pytest.raises(LimiteExcedido):
        limite.consumir(ATACANTE)

    relogio.avancar(JANELA_CUSTO_S + 1)
    limite.consumir(ATACANTE)  # não levanta: a janela deslizou
    assert limite.estado(ATACANTE)["custo"] == 1


def test_retry_after_diz_a_verdade_sobre_quando_voltar() -> None:
    """`Retry-After` = tempo até a marca mais antiga sair da janela. Um número inventado
    (ou um 'tente mais tarde' genérico) empurra o cliente a repetir cedo e queimar mais
    orçamento, ou a esperar muito mais do que precisa."""
    relogio = RelogioFixo()
    limite = LimitePorIp(relogio)
    for _ in range(TETO_CUSTO):
        limite.consumir(ATACANTE)
    relogio.avancar(20)
    with pytest.raises(LimiteExcedido) as capturado:
        limite.consumir(ATACANTE)
    assert capturado.value.retry_after == JANELA_CUSTO_S - 20

    relogio.avancar(capturado.value.retry_after)
    limite.consumir(ATACANTE)  # o número era honesto


def test_login_legitimo_nao_e_trancado_pelo_vizinho_de_nat() -> None:
    """Escritório atrás de um IP público: quem ACERTA zera a conta de falhas do IP.

    Sem essa válvula, um colega distraído errando a senha cinco vezes iria consumindo o
    orçamento anti-spraying de todo mundo até trancar o andar inteiro.
    """
    relogio = RelogioFixo()
    limite = LimitePorIp(relogio)

    for _ in range(TETO_FALHAS - 1):  # o colega distraído
        limite.consumir(ESCRITORIO)
        limite.registrar_falha(ESCRITORIO)
        relogio.avancar(10)
    assert limite.estado(ESCRITORIO)["falhas"] == TETO_FALHAS - 1

    limite.consumir(ESCRITORIO)  # alguém entra de verdade
    limite.registrar_sucesso(ESCRITORIO)
    assert limite.estado(ESCRITORIO)["falhas"] == 0

    for _ in range(TETO_FALHAS - 1):  # e o andar segue com orçamento cheio
        limite.consumir(ESCRITORIO)
        limite.registrar_falha(ESCRITORIO)
        relogio.avancar(10)


def test_orcamento_e_por_ip_e_um_nao_gasta_o_do_outro() -> None:
    limite = LimitePorIp(RelogioFixo())
    for _ in range(TETO_CUSTO):
        limite.consumir(ATACANTE)
    with pytest.raises(LimiteExcedido):
        limite.consumir(ATACANTE)
    limite.consumir(ESCRITORIO)  # vizinho intacto
    assert limite.estado(ESCRITORIO)["custo"] == 1


def test_falhas_tambem_deslizam_na_janela_longa() -> None:
    relogio = RelogioFixo()
    limite = LimitePorIp(relogio)
    for _ in range(TETO_FALHAS):
        limite.registrar_falha(ATACANTE)
    with pytest.raises(LimiteExcedido):
        limite.consumir(ATACANTE)
    relogio.avancar(JANELA_FALHAS_S + 1)
    limite.consumir(ATACANTE)


def test_limitador_nao_vira_dos_de_memoria() -> None:
    """Um IP forjado por requisição encheria o dicionário até o processo morrer — a
    defesa não pode ser o buraco. Teto duro com despejo do menos recentemente visto."""
    limite = LimitePorIp(RelogioFixo(), max_ips=50)
    for i in range(500):
        limite.consumir(f"192.0.2.{i}")
    assert limite.ips_rastreados <= 50


def test_x_forwarded_for_nao_e_confiado_sem_proxy() -> None:
    """Confiar no header hoje entregaria ao atacante um IP novo por requisição — e o
    limite deixaria de existir. Vale o peer TCP, que ele não escolhe."""

    class _Req:
        headers = {"x-forwarded-for": "1.2.3.4"}
        client = type("C", (), {"host": "203.0.113.9"})()

    assert ip_do_cliente(_Req()) == "203.0.113.9"


def test_sem_peer_tcp_todos_dividem_um_balde_unico() -> None:
    """Fail-closed: sem `client` no escopo ASGI, ninguém ganha orçamento próprio."""

    class _Req:
        headers: dict[str, str] = {}
        client = None

    assert ip_do_cliente(_Req()) == "desconhecido"
