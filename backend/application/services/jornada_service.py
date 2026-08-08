"""Casos de uso do M7 · Twin Canvas T7 (SDD §8-M7) — via ports (§2.1).

- `gerar` (POST /os/{id}/jornada/gerar): agente flow (120b — roster §7.2) propõe o JGC;
  guarda-corpos determinísticos (§1.3.5): meta.osCodigo/tenant SEMPRE reescritos com os
  valores da OS; `jgc_validate` (§5.3) reprova ANTES de persistir; taxímetro (A2)
  recalculado por código. Ledger `invocacao` via_ai + evento + trace (§10.8).
- `atualizar_grafo` (PUT /jornadas/{id}/grafo): valida §5.3 e RECALCULA o taxímetro
  (§8-M7); ZERO LLM — caminho crítico nunca depende de LLM (§10.6). Editar invalida
  simulação/previsto da versão (estado → rascunho; a régua congelada vive no snapshot).
- `criar_manual` (POST /os/{id}/jornada — emenda §8-M7 2026-08-05): "começar do zero"
  do editor T7 SEM LLM (§10.6): nova versão `rascunho` a partir de grafo informado
  (validado §5.3) ou do esqueleto mínimo entry→goal→exit; taxímetro recalculado (A2).
- `ajustar` (POST /jornadas/{id}/ajustar): texto livre → DIFF proposto — NUNCA aplica
  direto (§1.1.3: prévia com Aplicar/Rejeitar; aplicar = PUT do grafo proposto).
- `sfmc_preview` (GET /jornadas/{id}/no/{noId}/sfmc-preview): JSON determinístico que o
  compilador (M9 — §5.4) gerará, com externalKey idempotente.
- Versionamento/exportação (emenda §8-M7 2026-08-05 — 100% determinístico, ZERO LLM):
  `listar_versoes` (GET /os/{id}/jornadas — resumo ordenado por versao),
  `versao_especifica` (GET /jornadas/{id}), `restaurar` (POST /jornadas/{id}/restaurar
  — clona como NOVA versão rascunho: versões NUNCA são editadas retroativamente),
  `diff_versoes` (GET /jornadas/{a}/diff/{b} — domain/jornada/diff.py) e `exportar`
  (GET /jornadas/{id}/export?formato=json|xml — domain/jornada/exportacao.py:
  JSON = import nativo do JB; XML = auditoria corporativa com manifest + XSD).
Eventos (§2.3): agent.invoked · jornada.versao_criada · jornada.grafo_atualizado.
"""

import copy
import uuid
from datetime import datetime
from typing import Any

from agents import flow
from application.ports.clock import ClockPort
from application.ports.llm import LLMPort, soma_tokens
from application.ports.observabilidade import TracerPort
from application.ports.publicacoes import PublicacoesPort, politica_vigente
from application.ports.publicacoes_ia import PublicacoesIaPort
from application.ports.repositorio_jornada import RepositorioJornada
from application.ports.repositorio_os import RepositorioOs
from application.services import portao_ia
from domain.agentes.modelos import Invocacao, agente_uuid
from domain.campanha.erros import EstadoInvalido, NaoEncontrado
from domain.campanha.modelos import OS, EventoDominio
from domain.custo.tarifas import TARIFAS_VIGENTES
from domain.experimento.modelos import experimento_travado
from domain.intake.janela import janela_oferta_dias
from domain.jornada import exportacao, taximetro
from domain.jornada.canonico import hash_jgc, normalizar_grafo
from domain.jornada.diff import diff_grafos
from domain.jornada.erros import GrafoInvalido, SaidaDoFlowInvalida
from domain.jornada.modelos import ESTADOS_EDITAVEIS, JornadaVersao
from domain.jornada.sfmc_preview import preview_do_no
from domain.jornada.validacao import normalizar_arestas, validar_grafo


class ServicoJornada:
    def __init__(
        self,
        repositorio: RepositorioJornada,
        repositorio_os: RepositorioOs,
        relogio: ClockPort,
        llm: LLMPort,
        tracer: TracerPort,
        publicacoes: PublicacoesPort,
        publicacoes_ia: PublicacoesIaPort,
    ) -> None:
        self._repo = repositorio
        self._repo_os = repositorio_os
        self._relogio = relogio
        self._llm = llm
        self._tracer = tracer
        self._publicacoes = publicacoes  # política VIGENTE do banco (achado 8 UAT #5)
        self._publicacoes_ia = publicacoes_ia  # política de IA PUBLICADA (§10.2)

    def _politica(self, os_: OS) -> dict[str, Any]:
        """`conteudo` da política publicada do tenant da OS (§4.1 `policy_versao`).

        Era a constante compilada do domínio: publicar quiet hours/frequency cap novos
        em T16 não mudava nem o prompt do flow nem o veredito do validador §5.3.
        """
        return politica_vigente(self._publicacoes, os_.tenant_id)

    # --------------------------------------------------- POST /os/{id}/jornada/gerar
    def gerar(
        self, tenant_id: str, os_id: uuid.UUID, *, instrucoes: str, portador_id: uuid.UUID
    ) -> tuple[JornadaVersao, flow.SaidaFlow, Invocacao, dict[str, Any]]:
        """Flow → JGC (§8-M7) como NOVA versão do twin; validado (§5.3) e taxado (A2)
        antes de persistir — o LLM propõe, o código dá o veredito (§1.3.5).

        §10.2 (C02): instruções livres saneadas na fronteira — prompt e ledger só
        veem o texto sanitizado. `sanear` mantém o piso do C02 e passa a BLOQUEAR
        quando a política do tenant marcar a categoria detectada."""
        portao = portao_ia.de(  # política PUBLICADA + gasto do teto (J02)
            self._publicacoes_ia,
            tenant_id,
            gasto_tokens=portao_ia.gasto_do_dia(self._repo, self._relogio, tenant_id),
        )
        instrucoes = portao.sanear(instrucoes)
        os_ = self._exigir_os(tenant_id, os_id)
        skill = flow.carregar()
        politica = self._politica(os_)
        mensagens = flow.montar_mensagens(
            skill, os_.briefing or {}, instrucoes, quiet_hours=politica.get("quiet_hours")
        )
        inicio = self._relogio.agora()
        # (f) §7.2: perfil do roster CONFERIDO contra a política antes da chamada.
        portao.autorizar_modelo(skill.nome, skill.modelo_perfil)
        texto, tokens_uso = self._llm.chat(mensagens, perfil=skill.modelo_perfil)  # 503 se fora
        saida = flow.interpretar_saida(texto)
        # §7.3: gerar → validar → retry≤max_retries com o veredito DETERMINÍSTICO do
        # validador como feedback. O LLM propõe; o código continua dando o veredito.
        grafo: dict[str, Any] | None = None
        erro_validacao: GrafoInvalido | None = None
        max_retries = int(skill.meta.get("max_retries", 2))  # front-matter §7.1
        for tentativa in range(1 + max_retries):
            if tentativa:  # reprompt com os erros exatos do jgc_validate (§5.3)
                mensagens = [
                    *mensagens,
                    {"role": "assistant", "content": texto},
                    {
                        "role": "user",
                        "content": (
                            "O validador determinístico (§5.3) REPROVOU o grafo: "
                            f"{erro_validacao} Corrija TODOS os pontos e devolva o JSON "
                            "completo no MESMO formato — todo nó com objeto `data` "
                            "obrigatório conforme o §5.2."
                        ),
                    },
                ]
                portao.autorizar_modelo(skill.nome, skill.modelo_perfil)  # (f) idem no retry
                texto, tokens_retry = self._llm.chat(mensagens, perfil=skill.modelo_perfil)
                # I04: uma linha de ledger cobre TODAS as chamadas do retry §7.3 — soma,
                # para a métrica de custo não subrepresentar.
                tokens_uso = soma_tokens(tokens_uso, tokens_retry)
                saida = flow.interpretar_saida(texto)
            if saida.grafo is None:  # guarda-corpo §1.3.5: nada é inventado
                raise SaidaDoFlowInvalida(
                    "Flow não devolveu JGC utilizável (JSON malformado ou sem `grafo` — §7.2). "
                    + (f"Resposta do agente: {saida.resposta}" if saida.resposta else "")
                )
            candidato = self._normalizar_meta(saida.grafo, os_)
            try:
                self._validar(candidato, os_, politica)
            except GrafoInvalido as erro:
                erro_validacao = erro
                continue
            grafo = candidato
            break
        if grafo is None:  # esgotou o retry §7.3 — o veredito do código prevalece
            assert erro_validacao is not None
            raise erro_validacao
        fim = self._relogio.agora()
        custo, memoria, avisos = self._taximetro(grafo, os_.id)
        jornada = JornadaVersao(
            id=uuid.uuid4(),
            os_id=os_.id,
            versao=self._repo.proxima_versao(os_.id),
            grafo=grafo,
            hash=hash_jgc(grafo),
            premissas=list(saida.premissas),
            custo_projetado=float(custo),
            created_at=fim,
        )
        self._repo.adicionar_jornada(jornada)
        invocacao = self._registrar_invocacao(
            os_,
            skill,
            input={"instrucoes": instrucoes},
            output={"jornada_id": str(jornada.id), "resumo": saida.resumo},
            portador_id=portador_id,
            inicio=inicio,
            fim=fim,
            span="generate",
            portao=portao,
            tokens=tokens_uso,
        )
        self._evento(
            os_,
            "jornada.versao_criada",
            {
                "jornada_id": str(jornada.id),
                "versao": jornada.versao,
                "hash": jornada.hash,
                "custo_projetado": jornada.custo_projetado,
            },
            actor="agente:flow",
            via_ai=True,
        )
        return jornada, saida, invocacao, {"memoria": memoria, "avisos": avisos}

    # ----------------------------------------------------------- POST /os/{id}/jornada
    def criar_manual(
        self, tenant_id: str, os_id: uuid.UUID, *, grafo: dict[str, Any] | None, actor: str
    ) -> tuple[JornadaVersao, dict[str, Any]]:
        """ "Começar do zero" no editor T7 (emenda §8-M7): NOVA versão `rascunho` SEM
        LLM (§10.6) — usa o grafo informado ou o esqueleto mínimo entry→goal→exit
        (§5.2); `jgc_validate` (§5.3) reprova antes de persistir; taxímetro A2."""
        os_ = self._exigir_os(tenant_id, os_id)
        # D01 (UAT #4/#5): numa OS com experimento pré-registrado o §5.3 exige holdout no
        # grafo — e o esqueleto sem ele era rejeitado, deixando "começar do zero"
        # IMPOSSÍVEL justamente nas OS que já passaram pelo portão de experimento (a OS
        # demo entre elas). O esqueleto passa a nascer com o braço de controle, no mesmo
        # pct que o experimento registrou.
        experimento = self._repo.experimento_da_os(os_.id)
        holdout_pct = (
            float(getattr(experimento, "holdout_pct", 0) or 0)
            if experimento_travado(experimento)
            else 0.0
        )
        candidato = grafo if grafo is not None else self._grafo_minimo(os_, holdout_pct)
        candidato = self._normalizar_meta(candidato, os_)
        self._validar(candidato, os_, self._politica(os_))  # A1/A3 → 422
        custo, memoria, avisos = self._taximetro(candidato, os_.id)
        jornada = JornadaVersao(
            id=uuid.uuid4(),
            os_id=os_.id,
            versao=self._repo.proxima_versao(os_.id),
            grafo=candidato,
            hash=hash_jgc(candidato),
            premissas=[],
            custo_projetado=float(custo),
            created_at=self._relogio.agora(),
        )
        self._repo.adicionar_jornada(jornada)
        self._evento(
            os_,
            "jornada.versao_criada",
            {
                "jornada_id": str(jornada.id),
                "versao": jornada.versao,
                "hash": jornada.hash,
                "custo_projetado": jornada.custo_projetado,
                "origem": "manual",
            },
            actor=actor,
        )
        return jornada, {"memoria": memoria, "avisos": avisos}

    @staticmethod
    def _grafo_minimo(os_: OS, holdout_pct: float = 0.0) -> dict[str, Any]:
        """Esqueleto §5.2/§5.3 do "começar do zero": entrySource → goal → exit —
        o menor grafo que passa no `jgc_validate` (tem goal, nada órfão).

        `holdout_pct > 0` (D01): a OS tem experimento pré-registrado, e o §5.3 exige
        braço de controle no grafo. O esqueleto então nasce
        `entrySource → randomSplit(holdout | tratamento) → goal → exit`, com o controle
        indo direto ao `exit` — sem isso o "começar do zero" respondia 422 e a OS ficava
        sem nenhum caminho para criar a primeira versão do twin.
        """
        entrada = {
            "id": "entrada",
            "type": "entrySource",
            "data": {
                "deRef": f"DE_{os_.codigo}_entrada",
                "modo": "fire_once",
                "agenda": None,
                "reentrada": "nao",
            },
        }
        meta = {
            "id": "meta",
            "type": "goal",
            "data": {"metrica": "conversao", "deRef": f"DE_{os_.codigo}_conversoes"},
        }
        saida = {"id": "saida", "type": "exit", "data": {"motivo": "fim_da_jornada"}}

        if holdout_pct <= 0:
            return {
                "jgcVersion": "1.0",
                "meta": {},  # osCodigo/tenant/reentrada reescritos por _normalizar_meta
                "nodes": [entrada, meta, saida],
                "edges": [
                    {"id": "e1", "from": "entrada", "to": "meta", "cond": None},
                    {"id": "e2", "from": "meta", "to": "saida", "cond": None},
                ],
            }

        controle = round(float(holdout_pct), 4)
        divisao = {
            "id": "controle",
            "type": "randomSplit",
            "data": {
                "braços": [
                    {"id": "holdout", "pct": controle, "holdout": True},
                    {"id": "tratamento", "pct": round(100.0 - controle, 4)},
                ]
            },
        }
        return {
            "jgcVersion": "1.0",
            "meta": {},
            "nodes": [entrada, divisao, meta, saida],
            "edges": [
                {"id": "e1", "from": "entrada", "to": "controle", "cond": None},
                {"id": "e2", "from": "controle", "to": "saida", "cond": "holdout"},
                {"id": "e3", "from": "controle", "to": "meta", "cond": "tratamento"},
                {"id": "e4", "from": "meta", "to": "saida", "cond": None},
            ],
        }

    # ------------------------------------------------------ PUT /jornadas/{id}/grafo
    def atualizar_grafo(
        self, tenant_id: str, jornada_id: uuid.UUID, *, grafo: dict[str, Any], actor: str
    ) -> tuple[JornadaVersao, dict[str, Any]]:
        """Valida §5.3, recalcula o taxímetro (§8-M7) e MINTA uma versão nova — SEM LLM
        (§10.6).

        **D06 (emenda K04, onda 7 — aceite §8-M7-B6).** Até aqui esta função mutava o
        MESMO registro (`jornada.grafo = grafo`, `jornada.hash = ...`) e o adapter fazia
        `on_conflict_do_update`: uma sessão inteira de edição colapsava numa linha só. O
        UAT #4 mediu ~25 PUTs virando UMA versão — o histórico do twin, que é a fonte da
        verdade do §1.1, existia só no papel.

        E havia um buraco pior que a perda de histórico. Entre `criar_snapshot` (que NÃO
        muda o estado) e a decisão, a jornada segue `simulado` — portanto editável. O
        snapshot guarda o JGC por REFERÊNCIA e o compilador materializa o grafo ATUAL
        carimbado com o hash APROVADO, sem conferir igualdade: um PUT nessa janela
        publicava no SFMC um grafo que ninguém aprovou. Mintar versão fecha essa janela
        **por construção** — a versão aprovada deixa de ser alcançável pela edição.

        Duas garantias que andam juntas:

        · **Save idempotente não versiona.** Hash igual ⇒ nada acontece: nem registro
          novo, nem evento, nem invalidação de simulação. É o que cumpre a promessa de
          que reordenar nós no canvas não mexe no SFMC (o hash já é insensível à ordem,
          emenda I03) — sem esta guarda, o D06 encheria o histórico de versões idênticas
          e zeraria o Ensaio a cada auto-save.
        · **Nada é mutado.** Nenhuma linha desta função atribui a `jornada.<atributo>`:
          a versão de origem tem de sair da chamada byte a byte como entrou.
        """
        jornada, os_ = self._jornada_da_os(tenant_id, jornada_id)
        if jornada.estado not in ESTADOS_EDITAVEIS:
            raise EstadoInvalido(
                f"Jornada em estado {jornada.estado!r} não é editável — novo ciclo exige "
                "nova versão (§1.2 non-goals: sem edição ao vivo)."
            )
        grafo = self._normalizar_meta(grafo, os_)
        self._validar(grafo, os_, self._politica(os_))  # A1/A3 → 422
        custo, memoria, avisos = self._taximetro(grafo, os_.id)

        novo_hash = hash_jgc(grafo)
        if novo_hash == jornada.hash:
            # Grafo idêntico (inclusive só reordenado): o save é no-op observável.
            return jornada, {"memoria": memoria, "avisos": avisos}

        nova = JornadaVersao(
            id=uuid.uuid4(),
            os_id=os_.id,
            versao=self._repo.proxima_versao(os_.id),
            grafo=grafo,
            hash=novo_hash,
            premissas=list(jornada.premissas),
            custo_projetado=float(custo),
            created_at=self._relogio.agora(),
        )
        # `simulacao`/`previsto` NÃO acompanham: nascem `None` no dataclass. O Ensaio
        # pertence ao grafo que foi simulado, e o Previsto que vale é o do snapshot.
        self._repo.adicionar_jornada(nova)
        self._evento(
            os_,
            "jornada.versao_criada",
            {
                "jornada_id": str(nova.id),
                "versao": nova.versao,
                "hash": nova.hash,
                "custo_projetado": nova.custo_projetado,
                "derivada_de": {"jornada_id": str(jornada.id), "versao": jornada.versao},
            },
            actor=actor,
        )
        # O evento antigo CONTINUA saindo: consumidores (e aceites) filtram por ele, e
        # trocar o tipo calado transformaria um fecho em quebra de contrato de outros.
        self._evento(
            os_,
            "jornada.grafo_atualizado",
            {
                "jornada_id": str(nova.id),
                "versao": nova.versao,
                "hash": nova.hash,
                "custo_projetado": nova.custo_projetado,
            },
            actor=actor,
        )
        return nova, {"memoria": memoria, "avisos": avisos}

    # -------------------------------------------------- POST /jornadas/{id}/ajustar
    def ajustar(
        self, tenant_id: str, jornada_id: uuid.UUID, *, instrucoes: str, portador_id: uuid.UUID
    ) -> tuple[dict[str, Any], Invocacao]:
        """Texto livre → diff proposto (§8-M7); quem decide se a IA pode APLICAR
        sozinha é a POLÍTICA, não mais um literal no código.

        Até esta onda, `aplicado: False` era convenção: alguém escreveu o literal na
        mão, e o próximo commit podia trocá-lo por `True` sem que tela, log ou DPO
        ficassem sabendo (LGPD Art. 20). Agora a allowlist versionada
        `decisao_automatizada.pode_aplicar_sozinho` decide, e o default dela é VAZIA —
        publicar a v1 preserva exatamente o comportamento de hoje.

        §10.2 (C02): instruções livres saneadas na fronteira (prompt + ledger)."""
        portao = portao_ia.de(  # política PUBLICADA + gasto do teto (J02)
            self._publicacoes_ia,
            tenant_id,
            gasto_tokens=portao_ia.gasto_do_dia(self._repo, self._relogio, tenant_id),
        )
        instrucoes = portao.sanear(instrucoes)
        jornada, os_ = self._jornada_da_os(tenant_id, jornada_id)
        skill = flow.carregar()
        politica = self._politica(os_)
        mensagens = flow.montar_mensagens(
            skill,
            os_.briefing or {},
            instrucoes,
            quiet_hours=politica.get("quiet_hours"),
            grafo_atual=jornada.grafo,
        )
        inicio = self._relogio.agora()
        # (f) §7.2: perfil do roster CONFERIDO contra a política antes da chamada.
        portao.autorizar_modelo(skill.nome, skill.modelo_perfil)
        texto, tokens_uso = self._llm.chat(mensagens, perfil=skill.modelo_perfil)
        fim = self._relogio.agora()
        saida = flow.interpretar_saida(texto)
        if saida.grafo is None:
            raise SaidaDoFlowInvalida(
                "Flow não devolveu proposta de JGC utilizável (§7.2). "
                + (f"Resposta do agente: {saida.resposta}" if saida.resposta else "")
            )
        proposto = self._normalizar_meta(saida.grafo, os_)
        erros = validar_grafo(
            proposto,
            experimento_travado=experimento_travado(self._repo.experimento_da_os(os_.id)),
            politica=politica,
            janela_oferta_dias=janela_oferta_dias(os_.briefing),  # J04 — mesma régua
        )
        custo_proposto, _, avisos = self._taximetro(proposto, os_.id)
        invocacao = self._registrar_invocacao(
            os_,
            skill,
            input={"jornada_id": str(jornada.id), "instrucoes": instrucoes},
            output={"resumo": saida.resumo, "valido": not erros},
            portador_id=portador_id,
            inicio=inicio,
            fim=fim,
            span="ajustar",
            portao=portao,
            tokens=tokens_uso,
        )
        # (c) LGPD Art. 20 — a POLÍTICA decide o modo, não um literal.
        #
        # `aplicar` só acontece com proposta VÁLIDA (`not erros`): automatizar a decisão
        # nunca dispensa o veredito determinístico do §5.3, como `decisao.py` registra.
        # Proposta inválida com a ação autorizada continua sendo proposta — o caminho
        # automático não é uma porta dos fundos para gravar grafo reprovado.
        #
        # A aplicação reusa `atualizar_grafo`, que é o MESMO caminho do PUT humano
        # (§1.1.3): valida §5.3 de novo, recalcula o taxímetro e emite
        # `jornada.grafo_atualizado`. Um atalho que gravasse direto teria menos gates
        # que o clique — o oposto do que o Art. 20 pede.
        aplicado = False
        if not erros and portao.pode_aplicar_sozinho(portao_ia.ACAO_JORNADA_AJUSTAR):
            # `actor` diz a verdade: NINGUÉM clicou. A trilha registra a automação e o
            # portador em cujo nome ela rodou — sem isso, a linha do outbox seria
            # indistinguível de um humano tendo aplicado.
            self.atualizar_grafo(
                tenant_id,
                jornada_id,
                grafo=proposto,
                actor=f"ia:{skill.nome}:politica(portador={portador_id})",
            )
            aplicado = True
        proposta = {
            "jornada_id": str(jornada.id),
            "aplicado": aplicado,  # default: prévia — aplicar é PUT humano (§1.1.3)
            "grafo_proposto": proposto,
            "diff": self._diff_grafos(jornada.grafo, proposto),
            "premissas": list(saida.premissas),
            "resumo": saida.resumo,
            "valido": not erros,
            "erros": erros,
            "custo_projetado_atual": jornada.custo_projetado,
            "custo_projetado_proposto": float(custo_proposto),
            "avisos": avisos,
        }
        return proposta, invocacao

    # ------------------------------------------------------- GET /os/{id}/jornada
    def ultima_versao(self, tenant_id: str, os_id: uuid.UUID) -> JornadaVersao:
        """Última versão do twin da OS (§8-M7, emenda A14) — leitura determinística,
        ZERO LLM (§10.6); OS sem versão → NaoEncontrado (404)."""
        os_ = self._exigir_os(tenant_id, os_id)
        versoes = self._repo.listar_jornadas(os_.id)
        if not versoes:
            raise NaoEncontrado(
                f"OS {os_id} sem versão de jornada — gere o JGC no T7 (§8-M7) primeiro."
            )
        return versoes[-1]  # listar_jornadas devolve em ordem de `versao` (§4.1)

    # ----------------------------------- GET /jornadas/{id}/no/{noId}/sfmc-preview
    def sfmc_preview(self, tenant_id: str, jornada_id: uuid.UUID, no_id: str) -> dict[str, Any]:
        """JSON que o compilador (M9) gerará para o nó (§5.4) — determinístico."""
        jornada, _ = self._jornada_da_os(tenant_id, jornada_id)
        return preview_do_no(jornada.grafo, jornada.hash, no_id)  # nó ausente → 404

    # ------------------------------------------------------- GET /os/{id}/jornadas
    def listar_versoes(self, tenant_id: str, os_id: uuid.UUID) -> list[JornadaVersao]:
        """Todas as versões do twin da OS em ordem de `versao` (§4.1) — o T7 mostra a
        linha do tempo; OS sem versão devolve lista vazia (a OS existe). ZERO LLM."""
        os_ = self._exigir_os(tenant_id, os_id)
        return self._repo.listar_jornadas(os_.id)

    # --------------------------------------------------------- GET /jornadas/{id}
    def versao_especifica(self, tenant_id: str, jornada_id: uuid.UUID) -> JornadaVersao:
        """Versão específica COMPLETA (grafo incluso) — leitura determinística."""
        jornada, _ = self._jornada_da_os(tenant_id, jornada_id)
        return jornada

    # ------------------------------------------------ POST /jornadas/{id}/restaurar
    def restaurar(
        self, tenant_id: str, jornada_id: uuid.UUID, *, actor: str
    ) -> tuple[JornadaVersao, dict[str, Any]]:
        """Clona a versão como NOVA versão `rascunho` — versões NUNCA são editadas
        retroativamente (§1.2 non-goals). Grafo (deepcopy) e hash idênticos aos da
        origem; taxímetro RECALCULADO (tarifa/volume vigentes — A2); simulação e
        previsto NÃO acompanham (Ensaio Geral pertence ao snapshot da origem §6)."""
        origem, os_ = self._jornada_da_os(tenant_id, jornada_id)
        grafo = copy.deepcopy(origem.grafo)
        custo, memoria, avisos = self._taximetro(grafo, os_.id)
        nova = JornadaVersao(
            id=uuid.uuid4(),
            os_id=os_.id,
            versao=self._repo.proxima_versao(os_.id),
            grafo=grafo,
            hash=origem.hash,  # mesmo grafo ⇒ mesmo hash canônico (canonico.py)
            premissas=list(origem.premissas),
            custo_projetado=float(custo),
            created_at=self._relogio.agora(),
        )
        self._repo.adicionar_jornada(nova)
        self._evento(
            os_,
            "jornada.versao_criada",
            {
                "jornada_id": str(nova.id),
                "versao": nova.versao,
                "hash": nova.hash,
                "custo_projetado": nova.custo_projetado,
                "restaurada_de": {"jornada_id": str(origem.id), "versao": origem.versao},
            },
            actor=actor,
        )
        return nova, {"memoria": memoria, "avisos": avisos}

    # ---------------------------------------------- GET /jornadas/{a}/diff/{b}
    def diff_versoes(
        self, tenant_id: str, jornada_a: uuid.UUID, jornada_b: uuid.UUID
    ) -> dict[str, Any]:
        """Diff estrutural entre duas versões da MESMA OS (domain/jornada/diff.py:
        nós/arestas adicionados·removidos·alterados + meta) — versões de OSs
        diferentes não são comparáveis (409)."""
        de, os_de = self._jornada_da_os(tenant_id, jornada_a)
        para, os_para = self._jornada_da_os(tenant_id, jornada_b)
        if os_de.id != os_para.id:
            raise EstadoInvalido(
                f"Diff exige versões da MESMA OS — {jornada_a} pertence a {os_de.codigo} "
                f"e {jornada_b} a {os_para.codigo} (§8-M7)."
            )
        return {
            "de": {"id": str(de.id), "versao": de.versao, "hash": de.hash},
            "para": {"id": str(para.id), "versao": para.versao, "hash": para.hash},
            **diff_grafos(de.grafo, para.grafo),
        }

    # ------------------------------------- GET /jornadas/{id}/export?formato=json|xml
    def exportar(
        self, tenant_id: str, jornada_id: uuid.UUID, *, formato: str
    ) -> tuple[bytes, str, str]:
        """Exportação determinística (ZERO LLM §10.6) → (bytes, media type, filename).

        `json` = spec de interaction do JB (import nativo — REST
        /interaction/v1/interactions, via compilador M9); `xml` = MESMA spec canônica
        com manifest (geradoEm via ClockPort) validável pelo journey_export.xsd —
        integração/auditoria corporativa (o JB não importa XML). Ver exportacao.py.
        """
        jornada, os_ = self._jornada_da_os(tenant_id, jornada_id)
        base = f"jornada-{os_.codigo}-v{jornada.versao}"
        if formato == "json":
            return (
                exportacao.export_json(jornada.grafo, jornada.hash),
                ("application/json"),
                f"{base}.json",
            )
        conteudo = exportacao.export_xml(
            jornada.grafo, jornada.hash, versao=jornada.versao, gerado_em=self._relogio.agora()
        )
        return conteudo, "application/xml", f"{base}.xml"

    # ----------------------------------------------------------------- privados
    @staticmethod
    def _normalizar_meta(grafo: dict[str, Any], os_: OS) -> dict[str, Any]:
        """Escopo NUNCA vem do LLM/cliente (§1.3.5): meta.osCodigo/tenant = valores da OS.
        Arestas com aliases `source`/`target` (A13 — UAT com o 120b real) são
        normalizadas para `from`/`to` ANTES do `jgc_validate` (gerar/ajustar/PUT).
        Emenda I03: nodes/edges ordenados por id na MESMA borda — o grafo persiste
        canônico, então hash, compilador e drift enxergam sempre a mesma ordem."""
        grafo = dict(normalizar_arestas(grafo))
        grafo.setdefault("jgcVersion", "1.0")
        meta = dict(grafo.get("meta") or {})
        meta["osCodigo"] = os_.codigo
        meta["tenant"] = os_.tenant_id
        meta.setdefault("reentrada", "nao")
        grafo["meta"] = meta
        return normalizar_grafo(grafo)

    def _validar(self, grafo: dict[str, Any], os_: OS, politica: dict[str, Any]) -> None:
        erros = validar_grafo(
            grafo,
            experimento_travado=experimento_travado(self._repo.experimento_da_os(os_.id)),
            politica=politica,
            # J04: a janela ESTRUTURADA do briefing (janela_inicio/janela_fim) liga o
            # wait_alem_da_janela (§5.3) — ausente/não-parseável → None → inerte.
            janela_oferta_dias=janela_oferta_dias(os_.briefing),
        )
        if erros:
            raise GrafoInvalido(erros)

    def _taximetro(
        self, grafo: dict[str, Any], os_id: uuid.UUID
    ) -> tuple[Any, list[dict[str, Any]], list[str]]:
        """A2: custo = Σ(volume esperado × tarifa vigente); volume = líquido do último
        segmento recontado (M5); sem segmento → volume 0 + aviso (nunca inventa)."""
        segmentos = [
            s for s in self._repo.listar_segmentos(os_id) if s.contagem_liquida is not None
        ]
        volume = int(segmentos[-1].contagem_liquida or 0) if segmentos else 0
        custo, memoria, avisos = taximetro.calcular(
            grafo, volume_entrada=volume, tarifas=TARIFAS_VIGENTES
        )
        if not segmentos:
            avisos.append("OS sem segmento recontado (M5) — taxímetro calculado com volume 0.")
        return custo, memoria, avisos

    @staticmethod
    def _diff_grafos(atual: dict[str, Any], proposto: dict[str, Any]) -> dict[str, Any]:
        """Diff estrutural por id — código puro compartilhado (domain/jornada/diff.py;
        o M11 reusa o MESMO diff nas propostas do optimize §8-M11)."""
        return diff_grafos(atual, proposto)

    def _exigir_os(self, tenant_id: str, os_id: uuid.UUID) -> OS:
        os_ = self._repo_os.obter_os(tenant_id, os_id)
        if os_ is None:
            raise NaoEncontrado(f"OS {os_id} não encontrada no tenant {tenant_id!r}.")
        return os_

    def _jornada_da_os(self, tenant_id: str, jornada_id: uuid.UUID) -> tuple[JornadaVersao, OS]:
        jornada = self._repo.obter_jornada(jornada_id)
        os_ = self._repo_os.obter_os(tenant_id, jornada.os_id) if jornada is not None else None
        if jornada is None or os_ is None:  # escopo de tenant via OS (§4.1)
            raise NaoEncontrado(f"Jornada {jornada_id} não encontrada no tenant {tenant_id!r}.")
        return jornada, os_

    def _registrar_invocacao(
        self,
        os_: OS,
        skill: Any,
        *,
        input: dict[str, Any],
        output: dict[str, Any],
        portador_id: uuid.UUID,
        inicio: datetime,
        fim: datetime,
        span: str,
        portao: portao_ia.PortaoIa,
        tokens: int | None = None,
    ) -> Invocacao:
        """Ledger via_ai (§4.1 `invocacao`) + evento `agent.invoked` + trace (§10.8).

        Ponto ÚNICO de gravação do M7: a retenção da política (§10.4) é aplicada aqui,
        então `gerar` e `ajustar` não podem divergir por esquecimento de um dos dois."""
        invocacao = Invocacao(
            id=uuid.uuid4(),
            tenant_id=os_.tenant_id,
            os_id=os_.id,
            agente_id=agente_uuid(skill.nome),
            skill_versao=skill.versao,
            usuario_portador=portador_id,
            input=portao.reter_input({"os_id": str(os_.id), **input}),
            output=portao.reter_output(output),
            evidencias=[],
            tokens=tokens,  # I04: usage do provedor (somado no retry §7.3) — §10.8
            latencia_ms=int((fim - inicio).total_seconds() * 1000),
            created_at=fim,
        )
        self._repo.adicionar_invocacao(invocacao)
        self._repo.adicionar_evento(
            EventoDominio(
                tenant_id=os_.tenant_id,
                os_id=os_.id,
                type="agent.invoked",
                payload={
                    "invocacao_id": str(invocacao.id),
                    "agente": skill.nome,
                    "os_codigo": os_.codigo,
                },
                actor=f"agente:{skill.nome}",
                via_ai=True,
                created_at=fim,
            )
        )
        self._tracer.trace(  # §10.8: fire-and-forget, trace_id = invocacao.id
            trace_id=str(invocacao.id),
            nome=f"{skill.nome}.{span}",
            metadados={
                "tenant": os_.tenant_id,
                "os_id": str(os_.id),
                "agente": skill.nome,
                "skill_versao": skill.versao,
                "modelo_perfil": skill.modelo_perfil,
            },
            spans=[{"nome": span, "latencia_ms": invocacao.latencia_ms}],
        )
        return invocacao

    def _evento(
        self, os_: OS, tipo: str, payload: dict[str, Any], *, actor: str, via_ai: bool = False
    ) -> None:
        self._repo.adicionar_evento(
            EventoDominio(
                tenant_id=os_.tenant_id,
                os_id=os_.id,
                type=tipo,
                payload=payload,
                actor=actor,
                via_ai=via_ai,
                created_at=self._relogio.agora(),
            )
        )
