"""Priors v1 do simulador (§6: "priors (`calibracao_prior` do tipo de campanha)").

Enquanto a tabela `calibracao_prior` (§4.1) não tem linhas publicadas (o ciclo de
calibração chega com o M11 `calibrate`), o simulador usa este prior default v1 —
valores conservadores coerentes com o seed §11.4 (lift +24,1%, ROAS 18,5x na OS demo).
Formato espelha `calibracao_prior.priors` (jsonb): quando o M11 publicar priors por
tipo de campanha, o serviço passa a preferi-los sem tocar o motor (código puro).
"""

from typing import Any

PRIORS_DEFAULT: dict[str, Any] = {
    "versao": 1,
    "canais": {  # taxas por envio: entrega e conversão atribuída ao canal
        "email": {"entrega": 0.97, "conversao": 0.032},
        "sms": {"entrega": 0.98, "conversao": 0.021},
        "push": {"entrega": 0.90, "conversao": 0.012},
        "whatsapp": {"entrega": 0.99, "conversao": 0.045},
        "rcs": {"entrega": 0.95, "conversao": 0.025},
    },
    "engajamento": {"open": 0.42, "click": 0.11},  # engagementSplit (§5.2)
    "conversao_organica": 0.008,  # baseline do holdout (lift = tratado − holdout)
    "classes_frequencia": {"saturado": 0.20, "ok": 0.60, "sub": 0.20},  # governor
    "mult_classe": {"saturado": 0.60, "ok": 1.00, "sub": 1.15},  # propensão por classe
    "incerteza_relativa": 0.15,  # desvio dos multiplicadores por run (Monte Carlo)
    "ticket_medio": 89.90,  # R$/conversão quando o briefing não informa
    "hora_pico": 20,  # distribuição de horários das personas (STO §6)
    "desvio_horas": 3,
}
