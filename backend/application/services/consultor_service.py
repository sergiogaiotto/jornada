"""Casos de uso do M3 · Intake & Consultor (§8-M3) — orquestram o domínio via ports.

- `criar_pedido` (POST /pedidos): portal via link com token; conteúdo direto do
  solicitante entra com `inferido:false`; completude/faltantes derivados por código.
- `conversar` (POST /pedidos/{id}/mensagem): consultor (LLM 120b — roster §7.2) conversa
  e infere; inferências entram com `inferido:true` + evidências; grava o ledger
  `invocacao` (via_ai), evento `agent.invoked` (§2.3) e trace Langfuse fire-and-forget
  com trace_id = invocacao.id (§10.8). LLM indisponível → LLMIndisponivel (API: 503).
  C01 (§10.6): pedido para BURLAR COMPLIANCE é detectado por código antes do LLM
  (domain/agentes/compliance) — a recusa inegociável é carimbada na resposta e a
  tentativa fica marcada no ledger (`compliance_bypass_tentado`).
- `converter` (POST /pedidos/{id}/converter): exige completude=100 (A2 → 409); cria OS
  com briefing pré-preenchido — campos `inferido:true` até confirmação (A3).
- CRUD (emenda §8-M3 — o Portal do Solicitante foi aposentado; a criação vive na app):
  `listar_pedidos` (GET /pedidos — arquivados fora por padrão) · `obter_pedido`
  (GET /pedidos/{id}) · `editar_campos` (PATCH /pedidos/{id}/campos — edição manual
  direta vira `inferido:false`; completude recalculada por CÓDIGO) · `arquivar`
  (POST /pedidos/{id}/arquivar — soft e idempotente; convertido → 409; arquivado
  bloqueia conversa/edição/conversão).
- `obter_briefing`/`editar_briefing` (GET/PATCH /os/{id}/briefing[/{campo}]): confirmar
  ou editar um campo torna-o `inferido:false` (toque humano = confirmação).

PII (§10.2 — emenda C02 + achado 9 do UAT #5): TODA porta de texto livre deste serviço
mascara na FRONTEIRA, não na saída. São quatro: `conversar` (mensagem), `criar_pedido`
(conteudo), `editar_campos` (campos) e `editar_briefing` (campo + valor), mais o `nome`
opcional do `converter`. O original nunca é persistido — logo prompt, RAG, ledger,
outbox, nome da OS e página do link mágico só podem ver o texto já sanitizado.

Nas portas do briefing a CHAVE conta tanto quanto o valor: `conteudo`/`campos` são
`dict[str, Any]` ABERTO, sem enum de campos, então o nome do campo é digitação do
usuário — e vira chave persistida e item do payload de `pedido.campos_editados`. Por
isso usam `mascarar_campos` (chave + valor), não `mascarar_estrutura` (só valores).
"""

import uuid
from collections.abc import Sequence
from typing import Any

from agents import consultor as agente_consultor
from application.ports.clock import ClockPort
from application.ports.llm import LLMPort, soma_tokens
from application.ports.observabilidade import TracerPort
from application.ports.publicacoes_ia import PublicacoesIaPort
from application.ports.repositorio_intake import RepositorioIntake
from application.ports.repositorio_os import RepositorioOs
from application.services import portao_ia
from application.services.os_service import ServicoOs
from application.services.retriever_service import RetrieverService, evidencias_para_contexto
from domain.agentes import compliance
from domain.agentes.modelos import Invocacao, agente_uuid
from domain.campanha.erros import NaoEncontrado
from domain.campanha.modelos import OS, EventoDominio
from domain.intake import completude as regras_completude
from domain.intake.erros import (
    CampoBriefingDesconhecido,
    ConversaoIncompleta,
    PedidoArquivado,
    PedidoJaConvertido,
)
from domain.intake.modelos import Pedido
from domain.privacidade import mascarar_campos, mascarar_estrutura

_AUSENTE: Any = object()  # sentinela: PATCH briefing sem `valor` = apenas confirmar


class ServicoConsultor:
    def __init__(
        self,
        repositorio: RepositorioIntake,
        repositorio_os: RepositorioOs,
        relogio: ClockPort,
        servico_os: ServicoOs,
        llm: LLMPort,
        tracer: TracerPort,
        publicacoes_ia: PublicacoesIaPort,
        retriever: RetrieverService | None = None,
    ) -> None:
        self._repo = repositorio
        self._repo_os = repositorio_os
        self._relogio = relogio
        self._servico_os = servico_os
        self._llm = llm
        self._tracer = tracer
        self._publicacoes_ia = publicacoes_ia  # política de IA PUBLICADA (§10.2)
        self._retriever = retriever  # A11: precedentes (§7.4); None → sem RAG

    # ---------------------------------------------------------------- Pedido
    def criar_pedido(
        self, tenant_id: str, *, solicitante: dict[str, Any], conteudo: dict[str, Any]
    ) -> Pedido:
        """POST /pedidos — conteúdo plano {campo: valor} vira {campo: {valor, inferido:false}}.

        §10.2 (achado 9 do UAT #5): o BRIEFING é fronteira de entrada de texto livre
        igual à conversa. O C02 mascarava só `mensagem` e deixava esta porta aberta —
        e o conteúdo daqui vai para o prompt do consultor (`montar_mensagens` recebe
        `pedido.conteudo`), para o ledger, para o NOME da OS (`_nome_padrao` usa o
        `objetivo`) e daí para a página do link mágico. Mascara-se na ENTRADA: o
        original nunca é persistido, então nenhum caminho a jusante pode vazá-lo.
        """
        agora = self._relogio.agora()
        # CHAVE e valor: `conteudo` é `dict[str, Any]` aberto (sem enum de campos), logo
        # o nome do campo também é digitação — e vira chave persistida, item do payload
        # de evento e nome exibido. Ver `mascarar_campos`.
        conteudo = mascarar_campos(conteudo)
        pedido = Pedido(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            solicitante=dict(solicitante),
            conteudo={
                campo: {"valor": valor, "inferido": False} for campo, valor in conteudo.items()
            },
            completude=0.0,
            created_at=agora,
            updated_at=agora,
        )
        regras_completude.atualizar(pedido)  # determinístico (§8-M3)
        self._repo.adicionar_pedido(pedido)
        return pedido

    def conversar(
        self, tenant_id: str, pedido_id: uuid.UUID, *, mensagem: str, portador_id: uuid.UUID
    ) -> tuple[Pedido, str]:
        """POST /pedidos/{id}/mensagem — devolve (pedido atualizado, resposta do consultor).

        §10.2 (C02): a fala do solicitante é SANEADA na fronteira; daqui para baixo
        só existe `mensagem` sanitizada — prompt, RAG e ledger recebem a mesma coisa.
        `sanear` mantém o piso do C02 (mascarar) e passa a BLOQUEAR a chamada quando a
        política do tenant marcar a categoria detectada.
        """
        portao = portao_ia.de(self._publicacoes_ia, tenant_id)  # política PUBLICADA
        mensagem = portao.sanear(mensagem)
        pedido = self._exigir_pedido(tenant_id, pedido_id)
        if pedido.estado == "convertido":
            raise PedidoJaConvertido(
                f"Pedido {pedido_id} já convertido em OS; converse pela OS (§8-M3)."
            )
        self._exigir_nao_arquivado(pedido)
        skill = agente_consultor.carregar_skill()
        # C01 (§10.6): tentativa de burlar compliance é detectada por CÓDIGO, antes de
        # qualquer LLM — a recusa não pode depender do humor do modelo (ver
        # domain/agentes/compliance.py).
        burla = compliance.detectar_burla_de_compliance(mensagem)
        # A11 (§7.4): precedentes citáveis das bases da skill (historico_campanhas/
        # ofertas) — evidência ADICIONAL (a fala do solicitante continua bastando);
        # hub de embeddings fora → [] (degrade suave).
        precedentes = (
            self._retriever.buscar(tenant_id, mensagem, bases=skill.bases_rag)
            if self._retriever is not None
            else []
        )
        mensagens = agente_consultor.montar_mensagens(
            skill,
            pedido.conteudo,
            pedido.faltantes,
            mensagem,
            precedentes=evidencias_para_contexto(precedentes),
            burla_compliance=burla,
        )
        inicio = self._relogio.agora()
        # (f) §7.2: perfil do roster CONFERIDO contra a política antes da chamada.
        portao.autorizar_modelo(skill.nome, skill.modelo_perfil)
        texto, tokens_uso = self._llm.chat(mensagens, perfil=skill.modelo_perfil)  # 503 se fora
        saida = agente_consultor.interpretar_saida(texto, exige_evidencia=skill.exige_evidencia)
        # §7.3: modelo que conversa sem preencher `inferencias` recebe reforço de
        # contrato (achado da validação com o hub real — FakeLLM nunca exercitava).
        saida_original = saida  # 1ª resposta ao SOLICITANTE — é a que ele pode ver (A4)
        max_retries = int(skill.meta.get("max_retries", 2))
        tentativa = 0
        while (
            not saida.inferencias
            and pedido.faltantes
            and len(mensagem.strip()) >= 20
            and tentativa < max_retries
        ):
            tentativa += 1
            mensagens = [
                *mensagens,
                {"role": "assistant", "content": texto},
                {
                    "role": "user",
                    "content": (
                        "SISTEMA: a mensagem do solicitante acima contém informações de "
                        "briefing. Extraia AGORA em `inferencias` TODOS os campos "
                        "obrigatórios presentes na conversa, com evidencias: "
                        '["informado pelo solicitante"]. Se realmente nenhum campo '
                        "estiver presente, devolva inferencias: []."
                    ),
                },
            ]
            portao.autorizar_modelo(skill.nome, skill.modelo_perfil)  # (f) idem no retry
            texto, tokens_retry = self._llm.chat(mensagens, perfil=skill.modelo_perfil)
            tokens_uso = soma_tokens(tokens_uso, tokens_retry)  # I04: linha única soma o retry
            saida = agente_consultor.interpretar_saida(texto, exige_evidencia=skill.exige_evidencia)
        if tentativa and not saida.inferencias:
            # A4 (fix vazamento): reforço esgotado SEM inferências → preserva a resposta
            # original da 1ª chamada; a resposta ao reprompt "SISTEMA:" jamais vaza.
            # I04: os tokens do retry DESCARTADO ficam somados no ledger de propósito —
            # é custo real cobrado pelo provedor (`soma_tokens` nunca subrepresenta);
            # `output` preservar a 1ª resposta e `tokens` incluir a descartada não é
            # inconsistência, é a diferença entre resposta exibida e custo incorrido.
            saida = saida_original
        if burla:
            # C01: a recusa é CARIMBADA por código na frente da resposta — o solicitante
            # lê primeiro que é impossível por construção e só depois a consultoria do
            # modelo com o que É possível. Assim a plataforma nunca "normaliza" a ordem
            # ilegal como risco a monitorar, aconteça o que acontecer com o LLM.
            saida = agente_consultor.SaidaConsultor(
                resposta=f"{compliance.RECUSA_INEGOCIAVEL}\n\n{saida.resposta}".strip(),
                inferencias=saida.inferencias,  # o que ele contou de briefing continua valendo
            )
        fim = self._relogio.agora()

        for inf in saida.inferencias:  # A3: inferido:true + evidências (precedentes)
            pedido.conteudo[inf.campo] = {
                "valor": inf.valor,
                "inferido": True,
                "evidencias": list(inf.evidencias),
            }
        regras_completude.atualizar(pedido)  # completude é CÓDIGO, nunca LLM (§8-M3)
        pedido.updated_at = fim
        self._repo.salvar_pedido(pedido)

        invocacao = self._registrar_invocacao(
            pedido,
            skill,
            mensagem,
            saida,
            portador_id,
            inicio,
            fim,
            portao,
            burla=burla,
            tokens=tokens_uso,
        )
        self._tracer.trace(  # §10.8: fire-and-forget, trace_id = invocacao.id
            trace_id=str(invocacao.id),
            nome="consultor.mensagem",
            metadados={
                "tenant": tenant_id,
                "os_id": str(pedido.os_id) if pedido.os_id else None,
                "agente": skill.nome,
                "skill_versao": skill.versao,
                "modelo_perfil": skill.modelo_perfil,
            },
            spans=[
                {"nome": "rag_retrieve", "evidencias": len(precedentes)},  # §10.8
                {"nome": "generate", "latencia_ms": invocacao.latencia_ms},
            ],
        )
        return pedido, saida.resposta

    def converter(
        self,
        tenant_id: str,
        pedido_id: uuid.UUID,
        *,
        created_by: uuid.UUID,
        actor: str,
        nome: str | None = None,
        tshirt: str = "M",
    ) -> OS:
        """POST /pedidos/{id}/converter — exige completude=100 (A2); briefing herda
        `inferido:true` dos campos inferidos até confirmação humana.

        §10.2: `nome` é texto livre do usuário e vira o NOME da OS — que aparece na
        página pública do link mágico de aprovação (§8-M8). Mascarado na fronteira; o
        nome derivado (`_nome_padrao`) já nasce limpo porque o briefing é mascarado
        na entrada."""
        nome = portao_ia.de(self._publicacoes_ia, tenant_id).sanear(nome) if nome else nome
        pedido = self._exigir_pedido(tenant_id, pedido_id)
        if pedido.estado == "convertido":
            raise PedidoJaConvertido(f"Pedido {pedido_id} já convertido (os_id={pedido.os_id}).")
        self._exigir_nao_arquivado(pedido)
        regras_completude.atualizar(pedido)  # nunca confia em estado gravado: recalcula
        if pedido.completude < 100.0:
            raise ConversaoIncompleta(
                f"Converter exige completude=100 (§8-M3-A2); atual {pedido.completude}%, "
                f"faltantes: {', '.join(pedido.faltantes)}.",
                pedido.faltantes,
            )
        briefing = {campo: dict(entrada) for campo, entrada in pedido.conteudo.items()}
        os_ = self._servico_os.criar_os(
            tenant_id,
            nome=nome or self._nome_padrao(pedido),
            tshirt=tshirt,
            briefing=briefing,
            created_by=created_by,
        )
        pedido.estado = "convertido"
        pedido.os_id = os_.id
        pedido.updated_at = self._relogio.agora()
        self._repo.salvar_pedido(pedido)
        self._evento(
            tenant_id,
            os_.id,
            "pedido.convertido",
            {"pedido_id": str(pedido.id), "os_codigo": os_.codigo},
            actor,
        )
        return os_

    # ------------------------------------------------- CRUD de pedidos (emenda §8-M3)
    def listar_pedidos(self, tenant_id: str, *, incluir_arquivados: bool = False) -> list[Pedido]:
        """GET /pedidos — lista do tenant, mais recente primeiro; arquivados (soft)
        ficam FORA por padrão (`incluir_arquivados=True` os traz de volta)."""
        pedidos = self._repo.listar_pedidos(tenant_id)
        if incluir_arquivados:
            return pedidos
        return [p for p in pedidos if p.estado != "arquivado"]

    def obter_pedido(self, tenant_id: str, pedido_id: uuid.UUID) -> Pedido:
        """GET /pedidos/{id} — pedido completo (arquivado continua legível: soft)."""
        return self._exigir_pedido(tenant_id, pedido_id)

    def editar_campos(
        self, tenant_id: str, pedido_id: uuid.UUID, campos: dict[str, Any], *, actor: str
    ) -> Pedido:
        """PATCH /pedidos/{id}/campos — edição manual direta `{campo: valor}`.

        Cada campo editado vira `inferido:false` (toque humano = confirmação, A3);
        evidências de inferência anterior são preservadas para auditoria. Completude e
        faltantes são SEMPRE recalculados por código (§8-M3). Convertido/arquivado → 409
        (após conversão a edição é no briefing da OS).

        §10.2 (achado 9 do UAT #5): esta é a MESMA fronteira de `criar_pedido` — quem
        não digitou PII na criação pode digitá-la aqui. Mascara-se na entrada, CHAVE e
        valor: a chave vira nome de campo persistido e, pior, entra em claro no payload
        de `pedido.campos_editados` (`{"campos": sorted(campos)}`), que é o que a
        integração externa lê no outbox (§2.3)."""
        campos = mascarar_campos(campos)
        pedido = self._exigir_pedido(tenant_id, pedido_id)
        if pedido.estado == "convertido":
            raise PedidoJaConvertido(
                f"Pedido {pedido_id} já convertido; edite pelo briefing da OS {pedido.os_id}."
            )
        self._exigir_nao_arquivado(pedido)
        for campo, valor in campos.items():
            entrada = pedido.conteudo.get(campo)
            nova: dict[str, Any] = dict(entrada) if isinstance(entrada, dict) else {}
            nova["valor"] = valor
            nova["inferido"] = False
            pedido.conteudo[campo] = nova
        regras_completude.atualizar(pedido)  # completude é CÓDIGO, nunca LLM (§8-M3)
        pedido.updated_at = self._relogio.agora()
        self._repo.salvar_pedido(pedido)
        if campos:
            self._evento_pedido(pedido, "pedido.campos_editados", {"campos": sorted(campos)}, actor)
        return pedido

    def arquivar(self, tenant_id: str, pedido_id: uuid.UUID, *, actor: str) -> Pedido:
        """POST /pedidos/{id}/arquivar — soft e idempotente; convertido → 409 (o rastro
        pedido→OS é história de governança, não se arquiva)."""
        pedido = self._exigir_pedido(tenant_id, pedido_id)
        if pedido.estado == "convertido":
            raise PedidoJaConvertido(
                f"Pedido {pedido_id} já convertido (os_id={pedido.os_id}); não se arquiva."
            )
        if pedido.estado == "arquivado":
            return pedido  # idempotente (mutações aceitam repetição — convenções §8)
        pedido.estado = "arquivado"
        pedido.updated_at = self._relogio.agora()
        self._repo.salvar_pedido(pedido)
        self._evento_pedido(pedido, "pedido.arquivado", {}, actor)
        return pedido

    # -------------------------------------------------------------- Briefing
    def obter_briefing(self, tenant_id: str, os_id: uuid.UUID) -> dict[str, Any]:
        return self._servico_os.obter_os(tenant_id, os_id).briefing

    def editar_briefing(
        self,
        tenant_id: str,
        os_id: uuid.UUID,
        campo: str,
        *,
        valor: Any = _AUSENTE,
        actor: str,
    ) -> dict[str, Any]:
        """PATCH /os/{id}/briefing/{campo} — confirma (sem valor) ou edita (com valor);
        em ambos os casos o campo vira `inferido:false` (confirmação humana, A3).

        §10.2 (achado 9 do UAT #5): terceira porta do briefing — depois da conversão a
        edição acontece aqui, e o valor segue para o prompt de todo agente que lê o
        briefing (engineer, flow, criativo). Mascarado na entrada, como as outras duas.
        `campo` também passa pelo sanitizador: ele vem do PATH da URL (texto livre) e
        é ecoado na mensagem de erro 404 e no payload do evento."""
        campo = portao_ia.de(self._publicacoes_ia, tenant_id).sanear(campo)
        if valor is not _AUSENTE:
            valor = mascarar_estrutura(valor)
        os_ = self._servico_os.obter_os(tenant_id, os_id)
        entrada = os_.briefing.get(campo)
        if valor is _AUSENTE and entrada is None:
            raise CampoBriefingDesconhecido(
                f"Campo {campo!r} não existe no briefing da OS {os_id} (nada a confirmar)."
            )
        nova: dict[str, Any] = dict(entrada) if isinstance(entrada, dict) else {"valor": entrada}
        if valor is not _AUSENTE:
            nova["valor"] = valor
        nova["inferido"] = False
        os_.briefing[campo] = nova
        os_.updated_at = self._relogio.agora()
        self._repo_os.salvar_os(os_)
        self._evento(
            tenant_id,
            os_.id,
            "briefing.campo_atualizado",
            {"campo": campo, "confirmado": valor is _AUSENTE},
            actor,
        )
        return os_.briefing

    # --------------------------------------------------------------- Interno
    def _exigir_pedido(self, tenant_id: str, pedido_id: uuid.UUID) -> Pedido:
        pedido = self._repo.obter_pedido(tenant_id, pedido_id)
        if pedido is None:
            raise NaoEncontrado(f"Pedido {pedido_id} não encontrado no tenant {tenant_id!r}.")
        return pedido

    def _exigir_nao_arquivado(self, pedido: Pedido) -> None:
        if pedido.estado == "arquivado":
            raise PedidoArquivado(
                f"Pedido {pedido.id} está arquivado (soft): não conversa, não edita, "
                "não converte (§8-M3 CRUD)."
            )

    def _evento_pedido(
        self, pedido: Pedido, tipo: str, payload: dict[str, Any], actor: str
    ) -> None:
        """Outbox de pedido (§2.3): os_id pode ser None antes da conversão."""
        self._repo.adicionar_evento(
            EventoDominio(
                tenant_id=pedido.tenant_id,
                os_id=pedido.os_id,
                type=tipo,
                payload={"pedido_id": str(pedido.id), **payload},
                actor=actor,
                via_ai=False,
                created_at=self._relogio.agora(),
            )
        )

    def _registrar_invocacao(
        self,
        pedido: Pedido,
        skill: agente_consultor.Skill,
        mensagem: str,
        saida: agente_consultor.SaidaConsultor,
        portador_id: uuid.UUID,
        inicio: Any,
        fim: Any,
        portao: portao_ia.PortaoIa,
        burla: Sequence[str] = (),
        tokens: int | None = None,
    ) -> Invocacao:
        """Ledger via_ai (§4.1 `invocacao`) + evento `agent.invoked` (§2.3).

        PII (§10.2): `input` não carrega o bloco `solicitante` (§1.3.5) E a `mensagem`
        chega aqui JÁ mascarada (`conversar` sanitiza na fronteira). A garantia é dos
        dois lados — o achado 9 do UAT #5 mostrou que a primeira metade sozinha não
        bastava: o conteúdo do briefing entrava em claro por outra porta.

        C01: tentativa de burlar compliance vira `compliance_bypass_tentado` no output
        do agente (e no payload do evento) — é o que a auditoria precisa enxergar em
        `GET /auditoria`: quem pediu, quando e com quais marcadores.

        (b) §10.4: a RETENÇÃO da política decide se o texto chega a ser gravado. A marca
        `compliance_bypass_tentado` é lista de MARCADORES (não texto do titular), mas
        atravessa a redação como qualquer outro campo não declarado técnico — a política
        que suprime o prompt suprime também o eco dele, que é o comportamento correto:
        o que a auditoria precisa saber (houve tentativa) está no EVENTO, não só aqui."""
        evidencias = [e for inf in saida.inferencias for e in inf.evidencias]
        marca_burla: dict[str, Any] = {"compliance_bypass_tentado": list(burla)} if burla else {}
        invocacao = Invocacao(
            id=uuid.uuid4(),
            tenant_id=pedido.tenant_id,
            os_id=pedido.os_id,
            agente_id=agente_uuid(skill.nome),
            skill_versao=skill.versao,
            usuario_portador=portador_id,
            input=portao.reter_input({"pedido_id": str(pedido.id), "mensagem": mensagem}),
            output=portao.reter_output(
                {
                    "resposta": saida.resposta,
                    "inferencias": [
                        {"campo": i.campo, "valor": i.valor, "evidencias": list(i.evidencias)}
                        for i in saida.inferencias
                    ],
                    **marca_burla,
                }
            ),
            # (b) §10.4: a COLUNA `evidencias` (§4.1) passa pelo portão como o resto. Ela
            # é TEXTO LIVRE do modelo (`agents/consultor.py` monta com `str(e).strip()`),
            # não ref versionada: sem isto a auditoria lia `[SUPRIMIDO...]` no `output` e
            # o trecho da conversa intacto aqui do lado.
            evidencias=portao.reter_evidencias(evidencias),
            tokens=tokens,  # I04: usage do provedor (somado no reforço §7.3) — §10.8
            latencia_ms=int((fim - inicio).total_seconds() * 1000),
            created_at=fim,
        )
        self._repo.adicionar_invocacao(invocacao)
        self._repo.adicionar_evento(
            EventoDominio(
                tenant_id=pedido.tenant_id,
                os_id=pedido.os_id,
                type="agent.invoked",
                payload={
                    "invocacao_id": str(invocacao.id),
                    "agente": skill.nome,
                    "pedido_id": str(pedido.id),
                    "campos_inferidos": [i.campo for i in saida.inferencias],
                    **marca_burla,
                },
                actor=f"agente:{skill.nome}",
                via_ai=True,
                created_at=fim,
            )
        )
        return invocacao

    def _nome_padrao(self, pedido: Pedido) -> str:
        objetivo = regras_completude.valor_do_campo(pedido.conteudo, "objetivo")
        if isinstance(objetivo, str) and objetivo.strip():
            return objetivo.strip()[:80]
        return f"Pedido {pedido.id}"

    def _evento(
        self, tenant_id: str, os_id: uuid.UUID, tipo: str, payload: dict[str, Any], actor: str
    ) -> None:
        self._repo.adicionar_evento(
            EventoDominio(
                tenant_id=tenant_id,
                os_id=os_id,
                type=tipo,
                payload=payload,
                actor=actor,
                via_ai=False,
                created_at=self._relogio.agora(),
            )
        )
