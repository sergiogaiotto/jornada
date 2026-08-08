"""Casos de uso do M12 (parte 1) · Ateliê T16 (SDD §8-M12, §7.1) — via ports (§2.1).

- CRUD de agentes/skills: skill nasce `draft` a partir de um SKILL.md canônico (o
  parser §7.1 valida CAMPOS — skill_parser.py); ciclo draft→em_revisao→publicada;
  só `draft` é editável (em revisão o conteúdo é imutável — o harness julga um texto
  estável).
- `rodar_harness` (POST /skills/{id}/harness): roda o GOLDEN DATASET do agente
  (`harness_case` §4.1 — 3 casos por agente-chave nas seeds §11.4): executa a skill
  candidata sobre o input de cada caso e o JUDGE (LLM 120b, rubrica fixa §7.1; em
  teste o LLMFake determinístico §1.3.5) dá nota por dimensão; o CÓDIGO consolida
  (média por dimensão, passou = todas ≥ 90 §7.1) e grava `harness_run` com
  `skill_md_hash` (amarra o run ao texto julgado). Traceado com tag `harness` (§10.8).
- `publicar` (POST /skills/{id}/publicar): portão §8-M12-A1 — exige estado
  `em_revisao` E último harness_run VERDE sobre o skill_md ATUAL; senão 409. Publicar
  NUNCA toca `os.frozen` (A2): OS em voo continua com as versões congeladas no GO
  (§8-M4-A2); OS nova congela as novas no próximo GO (PublicacoesAtelie).
- `dry_run`: lado a lado (§8-M12) — MESMA entrada na versão publicada ATUAL e na
  candidata; nada persiste; decisão é humana (§1.1.3).
- `versao_para_os`: resolução da versão efetiva por OS — frozen.agent_versions (§4.1)
  quando a OS está em voo; senão a publicada atual (base da A2).

## Portão de IA Responsável (§10.2) — por que ele chegou tarde aqui

O Ateliê nasceu no M12 e ficou fora da fiação da onda 3: era o ÚNICO serviço com
`LLMPort.chat` sem `portao_ia`. A auditoria mediu os três controles caindo juntos com a
política mais restritiva PUBLICADA — CPF e e-mail em claro no prompt do dry-run, o perfil
vindo do front-matter (que o próprio usuário escreve) sem conferência, e
`harness_run.resultados` guardando saída de modelo sem passar por retenção; zero linhas no
ledger `invocacao`, então o Art. 20 não alcançava este caminho.

O que faz este serviço diferente dos outros sete — e o que a fiação teve de responder:

* **a entrada é ÁRVORE, não string**: `harness_case.input` e a `entrada` do dry-run são
  `dict` que viram `json.dumps` no prompt. Daí `portao.sanear_estrutura`, que vive no
  PORTÃO e não aqui — caminhamento de árvore duplicado por serviço é exatamente como o
  `kv_master` (dicionário aninhado) escapou inteiro da retenção na onda 3.
* **o perfil vem de ENTRADA NÃO CONFIÁVEL**: nos outros serviços a skill é arquivo de
  disco revisado em PR; aqui o `modelo_perfil` está no front-matter do SKILL.md que o
  analista digita na tela do T16. Escolha de modelo por texto de usuário é precisamente
  o que o parâmetro (f) existe para governar.
* **o JUDGE lê o dado do agente julgado**: `judge.PERFIL_JUDGE` é constante de código
  (120b), mas o dado que ele vê é do agente sob teste. A conferência do judge é feita
  contra `modelos_permitidos[agente.nome]` pelo mesmo motivo — a pergunta que a política
  responde é "que modelo pode ver o dado deste tenant", e quem vê é o 120b do judge.
  Restringir um agente a 20b passa a recusar o harness dele, e essa é a resposta certa:
  a alternativa é o dado ir ao 120b logo depois de o DPO o ter proibido.

"""

import uuid
from datetime import datetime
from typing import Any, Protocol, cast

from agents.harness import judge
from application.ports.clock import ClockPort
from application.ports.llm import LLMPort, soma_tokens
from application.ports.observabilidade import TracerPort
from application.ports.publicacoes_ia import PublicacoesIaPort
from application.ports.repositorio_atelie import RepositorioAtelie
from application.services import portao_ia
from domain.agentes.modelos import Invocacao, agente_uuid
from domain.atelie import harness as regras_harness
from domain.atelie.erros import (
    AgenteDuplicado,
    EstadoSkillInvalido,
    HarnessNaoAprovado,
    SemCasosGolden,
    SkillMdInvalido,
    VersaoDuplicada,
)
from domain.atelie.modelos import Agente, HarnessRun, SkillVersao
from domain.atelie.skill_parser import SkillMd, parse_skill_md
from domain.campanha.erros import NaoEncontrado
from domain.campanha.modelos import EventoDominio


class _LedgerInvocacoes(Protocol):
    """`adicionar_invocacao` é do ledger via_ai (§4.1) e não está em `RepositorioAtelie`.

    O repositório é UM objeto que implementa todas as portas (tipagem estrutural §2.1) —
    este Protocol só informa o mypy no cast, no mesmo padrão de
    `otimizacao_service._RepositorioComLaunches`. O lugar DEFINITIVO do método é a porta
    do Ateliê; declará-lo lá vai como EMENDA SUGERIDA porque `ports/repositorio_atelie.py`
    está fora dos arquivos desta frente — e o Art. 20 não podia esperar por uma porta.
    """

    def adicionar_invocacao(self, invocacao: Invocacao) -> None: ...

    # J02: gasto MEDIDO do teto de tokens (NULL conta 0 — régua do I04).
    def somar_tokens(self, tenant_id: str, desde: datetime) -> int: ...


class ServicoAtelie:
    def __init__(
        self,
        repositorio: RepositorioAtelie,
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

    # ------------------------------------------------------------ GET/POST /agentes
    def listar_agentes(self, tenant_id: str) -> list[dict[str, Any]]:
        publicadas = self._repo.versoes_skills_publicadas()
        return [
            {
                **_agente_out(agente),
                "versao_publicada": publicadas.get(agente.nome),
                "skills": [_skill_resumo(s) for s in self._repo.listar_skills(agente.id)],
            }
            for agente in self._repo.listar_agentes(tenant_id)
        ]

    def criar_agente(
        self,
        tenant_id: str,
        *,
        nome: str,
        camada: str,
        etapa_workflow: str | None,
        modelo_perfil: str | None,
        deterministico: bool,
        actor: str,
    ) -> dict[str, Any]:
        if self._repo.obter_agente_por_nome(nome) is not None:
            raise AgenteDuplicado(f"Agente {nome!r} já existe — `agente.nome` é unique (§4.1).")
        agente = Agente(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            nome=nome,
            camada=camada,
            etapa_workflow=etapa_workflow,
            modelo_perfil=modelo_perfil,
            deterministico=deterministico,
        )
        self._repo.adicionar_agente(agente)
        self._evento(tenant_id, "agente.criado", {"agente": nome, "camada": camada}, actor)
        return {**_agente_out(agente), "versao_publicada": None, "skills": []}

    # ------------------------------------------- GET/POST /agentes/{id}/skills, PUT
    def listar_skills(self, tenant_id: str, agente_id: uuid.UUID) -> list[dict[str, Any]]:
        agente = self._agente(tenant_id, agente_id)
        return [_skill_resumo(s) for s in self._repo.listar_skills(agente.id)]

    def criar_skill(
        self, tenant_id: str, agente_id: uuid.UUID, *, skill_md: str, actor: str
    ) -> dict[str, Any]:
        agente = self._agente(tenant_id, agente_id)
        parseada = self._parse_para_agente(agente, skill_md)
        if any(s.versao == parseada.versao for s in self._repo.listar_skills(agente.id)):
            raise VersaoDuplicada(
                f"Versão {parseada.versao} já existe para {agente.nome!r} — "
                "unique(agente_id, versao) (§4.1)."
            )
        skill = SkillVersao(
            id=uuid.uuid4(),
            agente_id=agente.id,
            versao=parseada.versao,
            skill_md=skill_md,
            execution_profile=parseada.execution_profile(),
            bases_rag=list(parseada.bases_rag),
        )
        self._repo.adicionar_skill(skill)
        self._evento(
            tenant_id,
            "skill.criada",
            {"agente": agente.nome, "versao": skill.versao, "skill_id": str(skill.id)},
            actor,
        )
        return _skill_out(skill, [])

    def atualizar_skill(
        self, tenant_id: str, skill_id: uuid.UUID, *, skill_md: str, actor: str
    ) -> dict[str, Any]:
        skill, agente = self._skill_do_tenant(tenant_id, skill_id)
        if skill.estado != "draft":
            raise EstadoSkillInvalido(
                f"Skill {skill.estado} não é editável — só `draft` muda de conteúdo "
                "(em revisão o harness julga um texto estável §8-M12)."
            )
        parseada = self._parse_para_agente(agente, skill_md)
        if any(
            s.versao == parseada.versao and s.id != skill.id
            for s in self._repo.listar_skills(agente.id)
        ):
            raise VersaoDuplicada(
                f"Versão {parseada.versao} já existe para {agente.nome!r} — "
                "unique(agente_id, versao) (§4.1)."
            )
        skill.versao = parseada.versao
        skill.skill_md = skill_md
        skill.execution_profile = parseada.execution_profile()
        skill.bases_rag = list(parseada.bases_rag)
        self._repo.salvar_skill(skill)
        self._evento(
            tenant_id,
            "skill.atualizada",
            {"agente": agente.nome, "versao": skill.versao, "skill_id": str(skill.id)},
            actor,
        )
        return _skill_out(skill, self._repo.listar_harness_runs(skill.id))

    def obter_skill(self, tenant_id: str, skill_id: uuid.UUID) -> dict[str, Any]:
        skill, _ = self._skill_do_tenant(tenant_id, skill_id)
        return _skill_out(skill, self._repo.listar_harness_runs(skill.id))

    # ------------------------------------------------------ POST /skills/{id}/revisao
    def enviar_para_revisao(
        self, tenant_id: str, skill_id: uuid.UUID, *, actor: str
    ) -> dict[str, Any]:
        skill, agente = self._skill_do_tenant(tenant_id, skill_id)
        if skill.estado != "draft":
            raise EstadoSkillInvalido(
                f"Transição inválida: {skill.estado} → em_revisao — o ciclo é "
                "draft→em_revisao→publicada (§8-M12)."
            )
        skill.estado = "em_revisao"
        self._repo.salvar_skill(skill)
        self._evento(
            tenant_id,
            "skill.em_revisao",
            {"agente": agente.nome, "versao": skill.versao, "skill_id": str(skill.id)},
            actor,
        )
        return _skill_out(skill, self._repo.listar_harness_runs(skill.id))

    # ------------------------------------------------------ POST /skills/{id}/harness
    def rodar_harness(
        self, tenant_id: str, skill_id: uuid.UUID, *, actor: str, portador_id: uuid.UUID
    ) -> dict[str, Any]:
        """Roda o golden dataset com judge (docstring do módulo). LLM indisponível →
        `LLMIndisponivel` sobe e a API responde 503 degraded (§10.6 — harness não é
        caminho crítico).

        Sob o portão de IA Responsável (§10.2): corpo da skill, `input`/`esperado` de cada
        caso e a saída que vai ao judge são SANEADOS; os DOIS perfis são conferidos contra
        a política do tenant; a saída gravada em `harness_run.resultados` passa por
        retenção; e o run inteiro vira linha do ledger `invocacao` (Art. 20).
        """
        skill, agente = self._skill_do_tenant(tenant_id, skill_id)
        casos = self._repo.listar_harness_cases(agente.id)
        if not casos:
            raise SemCasosGolden(
                f"Agente {agente.nome!r} sem golden dataset (`harness_case` §4.1) — "
                "harness exige casos (seeds §11.4: 3 por agente-chave)."
            )
        portao = portao_ia.de(  # política PUBLICADA (§10.2) + gasto do teto (J02)
            self._publicacoes_ia,
            tenant_id,
            gasto_tokens=portao_ia.gasto_do_dia(
                cast(_LedgerInvocacoes, self._repo), self._relogio, tenant_id
            ),
        )
        perfil = str(skill.execution_profile.get("modelo_perfil") or "20b")
        # §10.2 (C02): o corpo da skill é texto DIGITADO na tela do T16 e vira o system
        # prompt — sanear uma vez aqui cobre os N casos do golden dataset.
        corpo = portao.sanear(parse_skill_md(skill.skill_md).corpo)
        inicio = self._relogio.agora()
        avaliacoes: list[dict[str, Any]] = []
        tokens_uso: int | None = None  # I04: um run soma execução+judge de TODOS os casos
        for caso in casos:
            # `harness_case.input` é ÁRVORE, não string: quem sanea árvore é o portão
            # (`sanear_estrutura`), senão este serviço teria detector próprio de PII.
            entrada = portao.sanear_estrutura(caso.input)
            esperado = portao.sanear_estrutura(caso.esperado)
            # (f) §7.2: `perfil` veio do FRONT-MATTER — entrada não confiável escolhendo
            # modelo. Conferido DENTRO do laço, imediatamente antes do `chat`, para que a
            # revisão (e o vigia de CI) veja que nenhuma chamada ficou sem par.
            portao.autorizar_modelo(agente.nome, perfil)
            saida, tokens_exec = self._llm.chat(
                judge.montar_mensagens_execucao(corpo, entrada),
                perfil=perfil,  # type: ignore[arg-type]  # validado pelo parser §7.1
            )
            # O judge é 120b por constante de código, mas o dado que ele lê é do agente
            # JULGADO — quem autoriza é `modelos_permitidos[agente]` (docstring do módulo).
            portao.autorizar_modelo(agente.nome, judge.PERFIL_JUDGE)
            veredito, tokens_judge = self._llm.chat(
                judge.montar_mensagens_judge(
                    entrada=entrada,
                    esperado=esperado,
                    # saída de modelo é texto NÃO confiável que vira prompt de outro
                    # modelo: este é o único ponto em que ela pode ser saneada.
                    saida=portao.sanear(saida),
                    dimensoes=caso.dimensoes,
                ),
                perfil=judge.PERFIL_JUDGE,
            )
            tokens_uso = soma_tokens(tokens_uso, tokens_exec, tokens_judge)
            # (b) §10.4: `reter_resposta: false` redige a saída do modelo na GRAVAÇÃO —
            # e SÓ ela. `skill_md_hash` e os scores ficam FORA da retenção de propósito:
            # redigir o hash faria todo run parecer eternamente obsoleto e travaria o
            # portão A1 da publicação, e nem hash nem nota são texto de titular.
            #
            # `or {}` é estreitamento de tipo, não fallback: `reter_output` devolve
            # `dict | None` porque `invocacao.output` é anulável no §4.1, e aqui o payload
            # nunca é `None`.
            gravavel = portao.reter_output({"saida": saida}) or {}
            avaliacoes.append(
                {
                    "case_id": str(caso.id),
                    "dimensoes": caso.dimensoes,
                    "notas": judge.interpretar_notas(veredito, caso.dimensoes),
                    **gravavel,
                }
            )
        consolidado = regras_harness.consolidar(avaliacoes)
        fim = self._relogio.agora()
        run = HarnessRun(
            id=uuid.uuid4(),
            skill_versao_id=skill.id,
            resultados={
                "casos": avaliacoes,
                "score_por_dimensao": consolidado["score_por_dimensao"],
                "dimensoes_reprovadas": consolidado["dimensoes_reprovadas"],
                "skill_md_hash": regras_harness.hash_skill_md(skill.skill_md),
            },
            score=consolidado["score"],
            passou=consolidado["passou"],
            created_at=fim,
        )
        self._repo.adicionar_harness_run(run)
        self._registrar_invocacao(  # Art. 20: o ledger via_ai não pode ter buraco
            tenant_id,
            agente=agente,
            skill=skill,
            portador_id=portador_id,
            portao=portao,
            input={
                "proposito": "harness",
                "agente": agente.nome,
                "skill_versao": skill.versao,
                "casos": len(casos),  # número: atravessa a retenção intacto (é métrica)
                "modelo_perfil": perfil,
            },
            output={"harness_run_id": str(run.id), "score": run.score, "passou": run.passou},
            judge_notas=dict(consolidado["score_por_dimensao"]),
            inicio=inicio,
            fim=fim,
            tokens=tokens_uso,
        )
        self._evento(
            tenant_id,
            "harness.run",
            {
                "agente": agente.nome,
                "versao": skill.versao,
                "harness_run_id": str(run.id),
                "score": run.score,
                "passou": run.passou,
            },
            actor,
        )
        self._tracer.trace(  # §10.8: harness runs traceados com tag `harness`
            trace_id=str(run.id),
            nome=f"harness.{agente.nome}",
            metadados={
                "tenant": tenant_id,
                "agente": agente.nome,
                "skill_versao": skill.versao,
                "modelo_perfil": perfil,
                "tags": ["harness"],
            },
            spans=[
                {
                    "nome": "harness",
                    "casos": len(casos),
                    "latencia_ms": int((fim - inicio).total_seconds() * 1000),
                }
            ],
        )
        return _run_out(run)

    # ----------------------------------------------------- POST /skills/{id}/publicar
    def publicar(self, tenant_id: str, skill_id: uuid.UUID, *, actor: str) -> dict[str, Any]:
        """Portão §8-M12-A1 (docstring do módulo). NÃO toca `os.frozen` de nenhuma OS
        (A2): o congelado do GO permanece; só o `versoes_skills_publicadas()` muda."""
        skill, agente = self._skill_do_tenant(tenant_id, skill_id)
        if skill.estado != "em_revisao":
            raise EstadoSkillInvalido(
                f"Transição inválida: {skill.estado} → publicada — o ciclo é "
                "draft→em_revisao→publicada (§8-M12)."
            )
        runs = self._repo.listar_harness_runs(skill.id)
        ultimo = runs[-1] if runs else None
        if ultimo is None:
            raise HarnessNaoAprovado(
                "Publicar exige harness VERDE (§8-M12-A1) — nenhum harness_run "
                "registrado para esta versão; rode POST /skills/{id}/harness."
            )
        if ultimo.resultados.get("skill_md_hash") != regras_harness.hash_skill_md(skill.skill_md):
            raise HarnessNaoAprovado(
                "Harness_run obsoleto: o skill_md mudou depois do último run — "
                "rode o harness de novo sobre o texto atual (§8-M12-A1)."
            )
        if not ultimo.passou:
            raise HarnessNaoAprovado(
                f"Harness reprovado (score {ultimo.score}; dimensões < 90: "
                f"{ultimo.resultados.get('dimensoes_reprovadas')}) — publicar exige "
                "score ≥ 90 por dimensão do judge (§7.1)."
            )
        skill.estado = "publicada"
        skill.harness_score = ultimo.score
        skill.publicada_em = self._relogio.agora()
        self._repo.salvar_skill(skill)
        self._evento(
            tenant_id,
            "skill.publicada",
            {
                "agente": agente.nome,
                "versao": skill.versao,
                "skill_id": str(skill.id),
                "harness_run_id": str(ultimo.id),
                "score": ultimo.score,
            },
            actor,
        )
        return _skill_out(skill, runs)

    # ------------------------------------------------------ POST /skills/{id}/dry-run
    def dry_run(
        self,
        tenant_id: str,
        skill_id: uuid.UUID,
        *,
        entrada: dict[str, Any],
        portador_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Lado a lado (§8-M12): MESMA entrada na versão publicada ATUAL e na candidata.
        Nenhuma decisão automática (§1.1.3).

        "Nada persiste" segue valendo para o DOMÍNIO — nenhuma skill muda de estado,
        nenhum `harness_run` nasce. O ledger `invocacao` passa a ser gravado, e isso não
        é exceção à regra: o Art. 20 não tem cláusula de dispensa para comparação lado a
        lado, e era por esta rota que a auditoria mediu `invocacoes gravadas = 0` com CPF
        em claro no prompt.
        """
        candidata, agente = self._skill_do_tenant(tenant_id, skill_id)
        portao = portao_ia.de(  # política PUBLICADA (§10.2) + gasto do teto (J02)
            self._publicacoes_ia,
            tenant_id,
            gasto_tokens=portao_ia.gasto_do_dia(
                cast(_LedgerInvocacoes, self._repo), self._relogio, tenant_id
            ),
        )
        # §10.2 (C02): a `entrada` é o corpo do POST — texto que alguém digitou na tela.
        # Saneada UMA vez e usada nos dois lados: lado a lado só é comparação se as duas
        # versões receberem exatamente o mesmo texto.
        entrada = portao.sanear_estrutura(entrada)
        publicadas = [
            s
            for s in self._repo.listar_skills(agente.id)
            if s.estado == "publicada" and s.publicada_em is not None and s.id != candidata.id
        ]
        atual = max(publicadas, key=lambda s: s.publicada_em) if publicadas else None  # type: ignore[arg-type,return-value]
        avisos: list[str] = []
        if atual is None:
            avisos.append(
                f"Agente {agente.nome!r} sem versão publicada anterior — lado 'atual' vazio."
            )
        return {
            "agente": agente.nome,
            # a entrada devolvida é a SANEADA: a tela tem de mostrar o que de fato foi ao
            # modelo, senão o lado a lado mentiria sobre o texto que foi comparado.
            "entrada": entrada,
            "atual": self._executar_lado(
                atual,
                entrada,
                agente=agente,
                portao=portao,
                tenant_id=tenant_id,
                portador_id=portador_id,
            ),
            "candidata": self._executar_lado(
                candidata,
                entrada,
                agente=agente,
                portao=portao,
                tenant_id=tenant_id,
                portador_id=portador_id,
            ),
            "avisos": avisos,
        }

    # ------------------------------------------------------------ resolução por OS
    def versao_para_os(self, tenant_id: str, os_id: uuid.UUID, agente_nome: str) -> dict[str, Any]:
        """Versão EFETIVA do agente para a OS: em voo (GO executado) → a congelada em
        `os.frozen.agent_versions` (§4.1/A2); senão a publicada atual."""
        os_ = self._repo.obter_os(tenant_id, os_id)
        if os_ is None:
            raise NaoEncontrado(f"OS {os_id} não encontrada no tenant {tenant_id!r}.")
        congeladas = (os_.frozen or {}).get("agent_versions") or {}
        if agente_nome in congeladas:
            return {"agente": agente_nome, "versao": congeladas[agente_nome], "origem": "frozen"}
        return {
            "agente": agente_nome,
            "versao": self._repo.versoes_skills_publicadas().get(agente_nome),
            "origem": "publicada",
        }

    # ----------------------------------------------------------------- privados
    def _executar_lado(
        self,
        skill: SkillVersao | None,
        entrada: dict[str, Any],
        *,
        agente: Agente,
        portao: portao_ia.PortaoIa,
        tenant_id: str,
        portador_id: uuid.UUID,
    ) -> dict[str, Any] | None:
        if skill is None:
            return None
        parseada = parse_skill_md(skill.skill_md)
        # §10.2 (C02): o corpo da skill é texto digitado na tela do T16. Saneado em linha
        # PRÓPRIA, e não dentro dos argumentos do `chat`, porque o vigia de CI lê ordem de
        # linha: saneamento escondido no argumento é indistinguível, para quem revisa e
        # para o teste, de saneamento nenhum.
        corpo = portao.sanear(parseada.corpo)
        inicio = self._relogio.agora()
        # (f) §7.2: o perfil vem do front-matter que o USUÁRIO escreveu (docstring do
        # módulo). Sem esta linha, publicar `modelos_permitidos` não muda nada aqui — que
        # foi exatamente o que a auditoria mediu ("perfis usados = ['120b']").
        portao.autorizar_modelo(agente.nome, parseada.modelo_perfil)
        saida, tokens_uso = self._llm.chat(
            judge.montar_mensagens_execucao(corpo, entrada),
            perfil=parseada.modelo_perfil,  # type: ignore[arg-type]  # validado §7.1
        )
        fim = self._relogio.agora()
        self._registrar_invocacao(
            tenant_id,
            agente=agente,
            skill=skill,
            portador_id=portador_id,
            portao=portao,
            input={
                "proposito": "dry_run",
                "agente": agente.nome,
                "skill_versao": skill.versao,
                "entrada": entrada,  # já saneada (C02); a retenção decide se é gravada
            },
            output={"saida": saida},
            inicio=inicio,
            fim=fim,
            tokens=tokens_uso,
        )
        return {
            "skill_id": str(skill.id),
            "versao": skill.versao,
            "estado": skill.estado,
            "saida": saida,
        }

    def _registrar_invocacao(
        self,
        tenant_id: str,
        *,
        agente: Agente,
        skill: SkillVersao,
        portador_id: uuid.UUID,
        portao: portao_ia.PortaoIa,
        input: dict[str, Any],
        output: dict[str, Any],
        inicio: datetime,
        fim: datetime,
        judge_notas: dict[str, Any] | None = None,
        tokens: int | None = None,
    ) -> None:
        """Ledger via_ai (§4.1 `invocacao`) do Ateliê — o Art. 20 não pode ter buraco.

        `os_id` NULL porque o Ateliê é de PLATAFORMA, não de uma OS (mesma escolha do
        `ajuda_service`). Ponto ÚNICO de gravação do serviço, pelo mesmo motivo que o
        `criativo_service` tem o seu: a retenção (§10.4) é aplicada aqui, então nem o
        harness nem o dry-run escapam dela por esquecimento em um call site.
        """
        cast(_LedgerInvocacoes, self._repo).adicionar_invocacao(
            Invocacao(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                os_id=None,  # Ateliê é PLATAFORMA, não OS (§4.1: os_id NULL)
                agente_id=agente_uuid(agente.nome),
                skill_versao=skill.versao,
                usuario_portador=portador_id,
                input=portao.reter_input(input),
                output=portao.reter_output(output),
                judge=judge_notas,
                tokens=tokens,  # I04: usage do provedor (harness soma exec+judge) — §10.8
                latencia_ms=int((fim - inicio).total_seconds() * 1000),
                created_at=fim,
            )
        )

    def _parse_para_agente(self, agente: Agente, skill_md: str) -> SkillMd:
        parseada = parse_skill_md(skill_md)
        if parseada.nome != agente.nome:
            raise SkillMdInvalido(
                f"front-matter `name: {parseada.nome}` diverge do agente "
                f"{agente.nome!r} (§7.1 — a skill pertence ao agente).",
                erros=[f"name {parseada.nome!r} != agente {agente.nome!r}"],
            )
        return parseada

    def _agente(self, tenant_id: str, agente_id: uuid.UUID) -> Agente:
        agente = self._repo.obter_agente(tenant_id, agente_id)
        if agente is None:
            raise NaoEncontrado(f"Agente {agente_id} não encontrado no tenant {tenant_id!r}.")
        return agente

    def _skill_do_tenant(self, tenant_id: str, skill_id: uuid.UUID) -> tuple[SkillVersao, Agente]:
        skill = self._repo.obter_skill(skill_id)
        agente = self._repo.obter_agente(tenant_id, skill.agente_id) if skill is not None else None
        if skill is None or agente is None:  # tenant errado não vaza existência
            raise NaoEncontrado(f"Skill {skill_id} não encontrada no tenant {tenant_id!r}.")
        return skill, agente

    def _evento(self, tenant_id: str, tipo: str, payload: dict[str, Any], actor: str) -> None:
        self._repo.adicionar_evento(
            EventoDominio(
                tenant_id=tenant_id,
                os_id=None,  # eventos de PLATAFORMA (Ateliê não é escopado a OS)
                type=tipo,
                payload=payload,
                actor=actor,
                via_ai=False,
                created_at=self._relogio.agora(),
            )
        )


# ------------------------------------------------------------- helpers puros do módulo
def _agente_out(agente: Agente) -> dict[str, Any]:
    return {
        "id": str(agente.id),
        "tenant_id": agente.tenant_id,
        "nome": agente.nome,
        "camada": agente.camada,
        "etapa_workflow": agente.etapa_workflow,
        "modelo_perfil": agente.modelo_perfil,
        "deterministico": agente.deterministico,
    }


def _skill_resumo(skill: SkillVersao) -> dict[str, Any]:
    return {
        "id": str(skill.id),
        "versao": skill.versao,
        "estado": skill.estado,
        "harness_score": skill.harness_score,
        "publicada_em": skill.publicada_em.isoformat() if skill.publicada_em else None,
    }


def _skill_out(skill: SkillVersao, runs: list[HarnessRun]) -> dict[str, Any]:
    return {
        **_skill_resumo(skill),
        "agente_id": str(skill.agente_id),
        "skill_md": skill.skill_md,
        "execution_profile": skill.execution_profile,
        "bases_rag": skill.bases_rag,
        "harness_runs": [_run_out(r) for r in runs],
    }


def _run_out(run: HarnessRun) -> dict[str, Any]:
    return {
        "id": str(run.id),
        "skill_versao_id": str(run.skill_versao_id),
        "score": run.score,
        "passou": run.passou,
        "score_por_dimensao": run.resultados.get("score_por_dimensao"),
        "dimensoes_reprovadas": run.resultados.get("dimensoes_reprovadas"),
        "casos": len(run.resultados.get("casos") or []),
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }
