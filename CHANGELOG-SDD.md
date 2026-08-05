# CHANGELOG-SDD

Registro de emendas e decisões sobre o SDD-Jornada.md (regra §1.3.3: toda divergência
necessária edita o SDD na seção afetada + entrada aqui, no mesmo PR).

## 2026-08-05 — UAT-UI: correções (lote frontend A16/A14/A12/A10/A6)
Complemento de frontend do mesmo UAT (relatório em `docs/UAT-VPS-2026-08-05.md`);
nenhuma mudança de contrato de API além da emenda §8-M7 já registrada abaixo (A14).
- **A16 · página branca (React #185) na rota `simulacao` sem twin:** causa raiz era
  selector zustand com fallback instável (`cenarios[osId] ?? []` criava array novo a
  cada snapshot → loop do `useSyncExternalStore`); fallback agora é a constante
  `SEM_CENARIOS` (`pages/Ensaio.tsx`). Blindagem estrutural: `ErrorBoundary` global
  em dois níveis — por rota dentro do shell (keyed por `pathname`, o chrome sobrevive)
  e na raiz (último recurso) — com fallback amigável + Recarregar.
- **A14 (parte front):** T7 carrega a última versão persistida via
  `GET /os/{id}/jornada` ao montar com store vazio (reload do navegador); 404 mantém o
  botão Gerar; erro não-404 vira `BannerErro`; estado de carregamento explícito.
- **A12 · Data Cloud sem ação "usar":** botão "Usar como entrada no Estúdio (T5)" por
  segmento (`POST /datacloud/segmentos/{id}/usar`, ação que já existia na API §8-M5)
  com busy por linha e sucesso navegando ao T5 com o segmento em foco.
- **A10 (não reproduzido no código atual — cada botão já POSTa o campo da própria
  linha):** blindagem com busy/disabled POR LINHA via `mutation.variables` e rótulos
  Validando…/Abrindo… em `pages/Validacao.tsx`.
- **A6 (não reproduzido — o detail do 409 problem+json já vira banner):** o banner de
  erro da esteira agora faz `scrollIntoView` ao surgir (nunca fica fora do viewport).

## 2026-08-05 — UAT real na VPS (gpt-oss-120b) · fixes A13/A14/A15/A2/A17
- **A13 · KeyError 'to' no taxímetro (emenda de robustez, sem mudança de contrato do
  §5.1):** o 120b real gera arestas com aliases `source`/`target`. Correção em 3
  camadas: (a) `normalizar_arestas` (`domain/jornada/validacao.py`) converte
  `source`→`from`/`target`→`to` nas ENTRADAS (gerar/ajustar/PUT — chamado no
  `_normalizar_meta` do `ServicoJornada`, antes do `jgc_validate`; contrato interno e
  hash canônico seguem `from`/`to`); (b) `jgc_validate` (§5.3) passa a EXIGIR
  `from`/`to` presentes E apontando para nós existentes, com mensagem clara por campo
  (alimenta o retry §7.3 do flow); (c) `taximetro.py` ignora aresta/nó malformado na
  adjacência (quem aponta erro é o validador) — nunca mais KeyError bruto → 500.
  Testes: `test_M7_arestas_source_target_normalizadas`,
  `test_M7_aresta_sem_to_e_no_inexistente_422`, unit `test_jornada_arestas.py`.
- **A14 · canvas sem leitura (EMENDA §8-M7 — endpoint novo):** `GET /os/{id}/jornada`
  devolve a ÚLTIMA versão do twin (404 problem+json sem versão); leitura 100%
  determinística (LLM proibido §10.6). O front deixa de depender do estado de sessão
  para reabrir o T7. Seeds §11.4: a jornada demo agora tem a paleta REALISTA do §5.2
  (entry por DE, randomSplit com holdout, **sto**, **decisionSplit**, wait,
  channel.email/push/sms/whatsapp, goal, exit) e nasce `publicado` (launch em rampa ⇒
  apply ok M9) — o canvas da demo nunca abre vazio. Testes:
  `test_M7_get_jornada_ultima_versao`, `test_seeds_demo_jornada_publicada_no_canvas`.
- **A15 · seeds com uuid4 (links quebravam a cada restart):** `demo_seeds.py` e
  `atelie_seeds.py` passam a gerar ids DETERMINÍSTICOS —
  `uuid5(NAMESPACE_URL, 'jornada/<rotulo>')` (ex.: `jornada/os/OS-2026-0457`,
  `jornada/agente/flow`, `jornada/snapshot/OS-2026-0457`) para OS/etapas/segmento/
  certificado/jornada/experimento/snapshot/sync_run/launch/propostas/aprendizados/
  agentes/skills/harness cases/policy. Restart re-semeia com os MESMOS ids. Teste:
  `test_seeds_ids_deterministicos_entre_restarts` (2 boots com relógios diferentes).
- **A2 · consultor em OS com briefing completo:** `montar_mensagens`
  (`agents/consultor.py`) com `faltantes` vazio agora envia `briefing_completo: true`
  + instrução 'briefing completo: atue como consultor estratégico da campanha; não
  invente faltantes nem pergunte campo já preenchido'; regra espelhada no
  `consultor.skill.md` (§7.1). Teste:
  `test_montar_mensagens_briefing_completo_instrui_consultoria`.
- **A17 · insight recusava vocabulário livre:** novo `consulta_por_sinonimo`
  (`agents/insight.py`) — mapa determinístico sinônimo→métrica CANÔNICA consultado
  ANTES da recusa pós-LLM ('conversão por real gasto'/'custo-benefício por canal' →
  `custo_por_pedido`; ROI → `roas`; 'incremental'/'contra o holdout' → `lift`;
  'batemos a meta' → `atingimento_meta`); skill instruída com os mesmos sinônimos.
  Todo alvo do mapa EXISTE no dicionário (§7.2 — zero SQL livre) e a pré-guarda de
  PII (A4) permanece soberana. Testes: `test_M10_perguntar_sinonimo_nao_recusa`,
  unit `test_insight_sinonimos.py`.

## 2026-08-05 — MS8 · Auditoria final (build + pytest + smoke e2e da jornada feliz) — notas
- **Build/pytest:** `npm run build` (tsc -b + vite) verde; pytest 131 verdes (130 do
  MS0–MS8 + 1 regressão nova abaixo). Cobertura e gates do §13 inalterados.
- **Smoke e2e — ESCOLHA REGISTRADA (§13/MS8):** executado via **chamadas HTTP REAIS
  às rotas** (uvicorn local :8000 + `vite preview` :4173 com proxy `/api` validado),
  NÃO via Playwright (browsers não instalados nesta máquina; a verificação visual das
  telas foi feita manualmente no browser sobre o preview). Duas portas dubladas
  exatamente como o SDD manda para ambiente sem rede: `app.state.llm` = `LLMFake`
  com a resposta enlatada do flow (§1.3.5 — único adapter de LLM permitido fora do
  hub) e `app.state.sfmc_port` = mock-sfmc §11.1 in-process (o MESMO mock que o
  compose sobe como container). Jornada feliz completa numa OS NOVA nascida do
  intake: T1 (cockpit) → T2 (pedido 100% → converter, fase pensada) → T3/T4 (5
  validações `ok` → GO, fase criada + .docx) → T5 (Data Cloud `usar` → Guard
  certifica, 7 listas) → T7 (flow → JGC v1 válido + taxímetro) → T8 (simular
  semáforo verde → congelar previsto) → T9/T10 (snapshot → link mágico → página SEM
  Bearer → decidir aprovado) → T11 (plan 8 recursos → apply ok no mock-sfmc) → T12
  (armar → onda 1 → onda 2, breakers limpos) → T13 (monitor 200; na OS demo §11.4 o
  monitor traz previsto×realizado com os números calibrados das seeds).
- **Fix de auditoria (`application/services/simulador_service.py`):** `simular`
  estourava 500 (`float(dict)`) em OS nascida do intake REAL — o briefing §4.1 guarda
  `{valor, inferido}` e a verba vem humana ("R$ 500.000"); os aceites M8 semeavam OS
  sem briefing e nunca exercitavam o caminho. Novo helper puro `_numero` (forma §4.1
  + moeda pt-BR; não-numérico → None — verba ausente não bloqueia o Ensaio, ticket
  cai nos priors) usado para `ticket_medio` e `verba`; regressão em
  `tests/unit/test_simulador_numero.py`. Nenhum contrato alterado.

## 2026-08-05 — MS8 · Frontend SPA — 18 telas do §12 fiéis aos mocks — notas de implementação
- **Entrega (`frontend/` — Vite+React+TS, Tailwind, TanStack Query, zustand,
  @xyflow/react, Recharts — stack fechada do §12):** SPA completa com as 18 telas dos
  mocks: T1 Cockpit (kanban por fase + saúde derivada) · T2 Sala de Ideação (conversa
  + briefing estruturado ao vivo, inferido em âmbar até confirmação) · T3 Validação
  campo-a-campo (veredito + evidência da fonte) · T4 War Room (threads ancoradas +
  portão GO) · T4a Esteira (7 etapas + checklist de criativos) · T5 Audiência
  (Estúdio SQL + waterfall + certificado do Guard) · T5a Data Cloud (relatório +
  usar segmento) · T6 Criativo (matriz canal×variante + KV master) · T7 Twin/Canvas
  (@xyflow/react, nós tipados na paleta Journey Builder) · T8 Ensaio Geral (funil
  P10/P50/P90 + semáforo + comparar cenários + congelar previsto) · T9 Portões ·
  T10 Aprovação standalone `/aprovacao/:token` (SEM shell, token é a credencial) ·
  T11 Pré-voo & Drift · T12 Lançamento (armar/ondas/kill/retomar + breakers) ·
  T13 Monitor (previsto fantasma × realizado sólido, Recharts) · T14 Pergunte aos
  Dados (camada semântica, SQL público + downgrade a próximo do congelado) ·
  T15 Otimização & Retro (propostas com diff/impacto/score, apuração do experimento,
  aprendizados) · T16 Ateliê (agentes/skills/harness/publicar/dry-run + auditoria).
- **Fidelidade visual (REFERÊNCIA OBRIGATÓRIA = mocks das 18 telas):** tokens
  extraídos dos mocks para o `tailwind.config.js` — chrome vermelho Claro `#D0271C`
  (topbar + rail colapsável) e `#A81E14` (item ativo/pills), centro operacional em
  `#F3F5F8`, painel direito do copiloto, paleta Journey Builder no canvas
  (`jb-entry #2E844A` · `jb-msg #0B827C` · `jb-flow #DD7A01` · `jb-ein #9050E9` ·
  `jb-upd #0176D3`) e paleta de gráficos CVD-safe (ch1..ch4) no previsto×realizado.
- **Contrato de consumo:** SOMENTE os endpoints do §8 via `/api/v1` (proxy Vite →
  localhost:8000; `vite preview` herda o proxy), header `X-Tenant` + Bearer dev
  (`dev-<papel>`, trocável via localStorage sem rebuild), erros RFC-7807 tipados
  (`ApiError.degradado` → 503 `modo: degraded` §10.6 vira modo manual na UI).
- **Decisão de estado (consequência do §8):** artefatos SEM endpoint de leitura no
  §8 (jornada gerada, simulação corrente, snapshot/link da sessão) vivem no store
  `producao` (zustand) enquanto a sessão produz o ciclo T7→T12; telas de LEITURA
  (briefing, workflow, segmento, monitor, propostas, portões, auditoria) leem SEMPRE
  do backend via TanStack Query — a OS demo §11.4 alimenta essas telas sem passo
  manual (o canvas T7 da demo nasce de um clique em "Gerar jornada (Flow)").

## 2026-08-05 — Seeds DEMO_MODE (§11.4) + id do experimento no portão T9 — notas de implementação
- **Entrega (`adapters/demo_seeds.py`, wiring em `app/main.py:create_app(demo=…)`,
  aceite `tests/acceptance/test_seeds_demo.py`):** materializa o item §11.4 "Seeds
  DEMO_MODE: OS-2026-0457 completa" — briefing 14 campos, segmento 847.312 (waterfall
  + volume de abordagem + certificado do Guard), esteira T4a com 7 etapas, JGC de 4
  canais com holdout 90/10, Ensaio Geral + **Previsto CONGELADO** em snapshot
  (hash composto real), apply ok, launch `em_rampa` (onda 2), telemetria de 20 dias
  (ENS + extract espelhado < 2% — reconciliação A3 sem alerta) calibrada para
  **lift +24,1pp (IC95 ≈ [+18,6, +29,6], significativo) e ROAS 18,5x**, experimento
  pré-registrado com janela de 15 dias JÁ FECHADA (apuração T15 funciona na demo sem
  ferir o anti-peeking A1), 2 propostas pendentes do optimize (diff/esforço/risco/
  score pelas funções reais do M11 — sem LLM) e 3 aprendizados.
- **Wiring:** `create_app(demo=None)` → automático quando `DEMO_MODE=true` e
  `APP_ENV=dev`; o conftest dos aceites usa `demo=False` (módulos M0–M12 valem sobre
  repositório vazio; as seeds só ADICIONAM dados). O marco de telemetria do launch é
  gravado APÓS as seeds — breakers avaliam janela limpa (§8-M10).
- **Emenda aditiva ao payload do portão de experimento (§8-M8 T9):**
  `GET /os/{id}/portoes → portoes.experimento` agora inclui `id` do experimento —
  o T15 (§8-M11) precisa do alvo de `POST /experimentos/{id}/apurar` e o SDD não
  define outro GET que o exponha. Campo extra, nenhum contrato existente alterado.

## 2026-08-05 — M12 (parte 2) · Políticas + Auditoria (§8-M12, §4.1 `policy_versao`/`invocacao`) — notas de implementação
- **Entrega (router `api/v1/plataforma.py`, tags `policies` e `auditoria` — mesmo
  módulo M12, dois recursos, padrão M8 T9/T10; serviço
  `application/services/plataforma_service.py`; domínio em
  `domain/governanca/politicas.py` + `modelos.PolicyVersao` + erros; porta
  `application/ports/repositorio_plataforma.py`; aceite `test_M12_A3` +
  `test_M12_policies_e_drift`):** policy-as-code com ciclo draft→publicada e versão
  SEQUENCIAL, relatório de policy drift sobre OSs em voo e auditoria com
  reconstrução Art. 20 LGPD. SEM migração nova: `policy_versao`, `domain_event` e
  `invocacao` já constam da `0001_core` (§4.1); head permanece `0009_m11_otimizacao`.
- **Materialização do "GET/POST /policies (draft→publicada; relatório de policy
  drift)" em endpoints concretos:** `GET/POST /policies` ·
  `POST /policies/{id}/publicar` (só draft com versão MAIOR que a publicada — draft
  obsoleto 409; evento `policy.published` §2.3; publicar é papel `lider`, portão de
  plataforma como skills; NÃO toca `os.frozen` — simetria com A2) ·
  `GET /policies/drift` · `POST /policies/drift/pendencias`. Conteúdo validado por
  CÓDIGO no conjunto FECHADO do §4.1 (compliance nunca é LLM §1.1.3) com erros
  ACUMULADOS → 422 (padrão do parser §7.1). Seed §11.4 "políticas v1": a política v1
  do domínio vira linha PUBLICADA de `policy_versao` (mesmos valores do fallback do
  GO — `test_M4-A2` permanece válido); `PublicacoesAtelie.politica_publicada()`
  passa a ler o banco (fallback domínio), então um NOVO GO congela a versão nova.
- **Relatório de policy drift (decisão de escopo v1):** OS em VOO = `frozen` não
  nulo + fase ≠ encerrada; em drift = `frozen.policy_version` < versão publicada.
  Violações verificáveis nos artefatos CONGELADOS: holdout de segmento <
  `holdout_min` novo e breakers congelados no armar (§4.1 `launch.breakers`, launch
  não terminal) mais FROUXOS que os novos (`*_max`: congelado > novo). Caps de
  frequência/quiet hours não têm artefato congelado comparável no v1 — fora do
  relatório. Pendências de adequação são OPCIONAIS (POST explícito), NÃO bloqueantes
  (a política nova não trava retroativamente OS aprovada na antiga) e idempotentes
  por `origem = policy_drift:v{n}`.
- **Auditoria (Art. 20):** `GET /auditoria` filtra tipo/agente/OS (+ `via_ai`);
  evento via_ai com `invocacao_id` embute o DETALHE COMPLETO do ledger `invocacao`
  (input+evidências+output+judge+aceite humano) — o "clicável" da T16.
  `POST /auditoria/reconstruir/{invocacao_id}` devolve EXATAMENTE
  input/evidências/output/judge DA ÉPOCA (A3 — o ledger é imutável; skill nova
  publicada depois não muda nada) e registra `auditoria.reconstruida` no outbox.
  RBAC da reconstrução: `dpo|lider` (atende o titular; admin sempre passa §8-M0).

## 2026-08-05 — M12 (parte 1) · Ateliê T16 (§8-M12, §7.1, §4.1 mesh) — notas de implementação
- **Entrega (router `api/v1/atelie.py`, tag `atelie`; serviço
  `application/services/atelie_service.py`; domínio `domain/atelie/`; judge
  `agents/harness/judge.py`; seeds `adapters/atelie_seeds.py` +
  `mocks/seeds/harness_cases.json`; aceites `test_M12_A1/A2` + contratos):** parser
  PLENO do SKILL.md canônico (§7.1 — valida campos: name/version/camada/
  modelo_perfil, `bases_rag` no conjunto fechado do §4.1, exige_evidencia,
  max_retries, saida; 422 com a lista de erros), CRUD agentes/skills com ciclo
  draft→em_revisao→publicada, harness com judge 120b de rubrica fixa (LLMFake
  determinístico em teste §1.3.5; `harness_run` com score POR DIMENSÃO; trace tag
  `harness` §10.8), portão de publicação (A1: sem run VERDE — passou com score ≥ 90
  por dimensão — 409) e dry-run lado a lado (mesma entrada, atual × candidata; nada
  persiste). SEM migração nova: `agente`/`skill_versao`/`harness_case`/`harness_run`
  já constam da `0001_core` (§4.1); head permanece `0009_m11_otimizacao`.
- **Materialização do "CRUD agentes/skills" (§8-M12) em endpoints concretos:**
  `GET/POST /agentes` · `GET/POST /agentes/{id}/skills` · `GET/PUT /skills/{id}`
  (editável SÓ em draft — em revisão o harness julga texto estável) ·
  `POST /skills/{id}/revisao|harness|publicar|dry-run`. Publicar exige papel
  `lider` (portão de plataforma; RBAC §8-M0). Guarda-corpo adicional: `harness_run`
  guarda `skill_md_hash` — run que não cobre o texto ATUAL não publica (409).
- **Fonte das versões publicadas passa ao banco do Ateliê:** o GO (§8-M4-A2)
  congela agora via `PublicacoesAtelie` (banco `skill_versao`, fallback disco
  `PublicacoesLocais` com os MESMOS valores — seeds espelham `agents/skills/*.md`
  como v1 publicadas). A2 verificada ponta a ponta: publicar skill nova NÃO reescreve
  `os.frozen` de OS em voo (resolução por OS: `versao_para_os` — frozen → congelada;
  sem GO → publicada atual); um NOVO GO congela a versão nova.
- **Parser mínimo do M3 substituído:** `agents/consultor.carregar_skill` agora
  delega ao parser pleno (`domain/atelie/skill_parser.py`), como o próprio M3
  prometia ("o parser pleno chega com o Ateliê"). Seeds §11.4 ganham
  `harness_cases.json` (3 casos golden por agente-chave com SKILL.md; `guard`
  semeado como agente DETERMINÍSTICO sem skill §7.2). Política (`GET/POST
  /policies`), auditoria e reconstrução Art. 20 ficam para a parte 2 do M12.

## 2026-08-05 — M11 · Otimização/Retro/Calibração T15 (§8-M11, §4.1 `experimento`/`calibracao_prior`)
- **Entrega (router `api/v1/otimizacao.py`, tag `otimizacao`; serviço
  `application/services/otimizacao_service.py`; domínio `domain/otimizacao/` +
  `domain/experimento/apuracao.py`; migração `0009_m11_otimizacao`; aceites
  `test_M11_A1..A3` + contratos):**
  - **Agente optimize** (`agents/otimizacao.py` + `skills/optimize.skill.md`, 120b
    §7.2): PROPOR é a ÚNICA ação autônoma — `GET /os/{id}/propostas` sem pendentes
    faz o agente propor grafos JGC candidatos; TODO o resto é CÓDIGO (§1.3.5/§10.6):
    `meta.osCodigo/tenant` reescritos, `jgc_validate` §5.3 descarta candidata
    inválida (com evidência em `avisos`), diff estrutural (`domain/jornada/diff.py`
    — código puro FATORADO do M7, `ServicoJornada` delega), impacto PRÉ-SIMULADO via
    SimuladorService (novo `ensaiar_grafo`: mesmo pipeline §6, MESMA seed/params da
    simulação base, NADA persiste) e ranking determinístico lift×esforço×risco
    (`domain/otimizacao/ranking.py`: lift relativo de conversões P50 ÷ (nº de
    mudanças × fator de risco por semáforo/custo↑/mexer no entrySource)). Ledger
    `invocacao` via_ai + `agent.invoked` + trace Langfuse (§10.8). Propostas
    pendentes NÃO regeneram (decidir é humano §1.1.3).
  - `POST /propostas/{id}/aprovar`: re-valida §5.3, gera NOVA `jornada_versao`
    (rascunho, taxímetro M7-A2, SEM simulação/previsto) e devolve o **mini-ciclo
    M8→M9 expresso** — hash novo ⇒ snapshot novo ⇒ **nova aprovação EXPRESSA (link
    mágico) antes de qualquer apply** (imposto pelos gates já existentes do M8/M9;
    nada é publicado pelo agente). Vira aprendizado ACEITO.
    `POST /propostas/{id}/rejeitar`: motivo OBRIGATÓRIO (422 sem ele) — vira SINAL
    (aprendizado `sinal`) injetado no prompt do optimize na próxima geração.
  - **Apuração** `POST /experimentos/{id}/apurar` (ZERO LLM): ANTI-PEEKING (A1) —
    janela = primeira exposição (`sent` ENS) + `janela_dias`; antes do fim → **425
    Too Early** (problem+json com `fim_janela`; nenhum lift calculado; janela
    correndo marca `em_apuracao` §4.1). Depois: lift pp + IC95
    (`domain/experimento/apuracao.py`, mesmo z do §6/M8/M10; n holdout proporcional
    ao `holdout_pct` congelado) e `significativo` ⇔ IC exclui zero (A2); resultado
    IMUTÁVEL em `experimento.resultado` (§4.1 `{lift, ic95, significativo, roas}`;
    re-apurar → 409) + evento `experimento.apurado`. Significativo ⇒ aprendizado
    PROMOVIDO + ingestão STUB na base RAG `resultados` (A3): linha
    `agente_evidence` com chunk/meta íntegros e `embedding=None` até o adapter
    pgvector (`rag reindex` §7.4).
  - `POST /os/{id}/clonar-com-aprendizados` (A3): nova OS (fase `pensada`, briefing
    copiado, código sequencial) herdando aprendizados ACEITOS/PROMOVIDOS como linhas
    próprias com `herdado_de` (sinal NÃO herda) + `priors` VIGENTES na resposta
    (última `calibracao_prior` publicada; o Ensaio Geral da nova OS já os usa).
  - **CalibrateService** (`ServicoCalibracao` + `domain/otimizacao/calibracao.py`,
    código puro): compara previsto CONGELADO (snapshot §1.1.2) × realizado
    (conversões ENS do tratado — mesmo recorte do monitor M10) por OS; razão global
    clampada [0.25, 4.0] escala as taxas de conversão dos priors vigentes; BACKTEST
    OBRIGATÓRIO (MAPE antes×depois; não melhora ⇒ 409, nada publicado);
    `POST /calibracao/publicar` versiona em `calibracao_prior` (§4.1; DDL já na
    0001) com score/backtest/publicada_em + evento `calibracao.publicada`.
    **Simulador passa a preferir priors publicados** (promessa de priors.py):
    `ServicoSimulador._priors_vigentes` — sem publicação, `PRIORS_DEFAULT` v1
    intacto (M8-A1 preservado; `parametros.priors_versao` reflete a versão usada).
- **Emenda §4.1 (nota final):** tabelas auxiliares ganham `proposta_otimizacao` e
  `aprendizado` (migração `0009_m11_otimizacao`); `experimento`, `calibracao_prior`
  e `agente_evidence` já constavam da 0001.
- **Decisões (sem mudança de contrato do produto):**
  - `GET /os/{id}/propostas` é o gatilho da proposição autônoma (o §8-M11 define o
    GET como o endpoint do optimize); sem versão SIMULADA → 409 (não há régua para
    pré-simular). Hub LLM fora → o GET **degrada** (200 com `degradado: true` e
    lista vazia/existente) em vez de 503: leitura nunca depende de LLM (§10.6);
    geração via LLM continua respondendo 503 apenas em mutações (nenhuma no M11).
  - Versão publicada de `calibracao_prior` começa em 2 — a v1 é o `PRIORS_DEFAULT`
    em código (priors.py); `versao` da linha = versão dos priors.
  - Relógio do M11 é INJETÁVEL via `app.state.relogio` (`get_relogio` no router —
    §2.1 clock atrás de porta): `test_M11_A1` prova o anti-peeking manipulando o
    ClockPort (mesma telemetria; 425 a 1s do fim da janela → 200 depois dela).
  - Apuração usa telemetria ENS (extract é conciliação — decisão M10) e ROAS
    realizado = conversões×ticket congelado ÷ Σ sent×tarifa vigente (Decimal).
  - Novos tipos de evento (§2.3 define os MÍNIMOS): `proposta.criada|aprovada|
    rejeitada`, `experimento.apurado`, `aprendizado.promovido`,
    `os.clonada_com_aprendizados`, `calibracao.publicada`.

## 2026-08-04 — Auditoria MS6 (sem mudança de contrato): mypy verde + lacuna do adapter
- Auditoria cética do MS6 confirmou os aceites `test_M10_A1..A4` + suíte completa
  (116 verdes), ruff/format limpos, caminho crítico (breakers/kill/guard) SEM
  import de LLM, zero PII em `telemetry_event`/fixtures (§10.2) e insight sem SQL
  livre (execução só por consulta nomeada — §7.2). Correções pequenas:
  - **Lacuna real**: `PublicacoesLocais` não implementava `tarifas_vigentes()`
    declarado na `PublicacoesPort` (taxímetro §8-M7-A2) — adapter completado com o
    seed §11.4 (`domain/custo/tarifas.py`).
  - Gate mypy do CI (§13) de volta ao verde: anotações/narrowing pontuais em
    `api/v1/{lancamento,criativo}.py`, `agents/{flow,engineer}.py`,
    `agents/guard/elegibilidade.py`, `domain/simulacao/{personas,motor}.py` e
    `domain/validacao/regras.py` — zero mudança de comportamento (116 testes
    inalterados antes/depois).

## 2026-08-04 — M10 · parte 3: Pergunte aos Dados T13/T14 (§8-M10, §7.2 insight, aceite A4)
- **Entrega:**
  - **Camada semântica** (`domain/lancamento/semantica.py`, CÓDIGO PURO): dicionário
    VERSIONADO (`VERSAO_CAMADA=1.0.0`) de consultas nomeadas `vw_metricas_*` — roas,
    lift, custo_por_pedido (param `canal`), atingimento_meta (param `meta`) — cada uma
    com whitelist de parâmetros e a definição SQL da view (a "query" anexada à
    resposta, §7.2: "mostra a query"). Execução SÓ por nome (`executar`); nome ou
    parâmetro fora do dicionário ⇒ `ConsultaForaDaCamada` (defesa em profundidade).
  - **Agente insight** (`agents/insight.py` + `skills/insight.skill.md`, 120b §7.2):
    o LLM só COMPÕE — NL → consulta nomeada + parâmetros; guarda-corpos de CÓDIGO
    descartam SQL livre, view desconhecida, parâmetro fora da whitelist e JSON
    malformado ⇒ RECUSA PADRÃO sem executar nada (A4). Pré-guarda determinística de
    escopo: pergunta pedindo dado individual/PII (CPF, telefone, "quem"...) recusa
    SEM chamar o LLM (§1.3.5: PII jamais em prompt) — funciona até em modo degradado.
  - **Rota** `POST /os/{id}/perguntar` (router `api/v1/insight.py`, tag `insight`;
    caso de uso `ServicoInsight`): resposta com `consulta_executada` (nome, versão,
    parâmetros, sql, resultado) + `recusado`/`motivo_recusa`; ledger `invocacao`
    via_ai (pergunta MASCARADA — runs de ≥11 dígitos nunca em claro §10.2) + evento
    `agent.invoked` (§2.3) + trace Langfuse `insight.perguntar` (§10.8, no-op em
    teste). Aceite `test_M10_A4` + contrato `test_M10_perguntar_contratos`.
- **Decisões (sem mudança de contrato do produto):**
  - "NL→SQL sobre views semânticas" (§8-M10) materializado como NL→**consulta
    nomeada + parâmetros** — o LLM nunca emite SQL executável; o SQL das views vive
    no dicionário em código e a execução em dev/teste é o equivalente determinístico
    em Python sobre o repositório em memória (mesmo racional da view `os_saude` §4.1:
    contrato SQL íntegro, adapter equivale). Views físicas entram com o adapter
    Postgres, sem tocar domínio/serviços (hexagonal §2.1).
  - Recusa NÃO é erro: 200 com `recusado=true` e recusa padrão (o portão duro de
    LLM continua LLMIndisponivel→503 degraded §10.6). Router SEPARADO de
    `lancamento.py`: breakers/kill seguem LLM-proibidos (§10.6) — perguntar é
    leitura assistida (RBAC: qualquer autenticado, padrão do monitor). OS sem
    Previsto congelado ⇒ 409 ANTES de chamar o LLM (mesma régua §1.1.2 do monitor).

## 2026-08-04 — M10 · parte 2: telemetria dupla + Monitor T13 (§8-M10, aceite A3)
- **Entrega (LLM PROIBIDO em todo o caminho — §10.6; tudo determinístico):**
  - **Extracts loader** (§8-M10 "job extracts loader"): porta `ExtractsPort`
    (`application/ports/extracts.py`) + adapter de fixture CSV
    `adapters/fontes/extracts.py` sobre `mocks/seeds/extracts_tracking.csv` (batch
    D-1 da OS demo: 96 sent · 99 delivered · 1 bounce · 8 conversion; hashes sha256
    SINTÉTICOS — nunca PII §10.2; coluna `grupo` vira `payload.grupo` da conversão).
    Caso de uso `ServicoLancamento.carregar_extracts`: resolve `os_codigo`→OS do
    tenant (linha desconhecida é ignorada e contada) e delega à MESMA ingestão
    guardada do webhook (PII/contrato §4.1; `fonte='extract'`).
  - **Reconciliação diária ENS×extract (A3)**: `domain/lancamento/reconciliacao.py`
    (CÓDIGO PURO — `comparar_fontes`: contagens por tipo, divergência relativa
    |ens−extract|/max×100, `LIMITE_DIVERGENCIA_PCT=2.0`) + caso de uso
    `ServicoLancamento.reconciliar`: divergência >2% em qualquer tipo ⇒ ALERTA —
    incidente `sev3` tipo `reconciliacao_divergente` (launch_id nulo: incidente da
    OS; DEDUPE por incidente aberto — o job diário não re-abre alerta em tratamento)
    + eventos `telemetry.reconciliada` / `telemetry.reconciliacao_divergente`.
  - **Monitor T13** (`GET /os/{id}/monitor`, router `api/v1/lancamento.py`, tag
    `launch`; leitura por qualquer autenticado — padrão `GET /os/{id}/saude` M1):
    TODOS os KPIs como PAR `{previsto, realizado}` (§1.1.2) — conversões, lift vs
    holdout COM IC95, ROAS, custo real, receita, `briefing.metas`×realizado e
    disparos/custo POR CANAL — calculados em `domain/lancamento/monitor.py` (CÓDIGO
    PURO) SEMPRE contra o `snapshot.previsto` CONGELADO (nunca a simulação
    corrente); resposta embute `reconciliacao` corrente + alertas abertos e
    `fontes` {ens, extract}. OS sem previsto congelado ⇒ `PrevistoAusente` → 409.
  - Aceite `test_M10_A3` (fixture diverge 4% no tipo `sent` → alerta + dedupe;
    monitor com par previsto×realizado em TODO KPI/canal/meta) + contrato
    `test_M10_monitor_exige_previsto` (409 sem previsto; 404 OS inexistente).
- **Decisões (sem mudança de contrato do produto):**
  - Telemetria DUPLA sem dobrar contagem: taxas e burn-rate dos breakers e o
    "realizado" do monitor medem SÓ o fluxo ENS (tempo real); `fonte='extract'` é o
    batch de conciliação D-1. EXCEÇÃO deliberada: o breaker
    `disparo_lista_supressao` varre os `sent` de TODAS as fontes — extract que
    revela disparo a contato suprimido também mata (A2).
  - Loader e reconciliação NÃO ganham endpoint (o §8-M10 os define como JOB; mesmo
    racional do M9: "não há endpoint novo fora do SDD") — casos de uso
    `carregar_extracts`/`reconciliar` prontos para o agendador diário; o aceite A3
    os exercita direto no serviço (padrão M8: semeadura via repositório/serviço).
  - Reconciliação v1 por CONTAGEM por tipo (match por `contato_hash` é evolução do
    adapter real de extracts); divergência relativa sobre a MAIOR fonte.
  - Realizado do monitor: conversões = eventos `conversion` do grupo tratado
    (`payload.grupo != 'holdout'` — mesmo recorte do motor §6); n tratado =
    contatos DISTINTOS com `sent`; n holdout proporcional ao `holdout_pct`
    congelado no snapshot (fallback: segmento da OS, default 10.0 §4.1); lift em pp
    com IC95 normal de duas proporções (mesmo z do §6) e `significativo` ⇔ IC
    exclui zero (regra §8-M11-A2); receita = conversões × ticket médio congelado no
    previsto; ROAS = receita/custo real; custo real = Σ sents × tarifa vigente
    (Decimal). Premissas ecoadas na resposta.
  - `ingerir_telemetria` passa a validar também `tipo` ∈ contrato §4.1 (o webhook
    já validava via Pydantic; o extract entra pelo mesmo funil guardado).
  - Novos tipos de evento (§2.3 define os MÍNIMOS): `telemetry.reconciliada`,
    `telemetry.reconciliacao_divergente`.

## 2026-08-04 — M10 · parte 1: Torre de Lançamento T12 (§8-M10, §4.1 `launch`)
- **Entrega (LLM PROIBIDO em todo o caminho — §10.6: breakers/kill/retomada são
  caminho crítico; tudo determinístico, actor `sistema` nas ações automáticas):**
  - `domain/lancamento/` — `modelos.py` (Launch/TelemetryEvent 1:1 com o §4.1 e
    `Incidente` da tabela auxiliar; rampa default `[{pct:1},{pct:10},{pct:100}]`),
    `breakers.py` (CÓDIGO PURO: avaliação sobre a telemetria da janela — optout,
    bounce, erro de entrega, burn-rate vs projetado e `disparo_lista_supressao` ⇒
    SEV1 + kill), `telemetria.py` (guarda-corpo §10.2: contato só sha256; payload
    com chave/valor de PII ⇒ 422, nada gravado) e `erros.py` (BreakerDisparado→409
    com `disparos`; AprovadorRepetido→403; demais EstadoInvalido→409).
  - `application/services/lancamento_service.py` (ServicoLancamento): `armar` exige
    APPLY OK do snapshot (§8-M10; sync_run fase=apply estado=ok) e congela
    `launch.breakers` da política publicada (§4.1 "limites da política congelada");
    `avancar_onda` roda o PORTÃO AUTOMÁTICO entre ondas (breakers limpos p/ avançar;
    disparo ⇒ pausa/kill automático + 409); após a última onda ⇒ `concluido`.
    `ingerir_telemetria` persiste `telemetry_event` e avalia os launches `em_rampa`
    das OSs afetadas (A1: optout>0,6% ⇒ `pausado_breaker` AUTOMÁTICO; A2: sent p/
    contato suprimido ⇒ incidente SEV1 TIPADO + KILL AUTOMÁTICO). `kill` em 2
    ETAPAS (solicitar devolve token; confirmar mata + incidente `kill_manual`).
    `retomar` SEMPRE humano (A1); incidente SEV1 aberto ⇒ 2 aprovadores DISTINTOS
    (repetido ⇒ 403, segregação §10.5); retomada resolve incidentes e reinicia a
    janela dos breakers (marco de telemetria em `launch.eventos`).
  - Rotas (`api/v1/lancamento.py`, tag `launch`): `POST /launch/{snapshot}/armar` ·
    `POST /launch/{id}/avancar-onda` · `POST /launch/{id}/kill` (+confirmação) ·
    `POST /launch/{id}/retomar` · `POST /webhooks/ens` (ingestão §8-M10 com
    ASSINATURA VERIFICADA: HMAC-sha256 do corpo com APP_SECRET no header
    `X-ENS-Signature`; sem Bearer — a assinatura é a credencial, racional do link
    mágico M8; 401 sem/ com assinatura errada). RBAC: armar/avançar/kill exigem
    analista|lider; retomar exige lider|aprovador (ato de alçada).
  - Portas/adapters: `RepositorioLancamento` + `ListaSupressaoPort` (§2.1);
    `adapters/fontes/lista_supressao.py` (fixtures) + seed
    `mocks/seeds/lista_supressao.json` (§11.4 "7 listas com contagens" — contagens
    coerentes com o read model M5; `amostras` = hashes sha256 SINTÉTICOS, nunca
    PII). `RepositorioOsMemoria` implementa também `RepositorioLancamento`.
  - Migração `0008_m10_incidente`: tabela auxiliar `incidente` (§4.1 nota final:
    "incidente (sev1..3, kill/retomada 2 aprovadores)") — `launch`,
    `telemetry_event` e `lista_supressao` já constavam da `0001_core`.
  - Aceites `test_M10_A1`/`test_M10_A2` (+ contratos: armar exige apply ok e não
    re-arma launch ativo; kill 2 etapas com token errado não mata; rampa completa
    1→10→100 ⇒ concluído; webhook recusa assinatura inválida/PII/contato em claro
    sem gravar NADA) em `tests/acceptance/test_M10.py`.
- **Decisões (sem mudança de contrato do produto):**
  - `POST /webhooks/ens` (endpoint do §8-M10) entrou já na parte 1 como o GATILHO
    da avaliação automática dos breakers ("durante onda", A1/A2); extracts loader e
    reconciliação diária (A3), monitor (T13) e insight (T14/A4) ficam para a parte 2.
  - Breakers da política v1 (seed `POLITICA_PUBLICADA`, §11.4) ganham
    `erro_entrega_pct_max: 5.0` e `burn_rate_max: 1.5` ao lado dos existentes
    (`optout_pct_max: 0.6` — §8-M10-A1 — e `bounce_pct_max: 2.0`); a forma de
    `policy_versao.conteudo.breakers` é aberta (§4.1) e o M12 a governará. Limite
    ausente ⇒ breaker não avaliado.
  - Determinismo dos cálculos: taxas sobre os `sent` da JANELA (armar/última
    retomada — marco por id de telemetria em `launch.eventos`, imune a atraso de
    relógio); `erro_entrega` = (sent−delivered)/sent avaliado SÓ com telemetria de
    entrega presente (evita falso positivo por atraso do ENS); burn-rate = custo
    realizado (Σ sent×tarifa vigente) ÷ custo projetado do snapshot
    (`componentes.custo.previsto_p50`) pro-rata das ondas iniciadas.
  - Kill manual abre incidente sev2 (`kill_manual`) ⇒ retomada com 1 aprovação
    humana; só SEV1 (disparo p/ lista de supressão) exige 2 aprovadores distintos
    (§8-M10). Distinção por usuário autenticado (id), auditada em
    `incidente.meta.retomada.aprovadores` e `launch.eventos`.
  - `launch.eventos` (jsonb §4.1) é o histórico auditável da rampa: armado, ondas,
    disparos, kill 2 etapas, aprovações/retomadas e marcos de janela.
  - Novos tipos de evento (§2.3 define os MÍNIMOS; `launch.wave_advanced|
    breaker_tripped|killed` e `telemetry.ingested` já constavam): `launch.armado`,
    `launch.retomado`, `launch.concluido`, `incidente.aberto`.

## 2026-08-04 — M9 · fatia 2: Pré-voo & Drift (§5.4.5, §8-M9) — bateria + monitor + A4
- **Entrega (LLM PROIBIDO em todo o caminho — §5.4/§10.6; tudo determinístico):**
  - **Pré-voo** (`POST /preflight/{snapshot}?ambiente=`, router `api/v1/prevoo.py`,
    tag `compilador` — mesmo módulo M9): bateria de 8 itens pass/warn/fail COM
    evidência (§8-M9) — `des_schema` (DEs compiladas × estado real via SFMCPort;
    ausente=warn "criada no apply", schema divergente=fail), `frescor_hybris`
    (fixture do read model §11: D-1 ≤24h pass · ≤48h warn · >48h fail — §8-M5-A4),
    `opt_in` (re-checagem §5.3 dos `channel.*`), `listas_last_mile` (RE-VARREDURA das
    7 listas + opt-in via Guard determinístico §8-M5; resultado gravado em
    `certificado_elegibilidade.last_mile` §4.1), `lint_ampscript` (lint simples:
    `%%[ ]%%`/`%%= =%%` balanceados sobre células de criativos e assets),
    `limites_sfmc` (chave≤36, nome≤128, ≤200 activities/journey, ≤500 campos/DE —
    v1 em `domain/jornada/prevoo.py`), `drift_zero` (job on-demand restrito à OS) e
    `seed_dry_run` (seed SINTÉTICA validada contra o schema da DE de entrada —
    dry-run: nada é gravado; nunca PII §10.2). Semáforo: fail⇒vermelho,
    warn⇒amarelo. Persistência em `preflight_run` (migração `0007_preflight`) +
    evento `gate.passed|blocked` (portao=preflight §2.3).
  - **Gate no apply** (compilador_service): pré-voo VERMELHO bloqueia o apply em
    QUALQUER ambiente ("fail bloqueia apply" §8-M9); em PROD o pré-voo é
    OBRIGATÓRIO e não-vermelho (§5.4.4). Homolog sem pré-voo segue aplicável
    (fatia 1 intacta — aceites A1/A3 preservados).
  - **Drift** (`GET /drift?ambiente=&os_id=` — job on-demand §5.4.5; o job de 30min
    reusará o MESMO caso de uso `ServicoDrift.verificar`): para cada
    `resource_registry`, retrieve do estado real → decompila
    (`domain/jornada/drift.py`, código puro: projeção nos campos que o compilador
    emite) → compara por HASH (sha256 canônico) e por CAMPOS (diff
    `{campo: {twin, sfmc}}`) → grava `drift_check` (§4.1; DDL já na 0001). Estados:
    `em_sincronia` · `drift_sfmc` · `twin_a_frente` (sumiu do SFMC). Drift emite
    `drift.detected` (§2.3); **em PROD abre pendência automática BLOQUEANTE** na OS
    (A4) com dedupe por origem `drift:prod` — o avanço de fase trava (gate M1).
  - **Resolução** (`POST /drift/{id}/resolver`): `adopt` | `enforce` | `excecao` —
    excecao EXIGE prazo (`prazo_ate`, 422 sem ele); decisão em
    `drift_check.resolucao` + meta auditável (`diff.resolucao_meta` = {por, em,
    justificativa?, prazo_ate?}); sem drift pendente no ambiente ⇒ pendência
    automática resolvida (evento `pendencia.resolved`); re-resolver ⇒ 409.
  - Aceite `test_M9_A4` (drift injetado VIA `/chaos/drift` do mock in-process →
    pendência automática bloqueante) + contratos: resolver (prazo/dedupe/409),
    pré-voo vermelho bloqueia apply e prod exige pré-voo, bateria com evidência
    (warn antes do apply ⇒ amarelo NÃO bloqueia; verde depois do apply).
- **Emenda §4.1 (nota final):** lista de tabelas auxiliares ganha `preflight_run`
  (o §8-M9 exige "pre-flight verde" persistível como portão do apply; migração
  `0007_preflight`). `drift_check` NÃO precisou de migração (já estava na 0001).
- **Decisões (sem mudança de contrato do produto):**
  - "Pre-flight verde" (§5.4.4) lido à luz do §8-M9 ("fail bloqueia apply"): o gate
    aceita `verde|amarelo` (warns são registrados com evidência e não bloqueiam);
    `vermelho` bloqueia em qualquer ambiente; PROD exige pré-voo executado.
  - `GET /drift` é o disparo on-demand do job (§5.4.5 "job a cada 30min +
    on-demand") — não há endpoint novo fora do SDD; o agendador de 30min chega com
    a operação (M10) reusando `ServicoDrift.verificar`.
  - `enforce` NÃO re-aplica na hora: o caminho de reconvergência é o próprio
    plan/apply idempotente (§5.4.1-2 — re-plan marca `alterar`, apply recria);
    `adopt` pleno (decompilar → JGC) é o Adopt Wizard (nó `exception` §5.2), fora
    do v1 — ambos ficam REGISTRADOS com meta auditável.
  - `drift_check` não tem coluna de ambiente/prazo no DDL §4.1: ambiente, hashes,
    campos e `resolucao_meta` (incl. prazo da exceção) vivem no `diff` jsonb —
    evidência autocontida, sem migração.
  - Novo tipo de evento `drift.resolved` (§2.3 define os MÍNIMOS; padrão
    `pendencia.resolved`).

## 2026-08-04 — M9 · fatia 1: Compilador plan/apply (§5.4, §8-M9) — golden files + sync_run/registry
- **Entrega:** compilador determinístico (LLM PROIBIDO em todo o caminho — §5.4):
  - `domain/jornada/compilador.py` (código PURO): `compilar_recursos(grafo, hash)`
    resolve dependências na ordem §5.4.1 (DEs → EventDefs → Assets → Journey →
    Automations), externalKey idempotente `jrn-{hash[0:12]}-{noId}` (mesma função do
    preview M7), `corpo_soap_create` (XML do CreateRequest — espelha o template do
    adapter) e `GrafoNaoCompilavel` (nó `exception` §5.2 → 422, bloqueia publish).
  - `application/services/compilador_service.py`: `plan` consulta o estado real via
    SFMCPort e gera `{recurso, acao criar|alterar|manter|destruir, aviso}` (avisos
    destrutivos OBRIGATÓRIOS §5.4.3 — Event Source "reinicia contatos em espera",
    destruir DE); registros órfãos de snapshot anterior da MESMA OS viram `destruir`
    (ordem inversa de dependência). `apply` exige plan prévio (A1: 409), aprovação
    `aprovado|aprovado_ressalvas` não invalidada (a checagem de custo M8-A4 roda
    antes, lazy) e certificado VÁLIDO (M5-A3: expirado recusa); executa com tenacity
    (retry/backoff em `SfmcIndisponivel`, 3 tentativas §10.7), orçamento
    `SFMC_API_BUDGET_PER_APPLY` (§5.4.2) e IDEMPOTÊNCIA por externalKey (A3: estado
    real reconferido — existente e igual ⇒ `mantido`, 0 mutações); falha → rollback
    compensatório (destrói o que ESTA run criou, em ordem inversa; estado
    `revertido`, compensação incompleta ⇒ `parcial`). Tudo persistido em `sync_run`
    + `resource_registry` (§4.1 — dataclasses novas em domain/jornada/modelos.py,
    porta `application/ports/repositorio_sync.py`, memória em memoria.py; DDL já
    existia na migração 0001). Apply ok ⇒ `jornada_versao.estado='publicado'` +
    evento `sync.applied` (§2.3).
  - Rotas (`api/v1/compilador.py`, tag `compilador`): `POST /snapshots/{id}/plan
    ?ambiente=` · `POST /snapshots/{id}/apply?ambiente=` · `GET /sync-runs/{id}`.
    RBAC: mutações analista|lider. SFMC atrás de porta: `app.state.sfmc_port`
    (teste injeta `SfmcHttp` com `ASGITransport(mock)` — nenhum http real §1.3.5).
  - **Golden files (A2):** `tests/contract/golden/*.json|*.xml` congelam byte a byte
    os payloads REST (JSON ordenado) e SOAP (corpo do CreateRequest, sem envelope/
    token) do JGC de referência (OS-2026-0457, entrada agendada → cobre os 5 tipos);
    regeneração INTENCIONAL: `python -m tests.contract.util_golden` (+ emenda aqui).
  - Aceites `test_M9_A1..A3` + contratos (aprovação/certificado 409, rollback por
    orçamento, avisos destrutivos em novo hash) em `tests/acceptance/test_M9.py`.
- **Decisões (sem mudança de contrato do produto):**
  - **DataExtension usa o próprio `deRef` como externalKey** (não `jrn-{hash}-{noId}`):
    o JGC referencia DEs por nome (§5.2 `deRef`) e a DE SOBREVIVE a novas versões do
    grafo — hash novo troca eventDef/asset/journey (destruir+criar com aviso) mas
    mantém as DEs (`manter`), evitando destruição de dados a cada versão (§5.4.3).
  - Guardas de aprovação+certificado valem para os DOIS ambientes (o §8-M9 não
    qualifica ambiente; §5.4.4 segue valendo para prod). Pré-voo (`POST /preflight`)
    e drift (A4, `GET /drift`) ficam para a fatia 2 do M9 — quando existirem, o
    apply passará a exigir também pre-flight verde (§8-M9).
  - Orçamento vale para plan e apply (mesma variável §3.1); rollback desliga o
    orçamento (a compensação precisa concluir) e recursos DESTRUÍDOS pelo plano não
    são restauráveis — exatamente por isso o aviso destrutivo é obrigatório (§5.4.3).
  - Schema mínimo determinístico da DE (`SubscriberKey Text`): o JGC §5 não descreve
    schema de DE; o contrato pleno chega com o Adopt/decompile (drift, fatia 2).

## 2026-08-04 — mock-sfmc completo (§11.1) + SFMCPort/adapter — infraestrutura pré-M9
- **Entrega (sem compilador — §5.4 fica para o M9):**
  - `mocks/sfmc-server/main.py` deixa de ser stub M0: `POST /v2/token` (valida grant e
    credenciais mock), REST com validação de payload e estado em memória
    (`/rest/interaction/v1/eventDefinitions`, `/rest/interaction/v1/interactions`,
    `/rest/asset/v1/content/assets` — create/get/list/delete), SOAP simplificado
    (`POST /soap/Service.asmx`: Create/Retrieve/Delete de DataExtension e Automation,
    parsing por local-name, sem WSDL) e chaos `POST /chaos/rate-limit` (REST/SOAP → 429
    com Retry-After) e `POST /chaos/drift` (leituras devolvem recurso "editado fora do
    twin" — insumo do drift check §5.4.5/M9-A4).
  - Porta `application/ports/sfmc.py` (SFMCPort, §2.1) com erros tipados
    (`SfmcRateLimit`/`SfmcIndisponivel`/`SfmcRecusado`) e adapter
    `adapters/sfmc/cliente.py` (`SfmcHttp`): REST via httpx com **transport ASGI
    injetável** (teste fala com o mock IN-PROCESS — nenhum http real, §1.3.5) e SOAP
    por **template XML** (zeep §3.3 fica reservado ao adapter contra SFMC real; não é
    usado nem exigido em teste).
  - Unit: `tests/unit/test_mock_sfmc.py` (validação de payload REST/SOAP, auth, chaos)
    e `tests/unit/test_sfmc_adapter.py` (roundtrips + chaos vira exceção tipada), tudo
    via TestClient/ASGITransport in-process.
- **Decisões (sem mudança de contrato do produto — o mock é dublê de teste):**
  - Erros REST no formato SFMC `{message, errorcode}` (400 validação/duplicado 30003,
    401, 404, 429 com errorcode 50200); SOAP com `StatusCode Error` + `ErrorCode`
    (10006 validação, 310007 duplicado) e `soap:Fault` para XML/token/ação inválidos.
  - `create_app()` no mock → estado POR INSTÂNCIA (testes nascem limpos);
    `POST /chaos/reset` adicionado como higiene de teste (não faz parte do §11.1, é
    interno ao dublê). Estado nunca é mutado pelo drift — só a LEITURA é adulterada.
  - Deletes (REST e SOAP) já entregues porque o rollback compensatório e os avisos
    destrutivos do apply (§5.4.2–3) vão precisar deles no M9.
  - Retry/backoff (tenacity) e orçamento `SFMC_API_BUDGET_PER_APPLY` NÃO estão no
    adapter: são responsabilidade do compilador (§5.4.2); o adapter só traduz 429/5xx
    em exceções tipadas. LLM proibido em todo este caminho (§5.4) — 100% determinístico.

## 2026-08-04 — M7 · Twin Canvas T7 (§5, §8-M7) — fatia de API entregue na auditoria MS4
- **Contexto:** o domínio do M7 já existia (`domain/jornada/`: `jgc.schema.json` §5,
  `validacao.py` §5.3, `canonico.py` hash RFC-8785-like, `taximetro.py` A2,
  `sfmc_preview.py`; `agents/flow.py` + `agents/skills/flow.skill.md`; porta
  `RepositorioJornada`), mas rotas, serviço, aceites e esta entrada de CHANGELOG não
  haviam sido entregues (a nota do M8 parte 1 "rotas do M7 ainda não existem" registrou
  o buraco). A auditoria MS4 completa a fatia.
- **Entrega:** `application/services/jornada_service.py` (ServicoJornada) e router
  `api/v1/jornada.py` (tag `jornada`: `POST /os/{id}/jornada/gerar` ·
  `PUT /jornadas/{id}/grafo` · `POST /jornadas/{id}/ajustar` ·
  `GET /jornadas/{id}/no/{noId}/sfmc-preview`) + aceites `test_M7_A1..A3` (e contratos
  de ajustar/preview/degradado). SEM migração nova: `jornada_versao` já está na
  `0001_core` (§4.1) e as colunas de simulação vieram na `0005` (emenda M8).
- **Decisões (sem mudança de contrato):**
  - Guarda-corpos (§1.3.5): `meta.osCodigo`/`meta.tenant` SEMPRE reescritos com os
    valores da OS (escopo nunca vem do LLM/cliente); grafo do flow passa por
    `jgc_validate` (§5.3) e taxímetro ANTES de persistir — proposta inválida → 422
    com `erros[{no, regra, mensagem}]` (A1/A3), nada é salvo.
  - Taxímetro (A2): volume de entrada = `contagem_liquida` do último segmento
    recontado (M5); OS sem segmento → volume 0 + AVISO (nunca inventa). Resposta
    carrega a memória de cálculo por nó (volume, tarifa, custo em Decimal→str).
  - `PUT /grafo`: só estados editáveis (`rascunho`/`simulado`; senão 409); editar
    recalcula hash+taxímetro e INVALIDA `simulacao`/`previsto` da versão (estado →
    `rascunho`): a régua congelada que vale é a do snapshot (§1.1.2). Caminho 100%
    determinístico — jamais depende de LLM (§10.6); gerar/ajustar com hub fora → 503
    degraded.
  - `ajustar`: devolve `grafo_proposto` + diff estrutural (nodes/edges adicionados/
    removidos/alterados + meta) + validade/custo projetado — `aplicado=false` SEMPRE;
    aplicar é PUT humano do grafo proposto (Aplicar/Rejeitar §1.1.3).
  - Schema §5.2: `entrySource.data.reentrada` fica OPCIONAL no `jgc.schema.json`
    (o exemplo §5.1 não o traz; `meta.reentrada` é obrigatório e `reentrada_efetiva`
    dá precedência ao entrySource quando presente) — tabela §5.2 lida à luz do §5.1.
  - Ledger `invocacao` via_ai + `agent.invoked` + trace Langfuse (padrão M3/M5/M6);
    novos tipos de evento (§2.3 define os mínimos): `jornada.versao_criada`,
    `jornada.grafo_atualizado`.

## 2026-08-04 — M8 (parte 2) · Portões T9 + Aprovação T10 (§8-M8, §4.1)
- **Entrega:** `domain/governanca/` ganha `modelos.py` (Snapshot/Aprovacao 1:1 com o
  §4.1), `snapshot.py` (hash COMPOSTO sha256 — canonicalização do JGC reutilizada —
  sobre exatamente {jgc, sql, criativos, politica, custo, experimento}), `erros.py`
  (LinkExpirado→410, TokenInvalido→404, demais 409/422) e `faixa_alcada()` em
  `politicas.py`; `domain/experimento/poder.py` (n mínimo por braço para o MDE — duas
  proporções, α=0,05, poder 0,80: MESMAS premissas do `_poder` do motor §6);
  `application/services/aprovacao_service.py` (ServicoPortoes + ServicoAprovacao),
  porta `RepositorioAprovacao`, router `api/v1/portoes.py` (tags `portoes` e
  `aprovacao`: `GET /os/{id}/portoes` · `POST /experimentos` ·
  `POST /os/{id}/custo/enviar-alcada` · `POST /snapshots` ·
  `POST /snapshots/{id}/link-magico` · `GET /aprovacao/{token}` ·
  `POST /aprovacao/{token}/decidir`), migração `0006_aprovacao_invalidada`, aceites
  `test_M8_A3`/`test_M8_A4` (+ contratos de portões/experimento/snapshot).
- **Emenda §4.1:** `aprovacao` ganha `invalidada_em timestamptz` e `invalidada_motivo
  text`. O aceite A4 (variação de custo >10% após aprovação invalida a aprovação —
  snapshot novo obrigatório) precisa registrar a invalidação SEM apagar a decisão
  histórica (`decisao/decidido_em` preservados — event sourcing §4.1).
- **Decisões (sem mudança de contrato):**
  - Link mágico: token `secrets.token_urlsafe(32)` retornado UMA única vez; persiste
    só o sha256 (`token_hash` §4.1); URL = `{WEB_BASE_URL}/aprovacao/{token}` (rota
    standalone §12). Rotas `/aprovacao/{token}*` NÃO exigem Bearer — o token é a
    credencial (mesmo racional do portal §8-M3); X-Tenant segue obrigatório (§8) e
    tenant errado responde 404 sem vazar existência. Validade default 72h
    (`validade_horas` 1–720 no `link-magico`); uso único = decisão registrada (A3).
  - Ressalvas (A3): cada ressalva vira pendência automática bloqueante (tipo `issue`,
    severidade `media`, origem `aprovacao:{id}`) + evento `pendencia.opened`;
    `aprovado|aprovado_ressalvas` marca a versão do twin como `aprovado` (§4.1).
  - Invalidação A4: verificação determinística lazy (no `GET /os/{id}/portoes` e nas
    rotas de `/aprovacao/*`) comparando o custo P50 corrente (última simulação) com o
    custo congelado no snapshot aprovado; >10% ⇒ `invalidada_*` + evento
    `aprovacao.invalidada`. O M9 (`apply`) deve exigir aprovação NÃO invalidada.
  - Portões T9: `certificado` (expirado ⇒ vermelho — M5-A3), `experimento` (poder da
    última simulação — A2), `custo_alcada` (faixas `alcadas` §11.4; envio registrado
    como evento `custo.enviado_alcada`; custo variou >10% desde o envio ⇒ reenviar),
    `governor` STUB (colisão da pressão de contato da simulação §6; árbitro
    cross-campanha pleno chega no M10). Estados: verde/vermelho/pendente.
  - `POST /experimentos`: `n_minimo` é SEMPRE calculado no servidor (nunca input);
    pré-registro nasce travado (`travado_em`) — anti-p-hacking; holdout abaixo do
    `holdout_min` da política → 422. `POST /snapshots` idêntico (mesmo hash) → 409
    (pacote imutável §1.1.1); snapshot exige simulação + previsto congelado (409).

## 2026-08-04 — M8 (parte 1) · Simulador T8 / Ensaio Geral (§6, §8-M8)
- **Entrega:** `domain/simulacao/` (motor Monte Carlo PURO — `motor.py`; personas de
  agregados — `personas.py`; priors default v1 — `priors.py`; `tipos.py` com o Protocol
  `GeradorAleatorio`; erros 409), `application/services/simulador_service.py`
  (ServicoSimulador) + `persona_service.py` (ServicoPersona), portas `RngPort`
  (`application/ports/rng.py` — fábrica `gerador(seed)`) e `ClockPort` injetáveis
  (§2.1), adapter `adapters/aleatorio.py` (numpy vetorizado quando instalado, stdlib
  pura senão — §6 NFR), router `api/v1/simulador.py` (tag `simulador`:
  `POST /jornadas/{id}/simular` · `POST /jornadas/{id}/congelar-previsto` ·
  `POST /simulacoes/comparar`), migração `0005_simulacao`, aceites
  `test_M8_A1`/`test_M8_A2` (+ contratos de congelar/comparar/422).
- **Emenda §4.1:** `jornada_versao` ganha colunas `simulacao jsonb` (saída §6: funil
  por nó, P10/P50/P90 de conversões/custo/receita/ROAS, lift + poder, pressão de
  contato, gargalos, semáforo) e `previsto jsonb` (Previsto congelado da versão —
  copiado para `snapshot.previsto` no M8 parte 2). O §6 já mandava persistir "em
  jornada_versao"; o DDL original não tinha onde.
- **Emenda §6 (precedência do semáforo):** o §6 original listava "poder insuficiente"
  como causa de VERMELHO, mas o aceite §8-M8-A2 (que prevalece por ser o critério
  verificável) exige: poder insuficiente ⇒ portão de experimento VERMELHO e simulação
  AMARELA. Regra final: vermelho = ROAS P50 < 1 ou colisão crítica do governor;
  amarelo = poder insuficiente ou avisos (custo > verba); verde senão. Vermelho segue
  bloqueando T9/T11 (`gate.blocked`).
- **Decisões (sem mudança de contrato):**
  - Determinismo (A1): uma única sequência `RngPort.gerador(seed)` alimenta personas e
    os K runs; `numpy` e stdlib são AMBOS reprodutíveis por seed, mas não geram a mesma
    série entre si — A1 vale dentro de uma instalação. Testes trocam via
    `app.state.rng` (mesmo padrão de `app.state.llm`).
  - Priors §6: enquanto `calibracao_prior` não tem versão publicada (M11), vale
    `PRIORS_DEFAULT` v1 em código; tarifário e política publicada idem (seeds §11.4 em
    `domain/custo/tarifas.py` e `domain/governanca/politicas.py` até M11/M12).
  - Poder estatístico: teste de duas proporções (aproximação normal, α=0,05 bilateral)
    para o MDE pré-registrado; portão vermelho se `n_disponivel < n_minimo` OU
    poder < 0,8.
  - LGPD §6: `PersonaService` entrega só COORTES agregadas (mix de classes do governor
    + distribuição de horários) — nenhum registro individual em log/saída.
  - Zero LLM no caminho (§10.6): simulador é 100% determinístico; o agente `simulate`
    (§7.2) só narra — fica para o M8 parte 2/T8 UI.
  - Rotas do M7 ainda não existem: os aceites M8 semeiam `jornada_versao`/segmento/
    experimento direto no repositório em memória (`app.state.repositorio_os`).

## 2026-08-04 — M6 · Criativo (T6)
- **Entrega:** `domain/criativo/` (modelos espelhando a tabela auxiliar `criativo`
  §4.1 nota final — matriz canal×variante, estado por célula, kv_master_ref; regras
  puras em `matriz.py`; validadores DETERMINÍSTICOS em `validadores.py`; erros
  herdando o mapa HTTP do M1), migração `0003_criativo`, agentes do T6
  (`agents/skills/{visual,copy,content}.skill.md` §7.1 + `agents/criativo.py` —
  pipeline visual→copy→content, perfil 120b), `application/services/criativo_service.py`,
  rotas em `api/v1/criativo.py` (`POST /os/{id}/criativos/gerar`,
  `PATCH /criativos/{id}/celula`, `PUT /criativos/{id}/kv-master` — tag `criativo`)
  e aceites `test_M6_A1..A3`.
- **Notas de implementação (sem mudança de contrato):**
  - Validadores (§8-M6 "regras + LLM warn"): o VETO é 100% código — SMS≤160 (A1),
    template WhatsApp com status `aprovado`, termos proibidos de linguagem (lista v1
    em `validadores.py`; a política editorial do tenant poderá estendê-la via
    `policy_versao` no M12) → `CriativoInvalido` 422 com `problemas`. O LLM 20b só
    ACRESCENTA `avisos` não bloqueantes (hub fora → avisos vazios; geração exige LLM
    e responde 503 degraded §10.6, mas PATCH célula e PUT kv-master nunca dependem).
  - Guarda-corpos da saída do content (§1.3.5): JSON malformado/sem célula → 422
    (`SaidaDoCriativoInvalida`, nada é inventado); células fora dos canais×variantes
    pedidos são descartadas; ESTADO nunca vem do LLM — toda célula nasce `gerado` e
    `aprovado` é ato humano analista+ (A3: RBAC na rota + `AprovacaoRequerHumano` 403
    no domínio). Edição do KV master derruba aprovações: todas as células →
    `adaptado_revisar` (A2). `PUT /criativos/{id}/kv-master` materializa a edição do
    KV do §8-M6-A2 (endpoint da fatia — mesmo padrão dos demais do módulo).
  - Ledger via_ai (§4.1): uma `invocacao` por chamada de LLM (3 do pipeline + 1 do
    warn) com trace Langfuse (§10.8); novos tipos de evento (§2.3 define os mínimos):
    `criativo.gerado`, `criativo.celula_alterada`, `criativo.kv_master_editado`.

## 2026-08-04 — M5 · Audiência (T5) + Guard determinístico + Data Cloud (T5a)
- **Entrega:** `domain/audiencia/` (modelos espelhando `segmento`,
  `certificado_elegibilidade` e `dc_segment_cache` §4.1; regras puras em `waterfall.py`
  — waterfall, volume de abordagem, holdout, frescor; erros herdando o mapa HTTP do M1),
  **Guard determinístico** em `agents/guard/elegibilidade.py` (código puro, ZERO LLM:
  valida as 7 listas + opt-in no WHERE do SQL público e emite
  `certificado_elegibilidade` com hash sha256 canônico e validade; helpers
  `certificado_vigente`/`exigir_certificado_vigente` prontos para o publish M8/M9 — A3),
  agente engineer (`agents/skills/engineer.skill.md` §7.1 + `agents/engineer.py`),
  portas `DataCloudPort`/`ReadModelAudienciaPort`/`RepositorioAudiencia`, adapters
  `adapters/datacloud/{fixtures,cliente}.py` e `adapters/fontes/read_model.py`,
  `application/services/audiencia_service.py`, rotas em `api/v1/audiencia.py`
  (`POST /os/{id}/segmento/gerar-sql`, `POST /segmentos/{id}/recontar`,
  `PUT /segmentos/{id}/holdout`, `POST /segmentos/{id}/certificar` — tag `audiencia`)
  e `api/v1/datacloud.py` (`GET /datacloud/segmentos`, `GET .../{id}/relatorio`,
  `GET .../{id}/relatorio.docx`, `POST .../{id}/usar` — tag `datacloud`), mock-datacloud
  completado (§11.2: token + segments + query count + report), seeds
  `mocks/seeds/{datacloud_segmentos,read_model_audiencia}.json` e aceites
  `test_M5_A1..A4`. Tabelas do M5 já constavam da migração `0001_core`.
- **Notas de implementação (sem mudança de contrato):**
  - Guard (§7.2 "deterministico=true"): veredito por CÓDIGO — varredura textual do
    WHERE (case-insensitive) exige as 7 listas E checagem de opt-in; reprova →
    `CertificadoReprovado` (422 problem+json com `listas_faltantes`/`problemas`) +
    evento `gate.blocked`; aprova → certificado + `gate.passed`/`certificado.emitido`.
    Validade do certificado = 24h (ciclo D-1 do Hybris §11/A4); `last_mile` fica nulo
    até a re-varredura no disparo (M9/M10). Caminho crítico sem LLM comprovado por
    teste (hub indisponível → certificar segue 201; gerar-sql → 503 degraded §10.6).
  - Engineer: prévia via_ai (§1.1.3) com guarda-corpos determinísticos — SQL sem
    evidências (`exige_evidencia: true`) é descartado; JSON malformado degrada sem SQL
    (`SaidaDoEngineerInvalida` → 422); pré-check do Guard vira `avisos` na resposta
    (a reprovação dura é na certificação). Ledger `invocacao` + `agent.invoked` +
    trace Langfuse (span `generate`) como no M3. Parser de SKILL.md reusado de
    `agents/consultor.py` (o parser pleno continua adiado ao Ateliê/M12).
  - Recontagem é DRY-RUN no read model de ativação atrás de porta (fixtures §11 em
    dev/teste — `mocks/seeds/read_model_audiencia.json`); waterfall na ordem de
    precedência da política (7 listas) + corte `sem_opt_in`; volume de abordagem por
    canal = opt-in − cap excedente − impactados por quiet hours − colisões (governor),
    saturado em [0, líquido]; pct calculado SOBRE o líquido (A2). Frescor por fonte
    relativo nas fixtures (`atualizado_ha_horas`; Hybris D-1 = 24h) vira timestamp
    absoluto `{fonte: ultima_atualizacao}` (§4.1) na resposta (A4).
  - Data Cloud (T5a — consulta, não cópia): `DataCloudFixtures` (dev/teste, nenhuma
    rede) e `DataCloudHttp` (compose/prod via `app.state.datacloud`) leem a MESMA
    fixture do mock-datacloud (`mocks/seeds/datacloud_segmentos.json`, 4 segmentos);
    toda consulta faz upsert de `dc_segment_cache` com frescor (`republicado_em` +
    `atualizado_em`). `usar` cria `segmento` origem data_cloud com lineage
    (`dc_segment_id`, critérios, contagens/waterfall/frescor da consulta) e exige
    `os_id` no corpo (a tabela `segmento` referencia `os`). `relatorio.docx` gerado
    deterministicamente (novo método `relatorio_segmento` na GeradorDocumentoPort).
  - Holdout: `PUT /segmentos/{id}/holdout` valida contra `holdout_min` da política
    publicada (§11.4: 10%) — abaixo do mínimo → 422 `HoldoutForaDaPolitica`; default
    do segmento nasce do `holdout_min` vigente (≥ default 10.0 do DDL §4.1).
  - Novos tipos de evento (§2.3 define os MÍNIMOS): `segmento.recontado`,
    `segmento.holdout_definido`, `certificado.emitido`, `datacloud.segmento_usado`.
  - RAG pgvector (bases `dicionario_dados`/`historico_campanhas` do engineer) continua
    adiado: exige Postgres real; as evidências citadas seguem textuais no ledger, como
    registrado no M3. `RepositorioOsMemoria` passa a implementar também
    `RepositorioAudiencia` (mesma instância por app — tipagem estrutural §2.1).

## 2026-08-04 — M4 · Validação campo-a-campo & War Room (T3/T4)
- **Entrega:** `domain/validacao/` (modelos das tabelas auxiliares `validacao_campo`,
  `os_thread` e `documento_portao` — §4.1 nota final; regras puras do portão GO e do
  congelamento de SLAs em `regras.py`; `GoBloqueado` 409 com listas no corpo),
  migração `0004_m4_validacao`, porta `FonteValidacaoPort` + adapter
  `adapters/fontes/fixtures.py` (fixtures `mocks/seeds/fontes_validacao.json` §11),
  `PublicacoesPort` + `adapters/publicacoes.py` (versões publicadas p/ o frozen),
  `GeradorDocumentoPort` + `adapters/documentos/docx_portao.py` (python-docx §3.2),
  `application/services/validacao_service.py`, rotas em `api/v1/validacao.py`
  (`POST /os/{id}/validacoes/{campo}`, `POST .../validacoes/{campo}/pendencia`,
  `POST /os/{id}/threads`, `POST /os/{id}/go` — tag `validacao`) e aceites
  `test_M4_A1..A3`.
- **Notas de implementação (sem mudança de contrato):**
  - Checagem automática (§8-M4) determinística contra fonte atrás de porta: contagem,
    schema e frescor (relativo nas fixtures — `atualizado_ha_horas`; Hybris D-1=24h
    §8-M5-A4) com evidência persistida; campo sem fonte configurada → veredito
    `falha`. Campo inexistente no briefing → 404 (`CampoForaDoBriefing`) — vale para
    validação, pendência ancorada e thread do War Room.
  - "Campo decidido" (portão GO): última validação `ok` OU tratamento consciente
    (existe pendência ancorada `origem=validacao:{campo}` e nenhuma segue aberta).
    GO bloqueado (A1) → 409 problem+json com `campos_nao_decididos` + `pendencias`
    + evento `gate.blocked`; GO só parte de `discutida` (§8-M4: fase→criada).
  - Frozen (A2, §4.1): `{agent_versions, policy_version, tarifario_id, slas,
    congelado_em}` — versões de agentes lidas dos SKILL.md publicados (fonte da
    verdade até o Ateliê/M12), política v1 do seed, tarifário `tarifario-2026-v1`.
    SLAs congelados com prazos CUMULATIVOS pela ordem canônica da esteira (defaults
    de implementação em `regras.SLA_DIAS_PADRAO`; `etapa_workflow.sla_dias` da OS
    prevalece) e materializados como `sla_clock` correndo.
  - Doc executivo (A3): .docx determinístico em memória (BytesIO), bytes + sha256 em
    `documento_portao`; evento `documento_portao.gerado`. Novos tipos de evento
    (§2.3): `validacao.executada`, `thread.aberta`, `documento_portao.gerado`.

## 2026-08-04 — M3 · Intake & Consultor (T2 + Portal do Solicitante)
- **Entrega:** `domain/intake/` (modelos espelhando `pedido` §4.1; `completude.py` —
  cálculo DETERMINÍSTICO de completude/faltantes sobre os 5 campos obrigatórios
  objetivo/publico/oferta/verba/janela; erros herdando o mapa HTTP do M1),
  `domain/agentes/modelos.py` (linha do ledger `invocacao` §4.1),
  `application/ports/repositorio_intake.py` e `application/ports/observabilidade.py`
  (TracerPort §10.8), `adapters/observabilidade/langfuse.py` (fire-and-forget),
  agente consultor (`agents/skills/consultor.skill.md` §7.1 + `agents/consultor.py`),
  `application/services/consultor_service.py`, rotas em `api/v1/intake.py`
  (`POST /pedidos`, `POST /pedidos/{id}/mensagem`, `POST /pedidos/{id}/converter`,
  `GET /os/{id}/briefing`, `PATCH /os/{id}/briefing/{campo}` — tag `intake`) e aceites
  `test_M3_A1..A3`. Tabelas `pedido`/`invocacao` já constavam da migração `0001_core`.
- **Notas de implementação (sem mudança de contrato):**
  - `pedido.conteudo` é jsonb `{campo: {valor, inferido, evidencias?}}`: entrada direta
    do solicitante nasce `inferido:false`; inferência do consultor nasce `inferido:true`
    + `evidencias` (A3) e o briefing da OS herda isso na conversão até confirmação humana
    (PATCH confirma/edita → `inferido:false`). Completude (numeric 4,1) = 100×presentes/5,
    recalculada por código após TODA mutação — o LLM nunca escreve completude/faltantes.
  - Guarda-corpos determinísticos da saída do LLM (`agents/consultor.py`): só campos
    obrigatórios são aceitos como inferência (§1.3.5 — nunca campo fora do SDD);
    `exige_evidencia: true` na skill → inferência sem evidência é descartada (A3 por
    construção); JSON malformado degrada para resposta textual sem inferências.
  - Portal (§8-M3 "via link com token, sem login pleno"): token de portal dev
    `portal-dev` (`app/auth.py::get_portador`), válido só nas rotas de intake que o
    declaram; converter e PATCH briefing exigem login pleno analista|lider; prod trocará
    por link mágico assinado (APP_SECRET) sem mudar assinaturas.
  - PII (§1.3.5/§10.2): o prompt do consultor recebe conteúdo/faltantes/mensagem — o
    bloco `solicitante` do pedido JAMAIS entra em prompt (testado em unit e aceite).
  - Ledger `invocacao` (§4.1): enquanto a tabela `agente` não tem linhas (Ateliê M12),
    `agente_id` = uuid5 determinístico do nome canônico; `evidencias` guarda os
    precedentes textuais citados (ids de chunks RAG chegam com o RAG no M5); `tokens`
    fica nulo (o LLMPort v1 devolve só texto). Evento `agent.invoked` (§2.3) com
    `via_ai=true` por conversa; novos tipos de evento: `pedido.convertido`,
    `briefing.campo_atualizado`.
  - Langfuse (§10.8): `TracerLangfuse` — `LANGFUSE_ENABLED=false` → no-op absoluto (modo
    de TODO teste, injetado no conftest); habilitado, envia em thread daemon com exceções
    engolidas (trace_id = invocacao.id; span `generate` no M3 — `rag_retrieve`/`judge`
    chegam com RAG/judge). LLM indisponível (§10.6) → rota de mensagem responde 503
    problem+json com `modo: degraded`; criação/conversão de pedido seguem sem LLM.
  - Conteúdo do briefing além dos 5 obrigatórios é aceito e preservado (jsonb livre —
    os "14 campos" do §4.1 não são enumerados pelo SDD); campos extras não pontuam na
    completude. `POST /pedidos/{id}/converter` aceita `nome`/`tshirt` opcionais para a
    OS (default: objetivo do briefing / "M") — a OS exige esses atributos (§4.1) e o
    pedido não os carrega.

## 2026-08-04 — M2 · Esteira de Produção ex-Hike (T4a) + Hike import
- **Entrega:** `domain/esteira/` (modelos espelhando `etapa_workflow` §4.1, regras em
  `workflow.py`, erros herdando o mapa HTTP de `domain/campanha/erros.py`),
  `application/ports/repositorio_workflow.py`, `application/services/workflow_service.py`,
  rotas em `api/v1/esteira.py` (`GET/PATCH /os/{id}/workflow`, `POST /admin/hike/import` —
  tag `esteira`), migração `0002_hike_import_log` (tabela auxiliar, §4.1 nota final),
  fixture `mocks/seeds/hike_export.json` (3 cards — §11.4) e aceites `test_M2_A1..A3`.
- **Notas de implementação (sem mudança de contrato):**
  - Conteúdo dos checklists padrão (o SDD fixa as quantidades, não os textos): Criativos
    nasce com 4 subtarefas alinhadas ao fluxo do M6/T6 — "KV master definido",
    "Matriz canal×variante gerada", "Compliance de linguagem validado", "Células aprovadas";
    Acompanhamento nasce com "Checkpoint D+1/D+7/D+15". Constantes em
    `domain/esteira/modelos.py`.
  - Dependência default da esteira é linear (etapa N depende da N-1 concluída; briefing
    livre) — semântica do quadro ex-Hike; `dependencias` jsonb segue livre para arranjos
    por OS. `em_andamento` exige dependências concluídas (A2 → 409, `DependenciaInsatisfeita`
    herda de `EstadoInvalido` para reusar o mapa RFC-7807 do M1).
  - Etapas são materializadas lazy na primeira consulta do workflow da OS (não altera o
    `POST /os` do M1); import Hike cria as 7 etapas explicitamente com `hike_ref`
    `{card_id, importado_em, url_arquivada}` e estados/checklist como vieram do Hike
    (import é histórico — sem validação de transição).
  - Histórico preservado (A3): `por/em` originais no checklist + evento de outbox
    `hike.card_imported` com o `historico` integral do card (§2.3 define tipos MÍNIMOS;
    acrescentados `hike.card_imported` e `workflow.etapa_estado_alterado`). Import é
    idempotente por `card_id` (re-import → status `duplicado`, também logado em
    `hike_import_log`). Log com status ok|duplicado|erro.
  - `RepositorioOsMemoria` passa a implementar também a porta `RepositorioWorkflow`
    (mesma instância por app — tipagem estrutural; adapter Postgres continua adiado).
- **LLMPort antecipada (§2.1/§3, exigência de guarda-corpo §1.3.5):** criada
  `application/ports/llm.py` (perfis 120b|20b, `LLMIndisponivel`), adapter REAL
  `adapters/llm/hubgpu.py` (client `openai` com base_url do HubGPU, lazy, atrás de
  `LLM_DEGRADED_MODE` — `forced_off` levanta `LLMIndisponivel` sem rede, §10.6) e adapter
  FAKE `adapters/llm/fake.py` (único permitido em teste). Nenhuma rota do M2 invoca LLM;
  o hub real jamais é chamado em teste (`tests/unit/test_llm_port.py`).

## 2026-08-04 — M1 · Rotas do Núcleo OS/governança + gate de cobertura ampliado
- **Entrega (punch list da auditoria):** `backend/api/v1/os_governanca.py` materializa os
  endpoints do §8-M1 (`POST/GET /os`, `GET /os/{id}`, `POST /os/{id}/fase`,
  `POST /os/{id}/pendencias`, `POST /pendencias/{id}/resolver|aceitar`,
  `GET /os/{id}/saude`) sobre o `ServicoOs` existente; router registrado em
  `backend/api/v1/__init__.py` (tag OpenAPI `os`). Aceites `test_M1_A1..A3` em
  `backend/tests/acceptance/test_M1.py` (IDs = SDD §1.3.4).
- **Notas de implementação (sem mudança de contrato):**
  - Erros de domínio → problem+json traduzidos por `route_class` do próprio router
    (`RotaComErrosDeDominio`), mantendo o mapa onde `domain/campanha/erros.py` documenta
    (404/403/422/409); `AvancoBloqueadoPorPendencia` (409, A1) inclui `pendencias` no corpo.
  - RBAC: escrita exige `analista|lider` (admin passa — §8-M0); aceite de pendência aceita
    qualquer autenticado e o domínio exige o `accountable` + justificativa (A2, §10.5).
  - Persistência: `RepositorioOsMemoria` por app (`app.state.repositorio_os`), lazy; troca
    pelo adapter Postgres fica isolada em `get_repositorio_os` (hexagonal §2.1).
  - `test_M0_A2_com_header_passa_do_middleware` ajustado: com a rota `GET /os` existente,
    passar do middleware evidencia-se por 401 (Bearer ausente), não mais 404.
- **CI (§13):** gate de cobertura passa a medir também o núcleo —
  `--cov=app --cov=api --cov=domain --cov=application` (medir só app/api mascarava
  domain/application). `pyproject.toml` ganha `[tool.coverage.report].exclude_also` para
  stubs `...` de Protocols (ports §2.1) e blocos `TYPE_CHECKING` (código não executável).

## 2026-08-04 — Adoção do Langfuse self-hosted como observabilidade de LLM (§10.8)
- **Motivo:** necessidade de lente operacional sobre toda chamada LLM/Embedding (custo de IA
  por OS, latência por agente, taxa de retry/judge-fail) sem depender de SaaS externo e sem
  substituir o ledger `invocacao` (`via_ai`), que permanece a fonte de auditoria LGPD (Art. 20).
- **Impacto:**
  - `docker-compose.yml` ganha os serviços `langfuse` (imagem `langfuse/langfuse:2`) e
    `db-langfuse` (Postgres próprio, isolado do banco da aplicação).
  - `.env.example` ganha o bloco `LANGFUSE_HOST/PUBLIC_KEY/SECRET_KEY/ENABLED` (§3.1);
    `LANGFUSE_ENABLED=false` → no-op (a aplicação nunca depende do Langfuse).
  - `requirements.txt` inclui `langfuse~=2.53` (§3.2).
  - Contrato de instrumentação (§10.8): trace por invocação com `trace_id = invocacao.id`,
    spans `rag_retrieve` → `generate` → `judge`, envio assíncrono fire-and-forget; harness
    runs traceados com tag `harness`. Implementação do adapter ocorre junto ao `LLMPort` (M5+).

## 2026-08-04 — M0 · Emenda §4.1: ordem da view `os_saude` no DDL
- **Motivo:** no DDL original a view `os_saude` era declarada antes das tabelas `sla_clock` e
  `pendencia`, que ela referencia — a execução top-down da migração `0001_core` falharia.
- **Impacto:** bloco `create view os_saude` movido no §4.1 para depois de `pendencia`.
  Nenhuma mudança semântica (mesmas colunas/regra de saúde). Migração `0001_core` segue a
  nova ordem.

## 2026-08-04 — M0 · Notas de implementação (sem mudança de contrato)
- `.env.example` e `requirements.txt` materializados "um item por linha" (o §3.1/§3.2 compacta
  linhas por legibilidade; o próprio §3.2 indica o formato real).
- Aceite `test_M0_A1` roda via `TestClient` **sem docker**: o ping de banco do `/healthz` é
  substituído por dublê via `dependency_overrides` para simular a pré-condição "compose up"
  (db saudável). A validação real com `docker compose up` permanece no DoD do MS1 (§9) e no
  job de e2e do CI (a ativar no MS8 §13). Máquina de dev atual possui docker; a limitação é
  apenas do modo de execução dos testes unit/aceite.
- Serviço `web` do compose (§2.2/§8-M0) deixado comentado até o frontend existir (MS3+, §9) —
  compose precisa subir verde no MS1 sem build de frontend.
- CI (§13): jobs de build do front e e2e compose ficam condicionados/pendentes até MS3/MS8;
  ruff + mypy + pytest (cobertura ≥ 80%) ativos desde o M0. `pytest-cov` instalado só no CI
  (não consta do §3.2).

## 2026-08-05 · Validação HubGPU real + Langfuse (pós-vMS8)
- **HubGPU validado**: 120B (flow gerou JGC válido de 14 nós em 35s pelo caminho de produção; consultor extraiu briefing com completude 80% e faltante exato), 20B (200 OK) e embeddings Qwen3 (dim=1024 confirmado). Achado: reasoning do gpt-oss consome completion tokens — adapter lê só `content`, sem `max_tokens` baixo.
- **fix(m7)**: retry §7.3 no flow com feedback do jgc_validate (commit 86c95f3) — transformou a reprova real do 120B em geração válida.
- **fix(adapter hubgpu)**: `APITimeoutError`/`APIConnectionError` → `LLMIndisponivel` (503 degraded §10.6), nunca 500.
- **Langfuse §10.8 validado no self-hosted 2.95** (compose): trace com `trace_id = invocacao.id`, spans rag_retrieve/generate/judge, metadados de agente — via TracerLangfuse de produção. Nota: SDK deve seguir o pin `langfuse~=2.53` do requirements (v4 usa OTel, incompatível com servidor v2; venv local estava desalinhado).
- **Ambiente dev desta máquina**: docker-compose.override.yml LOCAL (gitignorado) com portas 18080/13000 por conflito com o projeto `agente_*` + restart unless-stopped (containers do projeto sofreram kill externo 255 duas vezes).
- Hub oscilou durante os testes (ConnectTimeout após 20 min funcionando) — instabilidade de rede/VPN, não do código; caminho degradado agora responde 503.

## 2026-08-05 · Melhoria UI (pós-vMS8): rebrand Jornada + "dinâmico"
- Marca **Martech → Jornada** em toda a aplicação (topbar, cockpit, portal de aprovação, título da aba: "Jornada · Digital Twin de Campanhas").
- Termo **"vivo" → "dinâmico"** com concordância (Monitoramento Dinâmico, modo Dinâmico do canvas, recontagem/telemetria/ata dinâmica, SQL/catálogo dinâmico); id interno do modo `aovivo` → `dinamico`. 24 substituições; verificação visual no dev server + build verde.

## 2026-08-05 · Evoluções do demo público (pós-deploy)
- **Deploy automático**: job `deploy` no ci.yml — push na main com os 3 gates verdes → SSH na VPS (chave dedicada em secret) → git reset + compose up --build + smoke. Concurrency `deploy-vps`.
- **Langfuse na VPS**: serviços langfuse+db-langfuse no docker-compose.prod.yml; api com LANGFUSE_ENABLED=true (trace por invocação §10.8); UI pública em :13000 com signup desabilitado e credenciais provisionadas via .env da VPS (segredos gerados lá, fora do git).
- **HTTPS preparado**: server block nginx (host) para jornada.falagaiotto.com.br → 127.0.0.1:8050; certbot presente. Pendente: registro DNS A → 187.77.46.137 (aí `certbot --nginx -d jornada.falagaiotto.com.br`). Adaptação consciente: Caddy substituído pelo nginx já existente no host (porta 80 ocupada).
