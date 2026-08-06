"""Aceite §10.4 · Purge de retenção — achado 20 do UAT #5.

`retencao_dias` era validado, exibido na tela de Políticas e NÃO TINHA CONSUMIDOR: sem
endpoint, sem job, sem `domain_event` de destruição. Controle documentado e inexistente
é o pior achado de uma auditoria LGPD.

Este arquivo é o guarda-corpo por COMPORTAMENTO do `POST /admin/purge`. O que ele
prova, nesta ordem de importância:

1. **o dry-run NÃO apaga** — é o default e é o que separa "relatório" de "estrago
   irreversível"; se este teste ficar verde com o dry-run destruindo, perdemos dado de
   cliente em produção na primeira execução;
2. a execução (`?aplicar=true`) apaga EXATAMENTE o que o dry-run relatou;
3. o que está DENTRO da retenção sobrevive (purge não é `TRUNCATE`);
4. a régua vem da política PUBLICADA no banco (achado 8: publicar 30 dias muda o
   comportamento — não é a constante compilada que manda);
5. a destruição vira `dados.purgados` no outbox (§2.3/§10.4), com contagens e sem
   nenhum dado do titular;
6. rodar de novo é seguro (idempotente: nada mais elegível, total 0, sem evento novo);
7. RBAC: só `dpo`/`admin` (§8-M0) — é quem responde pelo titular.

Sem docker e sem rede (§1.3.5): repositório em memória do app.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from domain.audiencia.modelos import DcSegmentCache
from domain.lancamento.modelos import TelemetryEvent

TENANT = "torre-movel"
AGORA = datetime.now(UTC)


def _h(token: str = "dev-dpo") -> dict[str, str]:
    return {"X-Tenant": TENANT, "Authorization": f"Bearer {token}"}


def _semear(app: FastAPI, *, dias_atras: tuple[int, ...]) -> None:
    """Telemetria + cache do Data Cloud com idades controladas (§4.1)."""
    repo = app.state.repositorio_os
    for dias in dias_atras:
        repo.adicionar_telemetria(
            TelemetryEvent(
                tenant_id=TENANT,
                tipo="sent",
                ts=AGORA - timedelta(days=dias),
                canal="email",
                contato_hash="a" * 64,  # sha256+salt do tenant (§10.2) — dado do titular
                fonte="ens",
            )
        )
        repo.salvar_dc_cache(
            DcSegmentCache(
                id=f"DC-SEG-{dias:03d}",
                tenant_id=TENANT,
                nome="Pós-pago 12+",
                criterios_resumo="plano=pos",
                membros=1000,
                atualizado_em=AGORA - timedelta(days=dias),
            )
        )


def _publicar_retencao(client: TestClient, dias: int) -> int:
    """Publica uma política nova só mudando `retencao_dias` — o resto vem da vigente."""
    vigente = client.get("/api/v1/policies", headers=_h("dev-analista")).json()
    conteudo: dict[str, Any] = {**vigente["publicada"]["conteudo"], "retencao_dias": dias}
    draft = client.post("/api/v1/policies", json={"conteudo": conteudo}, headers=_h("dev-analista"))
    assert draft.status_code == 201, draft.text
    publicada = client.post(
        f"/api/v1/policies/{draft.json()['id']}/publicar", headers=_h("dev-lider")
    )
    assert publicada.status_code == 200, publicada.text
    return int(publicada.json()["versao"])


def _eventos_purge(app: FastAPI) -> list[Any]:
    """Linhas `dados.purgados` no outbox (§2.3) — a prova documental da destruição."""
    return [e for e in app.state.repositorio_os.listar_eventos() if e.type == "dados.purgados"]


def _telemetria(app: FastAPI) -> list[TelemetryEvent]:
    return list(app.state.repositorio_os._telemetria)  # noqa: SLF001 — estado REAL em repouso


def test_D01_purge_dry_run_relata_e_nao_apaga(client: TestClient, app: FastAPI) -> None:
    """O ponto mais importante do arquivo: `POST /admin/purge` SEM `aplicar` conta o
    que expirou e não destrói NADA. Apagar é irreversível — o default tem de ser o
    modo seguro, e o relatório do dry-run tem de ser o mesmo número da execução."""
    _semear(app, dias_atras=(400, 300, 200, 10))  # 3 fora dos 180 dias do seed v1, 1 dentro
    antes = len(_telemetria(app))
    assert antes == 4

    seco = client.post("/api/v1/admin/purge", headers=_h())
    assert seco.status_code == 200, seco.text
    corpo = seco.json()
    assert corpo["aplicado"] is False
    assert corpo["retencao_dias"] == 180  # §11.4 seed v1
    assert corpo["removidos"] == {"telemetry_event": 3, "dc_segment_cache": 3}
    assert corpo["total"] == 6

    # PROVA da inércia: o repositório continua intacto e o outbox sem evento de purge
    assert len(_telemetria(app)) == antes, "dry-run APAGOU dado — regressão inaceitável"
    assert len(app.state.repositorio_os.listar_dc_cache(TENANT)) == 4
    assert _eventos_purge(app) == []

    # repetir o dry-run devolve exatamente o mesmo relatório (é leitura, não efeito)
    repetido = client.post("/api/v1/admin/purge", headers=_h()).json()
    assert repetido["removidos"] == corpo["removidos"]


def test_D01_purge_aplicar_apaga_o_relatado_preserva_o_recente_e_registra(
    client: TestClient, app: FastAPI
) -> None:
    """`?aplicar=true` apaga EXATAMENTE o que o dry-run relatou, preserva o que está
    dentro da retenção e registra a destruição em `domain_event` (§10.4) — com
    contagens, nunca com o dado destruído. Segunda passagem: idempotente."""
    _semear(app, dias_atras=(400, 300, 200, 10))
    previsto = client.post("/api/v1/admin/purge", headers=_h()).json()["removidos"]

    aplicado = client.post("/api/v1/admin/purge?aplicar=true", headers=_h())
    assert aplicado.status_code == 200, aplicado.text
    assert aplicado.json()["aplicado"] is True
    assert aplicado.json()["removidos"] == previsto, "execução divergiu do dry-run"

    # sobrou o que está DENTRO da retenção — purge não é TRUNCATE
    restantes = _telemetria(app)
    assert len(restantes) == 1
    assert (AGORA - restantes[0].ts).days == 10
    assert [e.id for e in app.state.repositorio_os.listar_dc_cache(TENANT)] == ["DC-SEG-010"]

    # §10.4: destruição registrada no outbox, com contagens e SEM dado do titular
    eventos = _eventos_purge(app)
    assert len(eventos) == 1
    payload = eventos[0].payload
    assert payload["total"] == 6 and payload["retencao_dias"] == 180
    assert payload["removidos"] == {"telemetry_event": 3, "dc_segment_cache": 3}
    assert "a" * 64 not in str(payload), "o evento da destruição não pode ressuscitar o dado"
    assert eventos[0].actor == "dpo@dev.jornada.local" and eventos[0].os_id is None

    # idempotente: rodar de novo não apaga nada e não emite evento novo (o cron do host
    # roda diariamente — a 2ª execução do dia não pode duplicar nem destruir a mais)
    repetido = client.post("/api/v1/admin/purge?aplicar=true", headers=_h())
    assert repetido.json()["total"] == 0
    assert len(_telemetria(app)) == 1
    assert len(_eventos_purge(app)) == 1


def test_D01_purge_obedece_a_politica_publicada_no_banco(client: TestClient, app: FastAPI) -> None:
    """Achado 8 do UAT #5 aplicado ao purge: publicar `retencao_dias: 30` MUDA o que a
    rota apaga. Se a régua viesse da constante compilada, o mesmo corte de 180 dias
    valeria para sempre e a tela de Políticas seria teatro auditável."""
    _semear(app, dias_atras=(400, 100, 40, 10))
    # com o seed v1 (180 dias), só o de 400 dias expirou
    assert (
        client.post("/api/v1/admin/purge", headers=_h()).json()["removidos"]["telemetry_event"] == 1
    )

    versao = _publicar_retencao(client, 30)
    corpo = client.post("/api/v1/admin/purge", headers=_h()).json()
    assert corpo["retencao_dias"] == 30
    assert corpo["policy_versao"] == versao
    assert corpo["removidos"]["telemetry_event"] == 3  # 400, 100 e 40 dias


def test_D01_purge_e_do_tenant_e_exige_dpo(
    client: TestClient, app: FastAPI, tokens_outro_tenant: dict[str, str]
) -> None:
    """Isolamento (§3) e RBAC (§8-M0): o purge só alcança o tenant do portador, e
    analista/solicitante não destroem dado — a função que responde pelo titular é o
    `dpo` (admin sempre passa)."""
    _semear(app, dias_atras=(400, 300))
    repo = app.state.repositorio_os
    repo.adicionar_telemetria(
        TelemetryEvent(
            tenant_id="outra-torre", tipo="sent", ts=AGORA - timedelta(days=999), fonte="ens"
        )
    )

    assert client.post("/api/v1/admin/purge", headers=_h("dev-analista")).status_code == 403
    # token de PORTAL nem chega ao RBAC: destruir dado exige login pleno (401, não 403)
    assert client.post("/api/v1/admin/purge", headers=_h("portal-dev")).status_code == 401
    valeu = client.post("/api/v1/admin/purge?aplicar=true", headers=_h("dev-admin"))
    assert valeu.status_code == 200, valeu.text

    # o registro de 999 dias do OUTRO tenant sobreviveu ao purge deste
    sobreviventes = _telemetria(app)
    assert [e.tenant_id for e in sobreviventes] == ["outra-torre"]
