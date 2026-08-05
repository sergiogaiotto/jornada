"""Guard determinístico de elegibilidade (roster §7.2) — CÓDIGO PURO, ZERO LLM.

Compliance é código determinístico, nunca LLM (§1.1.3); o caminho crítico jamais
depende de LLM (§10.6). Este módulo NÃO importa LLMPort nem nada de adapters.

Responsabilidades (§8-M5):
1. `validar_sql_de_segmentacao` — varre o WHERE do SQL público: as 7 listas de
   supressão (§4.1 `lista_supressao`) E a checagem de opt-in são obrigatórias;
   qualquer ausência → `CertificadoReprovado` (A1).
2. `emitir_certificado` — emite `certificado_elegibilidade` (§4.1) com hash sha256
   do conteúdo canônico e validade (A3).
3. `certificado_vigente`/`exigir_certificado_vigente` — helpers de validade que o
   publish (M8/M9) usará para RECUSAR certificado expirado (A3).

O LLM 20b pode apenas EXPLICAR o veredito na UI (§7.2) — nunca produzi-lo.
"""

import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta

from domain.audiencia.erros import CertificadoExpirado, CertificadoReprovado
from domain.audiencia.modelos import SETE_LISTAS, CertificadoElegibilidade

# Validade do certificado: 24h, alinhada ao ciclo D-1 do Hybris (§11 fixtures; A4).
# A re-varredura last-mile no disparo (M9/M10) re-emite/atualiza (§4.1 last_mile).
VALIDADE_HORAS_CERTIFICADO = 24

_WHERE = re.compile(r"\bwhere\b", re.IGNORECASE)


def clausula_where(sql: str) -> str:
    """Trecho do SQL a partir do primeiro WHERE ('' quando não há WHERE)."""
    match = _WHERE.search(sql or "")
    return sql[match.end() :] if match else ""


def listas_ausentes_no_where(sql: str) -> list[str]:
    """Das 7 listas (§4.1), as que NÃO aparecem no WHERE (ordem de precedência)."""
    where = clausula_where(sql).lower()
    return [lista for lista in SETE_LISTAS if lista not in where]


def opt_in_ausente_no_where(sql: str) -> bool:
    """Guard também exige checagem de opt-in no WHERE (§8-M5: '7 listas + opt-in')."""
    return "opt_in" not in clausula_where(sql).lower()


def problemas_no_sql(sql: str | None) -> tuple[list[str], list[str]]:
    """(listas_faltantes, problemas) do SQL — [] e [] quando o SQL está conforme."""
    if sql is None or not sql.strip():
        return list(SETE_LISTAS), ["SQL público ausente — nada a varrer."]
    problemas: list[str] = []
    faltantes = listas_ausentes_no_where(sql)
    if faltantes:
        problemas.append(
            f"WHERE não referencia as listas de supressão: {', '.join(faltantes)} (§4.1)."
        )
    if opt_in_ausente_no_where(sql):
        problemas.append("WHERE não verifica opt-in de canal (§8-M5).")
    return faltantes, problemas


def validar_sql_de_segmentacao(sql: str | None) -> None:
    """Veredito por código (A1): 7 listas + opt-in obrigatórios no WHERE, senão reprova."""
    faltantes, problemas = problemas_no_sql(sql)
    if problemas:
        raise CertificadoReprovado(
            "Guard reprovou a certificação (§8-M5-A1): " + " · ".join(problemas),
            listas_faltantes=faltantes,
            problemas=problemas,
        )


def emitir_certificado(
    *,
    os_id: uuid.UUID,
    segmento_id: uuid.UUID,
    sql_publico: str | None,
    suprimidos: dict[str, int],
    liquido: int,
    agora: datetime,
    validade_horas: int = VALIDADE_HORAS_CERTIFICADO,
) -> CertificadoElegibilidade:
    """Emite `certificado_elegibilidade` (§4.1) com hash canônico + validade (A3).

    Hash = sha256 do JSON canônico (chaves ordenadas) de {os_id, segmento_id,
    sha256(sql), suprimidos, liquido, emitido_em} — reproduzível em auditoria.
    """
    suprimidos_contagem: dict[str, int] = {
        lista: int(suprimidos.get(lista, 0)) for lista in SETE_LISTAS
    }
    payload = {
        "os_id": str(os_id),
        "segmento_id": str(segmento_id),
        "sql_sha256": (
            hashlib.sha256(sql_publico.encode("utf-8")).hexdigest() if sql_publico else None
        ),
        "suprimidos": suprimidos_contagem,
        "liquido": int(liquido),
        "emitido_em": agora.isoformat(),
    }
    canonico = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return CertificadoElegibilidade(
        id=uuid.uuid4(),
        os_id=os_id,
        hash=hashlib.sha256(canonico.encode("utf-8")).hexdigest(),
        suprimidos=suprimidos_contagem,
        liquido=int(liquido),
        emitido_em=agora,
        valido_ate=agora + timedelta(hours=validade_horas),
        last_mile=None,  # re-varredura no disparo (M9/M10)
    )


def certificado_vigente(certificado: CertificadoElegibilidade, agora: datetime) -> bool:
    """True ⇔ dentro da validade. Helper para o portão de publish (M8/M9 — A3)."""
    return certificado.valido_ate is not None and agora <= certificado.valido_ate


def exigir_certificado_vigente(certificado: CertificadoElegibilidade, agora: datetime) -> None:
    """Publish (M8/M9) chama este helper: certificado expirado → CertificadoExpirado (A3)."""
    if not certificado_vigente(certificado, agora):
        raise CertificadoExpirado(
            f"Certificado {certificado.hash[:12]} expirado em "
            f"{certificado.valido_ate.isoformat() if certificado.valido_ate else '—'} "
            "(§8-M5-A3): recertifique a audiência antes do publish."
        )
