"""Unit do TracerLangfuse — o que sai para o Langfuse sai do PERÍMETRO (§10.2/§10.8).

Duas coisas distintas são provadas aqui, e a distinção importa para a auditoria:

1. **Hoje já estava coberto — por CONVENÇÃO.** Nenhum dos oito `tracer.trace(...)` da
   aplicação manda texto livre: só tenant, os_id, nome do agente, versão da skill,
   perfil do modelo e latência. `test_chamadores_reais_nao_mandam_texto_livre` congela
   isso: se alguém acrescentar `{"pergunta": pergunta}` a um span, o teste morre.
2. **Convenção não é controle.** Por isso o adapter passou a sanitizar na saída, que é
   o último ponto antes da rede e o único que nenhum chamador futuro consegue
   esquecer. O `trace_id` fica de fora de propósito: é o UUID da `invocacao` (§4.1), a
   chave que liga o trace ao ledger — mascarar ali quebraria a correlação.

Nenhuma rede: o envio é interceptado sobrescrevendo `_enviar`.
"""

import threading
from typing import Any

from adapters.observabilidade.langfuse import TracerLangfuse
from app.config import Settings

CPF = "529.982.247-25"
EMAIL = "joao.silva@clientereal.com.br"


class _TracerEspiao(TracerLangfuse):
    """Captura o que o adapter entregaria ao SDK, sem SDK e sem rede."""

    def __init__(self) -> None:
        super().__init__(Settings(_env_file=None, langfuse_enabled=True))
        self.enviado: dict[str, Any] = {}
        self.chegou = threading.Event()

    def _enviar(self, **kwargs: Any) -> None:
        self.enviado = kwargs
        self.chegou.set()


def _tracar(**kwargs: Any) -> dict[str, Any]:
    espiao = _TracerEspiao()
    espiao.trace(**kwargs)
    assert espiao.chegou.wait(timeout=5), "o envio fire-and-forget (§10.8) não ocorreu"
    return espiao.enviado


def test_pii_em_metadados_e_spans_nao_atravessa_a_fronteira() -> None:
    """Chamador descuidado (o serviço novo de amanhã) põe texto livre no trace: o
    adapter mascara antes de entregar. Identificadores e métricas seguem intactos."""
    enviado = _tracar(
        trace_id="6f1c1e6e-0000-4000-8000-000000000001",
        nome="insight.perguntar",
        metadados={"tenant": "torre-movel", "pergunta": f"quem é o CPF {CPF}?"},
        spans=[{"nome": "generate", "latencia_ms": 1200, "eco": [f"contato {EMAIL}"]}],
    )
    assert CPF not in str(enviado) and EMAIL not in str(enviado)
    assert enviado["metadados"]["pergunta"] == "quem é o CPF [CPF]?"
    assert enviado["metadados"]["tenant"] == "torre-movel"
    assert enviado["spans"][0]["eco"] == ["contato [EMAIL]"]
    assert enviado["spans"][0]["latencia_ms"] == 1200, "métrica não é texto: passa intacta"
    # correlação com o ledger `invocacao` preservada (§10.8)
    assert enviado["trace_id"] == "6f1c1e6e-0000-4000-8000-000000000001"


def test_desabilitado_e_no_op_absoluto() -> None:
    """`LANGFUSE_ENABLED=false` (modo de TODO teste): nem thread, nem sanitização, nem
    rede — a aplicação nunca depende do Langfuse (§10.8)."""

    class _Nunca(TracerLangfuse):
        def _enviar(self, **kwargs: Any) -> None:
            raise AssertionError("no-op violado: houve envio com LANGFUSE_ENABLED=false")

    _Nunca(Settings(_env_file=None, langfuse_enabled=False)).trace(
        trace_id="x", nome="n", metadados={"cpf": CPF}, spans=[]
    )


def test_chamadores_reais_nao_mandam_texto_livre() -> None:
    """Prova (2) do cabeçalho: os chamadores REAIS só mandam identificadores e métricas.

    Lê o código dos serviços em vez de confiar na memória — o conjunto de chaves de
    `metadados` é fechado por contrato (§10.8) e este teste é o portão que o mantém
    fechado quando alguém acrescentar um trace novo."""
    import re
    from pathlib import Path

    servicos = Path(__file__).resolve().parents[2] / "application" / "services"
    chaves_permitidas = {
        "tenant",
        "os_id",
        "agente",
        "skill_versao",
        "modelo_perfil",
        "pagina",
        "tags",
    }
    encontrados = 0
    for arquivo in sorted(servicos.glob("*.py")):
        texto = arquivo.read_text(encoding="utf-8")
        for bloco in re.findall(r"metadados=\{(.*?)\n\s*\},", texto, re.DOTALL):
            encontrados += 1
            chaves = set(re.findall(r'"([a-z_]+)":', bloco))
            assert chaves <= chaves_permitidas, (
                f"{arquivo.name}: chave nova em `metadados` de trace "
                f"({chaves - chaves_permitidas}). "
                "§10.2: o Langfuse é externo — só identificador e métrica saem daqui."
            )
    assert encontrados >= 8, "os traces dos serviços sumiram — o portão ficou sem porta"
