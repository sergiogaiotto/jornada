"""Unit do agente consultor (§7.1/§7.2/§8-M3) e do tracer Langfuse (§10.8).

Nada aqui toca rede: o SKILL.md é arquivo local, o parser é determinístico e o tracer
é exercitado desabilitado (no-op) ou com envio dublado.
"""

import json
import threading

from adapters.observabilidade.langfuse import TracerLangfuse
from agents.consultor import carregar_skill, interpretar_saida, montar_mensagens
from app.config import Settings
from application.ports.observabilidade import TracerPort


# --------------------------------------------------------------- SKILL.md (§7.1)
def test_skill_canonica_do_consultor() -> None:
    """Front-matter §7.1: consultor é especialista 120b da etapa pedido (roster §7.2)."""
    skill = carregar_skill()
    assert skill.nome == "consultor"
    assert skill.versao == "1.0"
    assert skill.camada == "especialista"
    assert skill.modelo_perfil == "120b"
    assert skill.etapa == "pedido"
    assert skill.exige_evidencia is True
    assert "completude" in skill.corpo.lower()  # corpo instrui: completude é do código


def test_montar_mensagens_sem_pii_e_com_contexto() -> None:
    """Prompt: system = corpo da skill; user = contexto SEM o bloco solicitante (§1.3.5)."""
    skill = carregar_skill()
    conteudo = {"objetivo": {"valor": "Upgrade 5G", "inferido": False}}
    mensagens = montar_mensagens(skill, conteudo, ["verba", "janela"], "qual verba usar?")
    assert [m["role"] for m in mensagens] == ["system", "user"]
    contexto = json.loads(mensagens[1]["content"])
    assert contexto["conteudo_atual"] == {"objetivo": "Upgrade 5G"}
    assert contexto["faltantes"] == ["verba", "janela"]
    assert contexto["mensagem_do_solicitante"] == "qual verba usar?"
    assert "solicitante" not in contexto  # PII nunca em prompt (§1.3.5/§10.2)


# ------------------------------------------------- Guarda-corpos da saída do LLM
def test_interpretar_saida_json_valido() -> None:
    texto = json.dumps(
        {
            "resposta": "Sugiro R$ 500k.",
            "inferencias": [{"campo": "verba", "valor": "R$ 500k", "evidencias": ["OS-2025-0311"]}],
        }
    )
    saida = interpretar_saida(texto)
    assert saida.resposta == "Sugiro R$ 500k."
    assert len(saida.inferencias) == 1
    assert saida.inferencias[0].campo == "verba"
    assert saida.inferencias[0].evidencias == ("OS-2025-0311",)


def test_inferencia_sem_evidencia_e_descartada() -> None:
    """A3 por construção: exige_evidencia → inferência sem evidências não entra."""
    texto = json.dumps(
        {
            "resposta": "ok",
            "inferencias": [
                {"campo": "verba", "valor": "R$ 1", "evidencias": []},
                {"campo": "janela", "valor": "out/26"},  # sem a chave
                {"campo": "oferta", "valor": "20GB", "evidencias": ["precedente X"]},
            ],
        }
    )
    saida = interpretar_saida(texto, exige_evidencia=True)
    assert [i.campo for i in saida.inferencias] == ["oferta"]
    # sem exigência (skill futura), passariam as de valor presente
    assert len(interpretar_saida(texto, exige_evidencia=False).inferencias) == 3


def test_campo_fora_do_contrato_e_valor_vazio_sao_descartados() -> None:
    """§1.3.5: nunca inventar campo fora do SDD; valor vazio não infere nada."""
    texto = json.dumps(
        {
            "resposta": "ok",
            "inferencias": [
                {"campo": "cpf_do_cliente", "valor": "x", "evidencias": ["e"]},
                {"campo": "verba", "valor": "  ", "evidencias": ["e"]},
                "lixo-nao-dict",
            ],
        }
    )
    assert interpretar_saida(texto).inferencias == ()


def test_json_malformado_degrada_para_resposta_textual() -> None:
    saida = interpretar_saida("desculpe, não consegui formatar")
    assert saida.resposta == "desculpe, não consegui formatar"
    assert saida.inferencias == ()
    # JSON embutido em prosa ainda é aproveitado
    embutido = 'Segue: {"resposta": "oi", "inferencias": []} — fim.'
    assert interpretar_saida(embutido).resposta == "oi"


# ------------------------------------------------------- Tracer Langfuse (§10.8)
def test_tracer_desabilitado_e_noop_sem_rede() -> None:
    tracer = TracerLangfuse(Settings(_env_file=None, langfuse_enabled=False))
    assert isinstance(tracer, TracerPort)
    tracer.trace(trace_id="t-1", nome="consultor.mensagem", metadados={}, spans=[])  # não levanta


def test_tracer_fire_and_forget_engole_falhas(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """§10.8: queda do Langfuse NUNCA propaga — envio falho é silencioso."""
    tracer = TracerLangfuse(Settings(_env_file=None, langfuse_enabled=True))

    def _explode(**_: object) -> None:
        raise RuntimeError("langfuse fora do ar")

    monkeypatch.setattr(tracer, "_enviar", _explode)
    tracer._enviar_seguro(trace_id="t-1", nome="x", metadados={}, spans=[])  # não levanta
    antes = set(threading.enumerate())
    tracer.trace(trace_id="t-1", nome="x", metadados={}, spans=[])  # thread daemon, não levanta
    # join antes do undo do monkeypatch: a thread deve morrer no dublê `_explode` — jamais
    # alcançar o `_enviar` real (import do SDK/rede), preservando §1.3.5 sem corrida
    for pendente in set(threading.enumerate()) - antes:
        pendente.join(timeout=5)
