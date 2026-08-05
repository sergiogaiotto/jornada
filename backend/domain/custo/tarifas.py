"""Tarifário vigente — seed §11.4 espelhando `tarifa_canal` (§4.1; migração 0005).

Valores do SDD §11.4: email 0,0018 · push 0,0005 · sms 0 · whatsapp 0,3597 (R$/envio).
`rcs` não tem tarifa no seed — o taxímetro trata canal sem tarifa como custo 0 com
AVISO (nunca inventa valor — §1.3.5). Decimal SEMPRE (dinheiro nunca em float).
"""

from decimal import Decimal

TARIFAS_VIGENTES: dict[str, Decimal] = {
    "email": Decimal("0.0018"),
    "push": Decimal("0.0005"),
    "sms": Decimal("0"),
    "whatsapp": Decimal("0.3597"),
}
