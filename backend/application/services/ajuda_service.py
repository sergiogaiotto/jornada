"""Caso de uso do M-Guia · chat "IA, me ajude com esta página" (§8-M-Guia) —
`POST /ajuda/perguntar`.

O agente ajuda (LLM 20b — §3: triagens/resumos de UI) responde SÓ sobre a
plataforma Jornada e a página em questão: o CONTEXTO é o conteúdo do guia da
página, enviado pelo front (fonte única — a API valida ≤ 8k chars no contrato).
Recusa de assunto fora da plataforma é instrução da skill (§7.1) — o chat é
informativo: nenhuma ação de domínio executa a partir dele, então não há
guarda-corpo de execução a aplicar. Toda pergunta grava `invocacao` (via_ai —
LGPD Art. 20; pergunta MASCARADA §10.2, `os_id` NULL: ajuda não é de uma OS) +
trace Langfuse fire-and-forget com trace_id = invocacao.id (§10.8). Hub fora
(`forced_off` §10.6) → `LLMIndisponivel` → 503 degraded na camada de API; o front
oferece o guia estático como modo manual.
"""

import uuid
from typing import Any

from agents import ajuda as agente_ajuda
from application.ports.clock import ClockPort
from application.ports.llm import LLMPort
from application.ports.observabilidade import TracerPort
from application.ports.publicacoes_ia import PublicacoesIaPort
from application.ports.repositorio_ajuda import RepositorioAjuda
from application.services import portao_ia
from domain.agentes.modelos import Invocacao, agente_uuid


class ServicoAjuda:
    def __init__(
        self,
        repositorio: RepositorioAjuda,
        relogio: ClockPort,
        llm: LLMPort,
        tracer: TracerPort,
        publicacoes_ia: PublicacoesIaPort,
    ) -> None:
        self._repo = repositorio
        self._relogio = relogio
        self._llm = llm
        self._tracer = tracer
        self._publicacoes_ia = publicacoes_ia  # política de IA PUBLICADA (§10.2)

    # ------------------------------------------------------ POST /ajuda/perguntar
    def perguntar(
        self,
        tenant_id: str,
        *,
        pagina: str,
        pergunta: str,
        contexto: str,
        historico: list[dict[str, str]],
        portador_id: uuid.UUID,
    ) -> dict[str, Any]:
        skill = agente_ajuda.carregar()
        inicio = self._relogio.agora()
        portao = portao_ia.de(self._publicacoes_ia, tenant_id)  # política PUBLICADA (§10.2)

        # §10.2 (C02): sanea ANTES do prompt — o histórico da sessão também é texto
        # do usuário e entra nas mensagens; mascarar só no ledger deixava o prompt
        # vazando (achado do UAT #3). `contexto` é o guia público, não é do usuário.
        # `sanear` mantém o piso do C02 (mascarar) e passa a BLOQUEAR a chamada quando
        # a política do tenant assim disser — antes, a regra era constante no código.
        pergunta = portao.sanear(pergunta)
        historico = [
            {**turno, "texto": portao.sanear(turno.get("texto", ""))} for turno in historico
        ]
        mensagens = agente_ajuda.montar_mensagens(
            skill, pagina=pagina, contexto=contexto, historico=historico, pergunta=pergunta
        )
        # (f) §7.2: o perfil que a skill pede é CONFERIDO contra a política do tenant —
        # imediatamente antes da chamada, para nenhum caminho dinâmico escapar do portão.
        portao.autorizar_modelo(skill.nome, skill.modelo_perfil)
        texto, tokens_uso = self._llm.chat(mensagens, perfil=skill.modelo_perfil)  # 503 se fora
        resposta = texto.strip()
        if not resposta:  # resposta vazia: fallback determinístico — nada inventado (§1.3.5)
            resposta = (
                "Não consegui elaborar uma resposta agora. As abas do guia desta página "
                "(O que é, Campos da tela, Exemplo prático...) cobrem o conteúdo completo."
            )

        fim = self._relogio.agora()
        invocacao = Invocacao(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            os_id=None,  # ajuda é da PÁGINA, não de uma OS (§4.1: os_id NULL)
            agente_id=agente_uuid(skill.nome),
            skill_versao=skill.versao,
            usuario_portador=portador_id,
            # (b) §10.4: `reter_prompt: false` na política redige o texto ANTES da
            # gravação — não depende de o purge rodar. `pergunta` já vem saneada (C02).
            input=portao.reter_input(
                {
                    "pagina": pagina,
                    "pergunta": pergunta,  # §10.2: já mascarada na fronteira (C02)
                    "contexto_chars": len(contexto),  # o contexto é o guia público — só o tamanho
                    "historico_len": len(historico),
                }
            ),
            output=portao.reter_output({"resposta": resposta}),
            tokens=tokens_uso,  # I04: usage do provedor — §10.8
            latencia_ms=int((fim - inicio).total_seconds() * 1000),
            created_at=fim,
        )
        self._repo.adicionar_invocacao(invocacao)
        self._tracer.trace(  # §10.8: fire-and-forget, trace_id = invocacao.id
            trace_id=str(invocacao.id),
            nome="ajuda.perguntar",
            metadados={
                "tenant": tenant_id,
                "pagina": pagina,
                "agente": skill.nome,
                "skill_versao": skill.versao,
                "modelo_perfil": skill.modelo_perfil,
            },
            spans=[{"nome": "generate", "modelo_perfil": skill.modelo_perfil}],
        )
        return {"resposta": resposta, "pagina": pagina, "invocacao_id": invocacao.id}
