"""ReadModelAudienciaPort — read model de ativação para o dry-run de recontagem (§8-M5).

Porta = Protocol (§2.1). `POST /segmentos/{id}/recontar` é DRY-RUN: conta no read
model (com TTL — camada Data §2.1), nunca dispara nada. Em dev/teste o adapter lê as
fixtures (mocks/seeds/read_model_audiencia.json — §11); frescor relativo por fonte
(Hybris D-1 = 24h — §8-M5-A4).
"""

from typing import Any, Protocol


class ReadModelAudienciaPort(Protocol):
    def contagens_segmentacao(self, sql_publico: str) -> dict[str, Any]:
        """Contagens do dry-run do SQL público: {bruto, supressoes: {lista: n},
        sem_opt_in, canais: {canal: {opt_in, cap_excedente, quiet_impactados,
        colisoes}}, frescor: {fonte: {atualizado_ha_horas}}, derivado_do_sql: bool}.

        CONTRATO DE PROVENIÊNCIA (§8-M5-A5 — K05, onda 7): o dict DEVE conter
        `derivado_do_sql`. `True` significa que estas contagens são o resultado de
        EXECUTAR o `sql_publico` recebido — e implica que SQLs distintos produzem
        contagens distintas (é o que o contract test
        `tests/contract/test_read_model_audiencia_contrato.py` cobra de qualquer
        implementação). `False` significa fixture/pré-calculado: o argumento foi
        ignorado, e o certificado emitido carregará essa confissão no próprio hash.
        Um adapter que declare `True` sem consumir o SQL reprova no contract test
        (caso do alçapão) — declarar proveniência é afirmação verificada, não flag.
        """
        ...
