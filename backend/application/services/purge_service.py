"""Purge de retenção (§10.4) — o consumidor que faltava para `retencao_dias`.

Achado 20 do UAT #5 (docs/UAT5-2026-08-06-cacada.md): `retencao_dias: 180` era
validado, exibido na tela de Políticas e **não tinha nenhum consumidor** — nem
endpoint, nem job, nem `domain_event` de destruição. Controle documentado e
inexistente é o pior achado possível numa auditoria de LGPD.

O que o §10.4 manda: "job diário remove `telemetry_event` e DEs de campanhas além de
`retencao_dias` da política; destruição registrada em `domain_event`". Aqui:

- **`retencao_dias` vem da `PublicacoesPort`** — a fonte ÚNICA da política em runtime
  (achado 8: parametrização que não muda comportamento é teatro auditável). Publicar
  `retencao_dias: 30` na tela de Políticas MUDA o que este serviço apaga; sem linha
  publicada o adapter cai no seed §11.4, e o relatório carimba a `policy_versao` que
  valeu — a auditoria precisa saber qual régua aplicou.
- **Alvos** (o dado do titular que este twin realmente mantém em repouso):
  `telemetry_event` — a única tabela com dado por CONTATO (`contato_hash`, §4.1), a
  que cresce indefinidamente — e `dc_segment_cache`, a cópia local das audiências
  vindas do Data Cloud (as "DEs de campanhas" do §10.4 neste twin; o restante da
  audiência é SQL e contagem, não gente).
- **NÃO são alvo, e isso é decisão, não esquecimento**: o ledger `invocacao` e o
  outbox `domain_event`. São a trilha de auditoria LGPD (reconstrução do Art. 20,
  §8-M12) e já nascem sanitizados pelo C02; destruí-los por retenção apagaria
  justamente a prova de que a plataforma se comportou — inclusive a prova do próprio
  purge, que é gravada em `domain_event`. Está registrado no CHANGELOG como escopo
  explícito da emenda para que ninguém leia a ausência como bug.

**Dry-run é o default.** Apagar dado é irreversível: o endpoint só destrói com
`?aplicar=true`, e o dry-run devolve EXATAMENTE o relatório que a execução aplicaria
(mesmo predicado no repositório — ver `RepositorioPurge`). Rodar de novo é seguro:
na segunda passagem nada mais é elegível, o total é 0 e nenhum evento é emitido
(idempotência por construção, não por flag de controle).
"""

from datetime import datetime, timedelta
from typing import Any

from application.ports.clock import ClockPort
from application.ports.publicacoes import PublicacoesPort
from application.ports.repositorio_purge import RepositorioPurge
from domain.campanha.modelos import EventoDominio

# Tabelas varridas, na ordem do relatório (§10.4). Nome da tabela = chave do §4.1.
TABELAS_PURGADAS: tuple[str, ...] = ("telemetry_event", "dc_segment_cache")

EVENTO_PURGE = "dados.purgados"  # §2.3/§10.4 — destruição registrada no outbox


class RetencaoInvalida(Exception):
    """`retencao_dias` da política vigente fora do contrato §4.1 (inteiro ≥ 1).

    Erro DURO de propósito: purgar com um valor absurdo (0, negativo, texto) apagaria
    a base inteira. Preferimos o 422 a "interpretar" a intenção do operador."""

    def __init__(self, motivo: str) -> None:
        super().__init__(motivo)
        self.motivo = motivo


class ServicoPurge:
    """Aplica a retenção da política vigente (§10.4). Sem LLM, sem heurística."""

    def __init__(
        self, repositorio: RepositorioPurge, relogio: ClockPort, publicacoes: PublicacoesPort
    ) -> None:
        self._repo = repositorio
        self._relogio = relogio
        self._publicacoes = publicacoes  # fallback do seed pelo adapter (achado 8)

    def purgar(self, tenant_id: str, *, aplicar: bool = False, actor: str) -> dict[str, Any]:
        """POST /admin/purge — relatório do que expirou (e, com `aplicar`, apaga).

        Devolve `{aplicado, retencao_dias, policy_versao, corte, removidos:{tabela: n},
        total}`. Com `aplicar=False` os números são os mesmos que a execução produziria:
        é o mesmo predicado no repositório.
        """
        retencao_dias, versao = self._retencao_vigente(tenant_id)
        agora = self._relogio.agora()
        corte = agora - timedelta(days=retencao_dias)
        removidos = {
            "telemetry_event": self._repo.purgar_telemetria(tenant_id, corte, aplicar=aplicar),
            "dc_segment_cache": self._repo.purgar_dc_cache(tenant_id, corte, aplicar=aplicar),
        }
        total = sum(removidos.values())
        relatorio: dict[str, Any] = {
            "aplicado": aplicar,
            "retencao_dias": retencao_dias,
            "policy_versao": versao,
            "corte": corte,
            "removidos": removidos,
            "total": total,
        }
        if aplicar and total:
            # §10.4: a destruição é registrada em `domain_event`. Só quando algo foi de
            # fato destruído — rodar o cron de hora em hora não pode encher o outbox de
            # linhas "apaguei zero" (ruído em auditoria é o mesmo que apagar o sinal).
            self._registrar(tenant_id, relatorio, agora, actor)
        return relatorio

    # --------------------------------------------------------------- Interno
    def _retencao_vigente(self, tenant_id: str) -> tuple[int, int | None]:
        """`retencao_dias` + versão da política VIGENTE do tenant, pela PublicacoesPort.

        Uma fonte só (achado 8 do UAT #5): o adapter já resolve banco → fallback do
        seed §11.4, então o purge não tem — nem pode ter — régua própria. Publicar
        `retencao_dias: 30` na tela de Políticas muda o que este serviço apaga."""
        politica = self._publicacoes.politica_publicada(tenant_id)
        conteudo = dict(politica.get("conteudo") or {})
        versao = politica.get("versao")
        bruto = conteudo.get("retencao_dias")
        # bool é subclasse de int: `True` viraria 1 dia de retenção silenciosamente.
        if isinstance(bruto, bool) or not isinstance(bruto, int) or bruto < 1:
            raise RetencaoInvalida(
                f"retencao_dias inválido na política vigente (versão {versao}): {bruto!r}. "
                "Contrato §4.1: inteiro ≥ 1. Purge abortado sem apagar nada."
            )
        return bruto, versao if isinstance(versao, int) else None

    def _registrar(
        self, tenant_id: str, relatorio: dict[str, Any], agora: datetime, actor: str
    ) -> None:
        self._repo.adicionar_evento(
            EventoDominio(
                tenant_id=tenant_id,
                os_id=None,  # purge é do TENANT, não de uma OS
                type=EVENTO_PURGE,
                payload={
                    "retencao_dias": relatorio["retencao_dias"],
                    "policy_versao": relatorio["policy_versao"],
                    "corte": relatorio["corte"].isoformat(),
                    "removidos": dict(relatorio["removidos"]),
                    "total": relatorio["total"],
                },  # só contagens e datas: o evento da destruição não ressuscita o dado
                actor=actor,
                via_ai=False,
                created_at=agora,
            )
        )
