"""DataCloudPort — consulta ao Data Cloud (T5a: consulta, NÃO cópia) atrás de porta.

Porta = Protocol (§2.1). Dados crus por segmento; quem deriva waterfall/volume é o
domínio (domain/audiencia/waterfall.py). Em dev/teste o adapter lê as fixtures
(mocks/seeds/datacloud_segmentos.json — §11.2, 4 segmentos); o adapter HTTP fala com
o mock-datacloud (compose) e, em prod, com o Data Cloud real — NUNCA em teste (§1.3.5).
"""

from typing import Any, Protocol


class DataCloudPort(Protocol):
    def segmentos(self) -> list[dict[str, Any]]:
        """Segmentos publicados: [{id, nome, criterios_resumo, membros, dmos,
        republicado_ha_horas, ciclo, status}] (frescor relativo — determinístico)."""
        ...

    def segmento(self, segmento_id: str) -> dict[str, Any] | None:
        """Um segmento (mesma forma da listagem) ou None se não existir."""
        ...

    def relatorio(self, segmento_id: str) -> dict[str, Any] | None:
        """Contagens do relatório (§8-M5): {elegivel, supressoes: {lista: n},
        sem_opt_in, sobreposicao: {outro_id: n}, canais: {canal: {opt_in,
        cap_excedente, quiet_impactados, colisoes}}, frescor: {fonte:
        {atualizado_ha_horas}}} — colisões vêm do governor (A2)."""
        ...
