/**
 * Conteúdo do Guia Interativo — registro por rota das 18 telas (SDD §8/§12 +
 * achados reais do UAT docs/UAT-VPS-2026-08-05.md). Cada página tem título,
 * descrição curta e as abas "O que é", "Fundamentos", "Campos da tela",
 * "Casos de uso", "Exemplo prático" (OS-2026-0457 demo) e "Pegadinhas"
 * (armadilhas REAIS do produto), além de páginas relacionadas (chips).
 * Tom: professor — português claro, sem jargão gratuito.
 */

export type ChaveGuia =
  | "cockpit"
  | "briefing"
  | "validacao"
  | "warroom"
  | "workflow"
  | "audiencia"
  | "datacloud"
  | "criativo"
  | "twin"
  | "simulacao"
  | "portoes"
  | "aprovacao"
  | "prevoo"
  | "lancamento"
  | "monitor"
  | "perguntas"
  | "retro"
  | "atelie";

export interface ConteudoPagina {
  titulo: string;
  /** grupo do fluxo (seções do rail; Aprovação entra em Avaliação) */
  fase: string;
  /** destino no padrão do rail: rota absoluta ou "os:sub"; null = standalone (sem navegação genérica) */
  destino: string | null;
  descricao: string;
  oQueE: string[];
  fundamentos: { termo: string; definicao: string }[];
  campos: { campo: string; significado: string }[];
  casosDeUso: string[];
  exemplo: string[];
  pegadinhas: string[];
  relacionados: ChaveGuia[];
}

/** Ordem canônica das 18 telas (ordem do fluxo da campanha). */
export const ORDEM_GUIA: ChaveGuia[] = [
  "cockpit",
  "briefing",
  "validacao",
  "warroom",
  "workflow",
  "audiencia",
  "datacloud",
  "criativo",
  "twin",
  "simulacao",
  "portoes",
  "aprovacao",
  "prevoo",
  "lancamento",
  "monitor",
  "perguntas",
  "retro",
  "atelie",
];

export const CONTEUDO_GUIA: Record<ChaveGuia, ConteudoPagina> = {
  cockpit: {
    titulo: "Cockpit",
    fase: "Principal",
    destino: "/",
    descricao:
      "Home do portfólio: KPIs, kanban por fase e saúde derivada de cada campanha (OS).",
    oQueE: [
      "O Cockpit é a porta de entrada da plataforma: todas as campanhas (OSs) do tenant aparecem num kanban organizado pelas 8 fases do ciclo de vida — de Pensada a Encerrada. No topo, quatro KPIs resumem o dia: quantas estão no ar, aguardando aprovação, em risco e no ciclo.",
      "Selecionar um card coloca aquela OS \"em foco\": o menu lateral inteiro passa a apontar para ela e o painel direito mostra fase, saúde e as últimas ações — inclusive as feitas por agentes de IA, marcadas com o badge via_ai clicável.",
      "A saúde que você vê aqui nunca é digitada por ninguém: ela é derivada em tempo real de pendências bloqueantes abertas e SLAs estourados. Não existe botão para \"pintar de verde\".",
    ],
    fundamentos: [
      {
        termo: "OS (Ordem de Serviço)",
        definicao:
          "A unidade de trabalho da plataforma: uma campanha com código (ex.: OS-2026-0457), t-shirt size (P/M/G/GG), briefing de 14 campos e fase.",
      },
      {
        termo: "Fases do ciclo",
        definicao:
          "Pensada → Discutida → Criada → Avaliada → Configurada → Disparada → Monitorada → Encerrada. Transições só acontecem com os QAs da fase satisfeitos.",
      },
      {
        termo: "Saúde derivada",
        definicao:
          "View calculada: pendência bloqueante aberta OU SLA correndo além do prazo ⇒ \"em risco\". Nunca editável — é consequência, não opinião.",
      },
      {
        termo: "via_ai",
        definicao:
          "Ledger de toda ação de agente de IA. O badge é clicável e mostra quem invocou, o que o agente propôs e quem aceitou (LGPD Art. 20).",
      },
    ],
    campos: [
      { campo: "KPIs do topo", significado: "No ar · Aguardando aprovação · Em risco · No ciclo — contagens do portfólio hoje." },
      { campo: "Kanban por fase", significado: "Colunas Pensada…Encerrada; cada card é uma OS." },
      { campo: "Card da OS", significado: "Código, nome, t-shirt (P/M/G/GG), fase e saúde derivada." },
      { campo: "Painel direito", significado: "OS selecionada: fase, saúde, últimas ações com badge via_ai e atalho \"Abrir OS →\"." },
      { campo: "Digest do copiloto", significado: "Resumo \"Hoje no portfólio\" — leitura, nunca ação automática." },
    ],
    casosDeUso: [
      "Começar o dia identificando o que está \"Em risco\" e por quê.",
      "Selecionar a OS em que vai trabalhar — isso habilita todas as telas do menu.",
      "Acompanhar a distribuição do portfólio por fase (funil de campanhas).",
      "Auditar as últimas ações de IA de uma OS pelo badge via_ai do painel.",
    ],
    exemplo: [
      "Abra o Cockpit e localize a OS-2026-0457 (a campanha demo, em fase Monitorada).",
      "Clique no card: o painel direito mostra fase, saúde \"Normal\" e as últimas ações.",
      "Repare que o menu lateral inteiro se habilitou — todas as telas agora são \"da\" OS-2026-0457.",
      "Clique em \"Abrir OS →\" para cair no Briefing e navegar o fluxo na ordem.",
    ],
    pegadinhas: [
      "Saúde nunca é editável — se está \"em risco\", a causa é uma pendência bloqueante aberta ou SLA estourado; resolva a causa, não procure um botão.",
      "Sem OS selecionada, as telas de OS ficam desabilitadas no menu (esmaecidas) — selecione um card primeiro.",
      "Ambiente demo roda com repositórios em memória: redeploy/restart apaga OSs criadas por você; só a OS-2026-0457 volta pelas seeds.",
      "Não existe (ainda) botão \"criar campanha\" na UI — a porta de entrada v1 é o portal do pedido/API (achado A3 do UAT).",
    ],
    relacionados: ["briefing", "workflow", "monitor"],
  },

  briefing: {
    titulo: "Briefing · Sala de Ideação",
    fase: "Principal",
    destino: "os:briefing",
    descricao:
      "Conversa com o Consultor de Campanhas e briefing dinâmico de 14 campos com prévia/diff Aplicar/Rejeitar.",
    oQueE: [
      "A Sala de Ideação é onde a campanha ganha forma: à esquerda, uma conversa livre com o Consultor de Campanhas (agente de IA no perfil 120B); à direita, o briefing da OS com seus 14 campos, um medidor de completude e a lista do que ainda falta.",
      "O Consultor lê sua mensagem, extrai/infere campos e devolve uma prévia de diff: valor atual vs valor inferido, com as premissas usadas. Nada entra no briefing sem você clicar Aplicar — este é o contrato de UX da IA em toda a plataforma (IA copilota, humano aprova).",
      "Campos preenchidos por inferência ficam em âmbar (inferido) até serem confirmados por um humano, quando ficam verdes.",
    ],
    fundamentos: [
      {
        termo: "Contrato de UX da IA",
        definicao:
          "Toda ação de agente chega como prévia/diff com Aplicar/Rejeitar, chips de premissas e badge via_ai. Vale nesta e em todas as telas.",
      },
      {
        termo: "Consultor",
        definicao:
          "Agente 120B do intake: extrai campos, mede completude e lista faltantes. Toda inferência dele carrega via_ai + evidências (precedentes).",
      },
      {
        termo: "Pedido → OS",
        definicao:
          "O fluxo formal nasce de um pedido (portal do solicitante); converter pedido em OS exige completude = 100%.",
      },
      {
        termo: "inferido: true",
        definicao:
          "Marca de campo preenchido por IA e ainda não confirmado — a Validação (T3) cobra a confirmação campo a campo.",
      },
    ],
    campos: [
      { campo: "Conversa", significado: "Mensagens livres para o Consultor; cada resposta pode trazer uma prévia de diff." },
      { campo: "Prévia/diff", significado: "Campo, valor atual vs inferido, premissas em chips e botões Aplicar/Rejeitar." },
      { campo: "Briefing (14 campos)", significado: "Objetivo, oferta, público, verba, janela etc. — âmbar = inferido, verde = confirmado." },
      { campo: "Completude / faltantes", significado: "Percentual preenchido e exatamente quais campos faltam." },
      { campo: "Badge via_ai", significado: "Clicável: abre a invocação (prompt, evidências, quem aceitou)." },
    ],
    casosDeUso: [
      "Dar partida numa campanha a partir de um texto corrido de necessidade.",
      "Completar rapidamente os faltantes apontados pelo medidor de completude.",
      "Pedir recomendação consultiva (ex.: vale estender o público?) e avaliar a prévia.",
      "Revisar e confirmar, campo a campo, o que a IA inferiu.",
    ],
    exemplo: [
      "Na OS-2026-0457, abra Briefing · Ideação.",
      "Escreva: \"vale a pena estender para o público controle com ARPU > 60? o que recomenda?\".",
      "O Consultor responde (~10 s no hub real) com uma prévia de diff no campo público — valor atual vs inferido, premissas e o selo \"IA copilota · humano aprova\".",
      "Clique Rejeitar: a prévia some e o briefing fica intocado. Clique Aplicar num diff bom: o campo entra em âmbar (inferido) com badge via_ai.",
      "Confirme o campo à direita para ele ficar verde — só então a Validação o considera decidido.",
    ],
    pegadinhas: [
      "Aplicar ≠ confirmar: o campo continua \"inferido\" (âmbar) até um humano confirmar — e a Validação/GO cobram isso.",
      "A extração é sensível à forma da frase (achado A1): rotule os valores (\"Verba: R$ 500 mil · Janela: 01–15/09\") para extração 100%.",
      "Converter um pedido em OS exige completude = 100 — não adianta forçar com faltantes abertos.",
      "Nenhuma resposta do agente altera o briefing sozinha; se algo mudou, houve um Aplicar humano — confira no via_ai.",
    ],
    relacionados: ["validacao", "warroom", "cockpit"],
  },

  validacao: {
    titulo: "Validação de Prontidão",
    fase: "Principal",
    destino: "os:validacao",
    descricao:
      "Cada campo do briefing é checado automaticamente contra a fonte — contagem, schema e frescor — com evidência.",
    oQueE: [
      "Antes de gastar produção com um briefing frágil, esta tela valida campo a campo contra as fontes reais: o público existe? a contagem bate? o schema confere? o dado está fresco?",
      "Cada linha traz duas ações: Validar (roda a checagem e anexa a evidência) ou Abrir pendência (registra formalmente um problema). Pendências bloqueantes seguram o GO no War Room até serem resolvidas ou aceitas.",
      "O painel direito exibe a evidência da verificação selecionada — a tríade ✓ contagem · ✓ schema · ✓ frescor é o carimbo de prontidão de cada campo.",
    ],
    fundamentos: [
      {
        termo: "Evidência tripla",
        definicao:
          "Toda validação retorna três checagens: contagem (a fonte devolve números plausíveis), schema (estrutura esperada) e frescor (idade do dado, ex.: Hybris D-1).",
      },
      {
        termo: "Pendência (ex-Hike)",
        definicao:
          "Item de risco/assunção/issue/dependência herdado do método Hike. Bloqueante = trava a etapa que ela indica (por padrão, o GO).",
      },
      {
        termo: "Resolver × Aceitar",
        definicao:
          "Resolver = o problema sumiu. Aceitar = conviver com o risco — exige papel accountable e justificativa, e fica registrado em evento de domínio.",
      },
      {
        termo: "Campo decidido",
        definicao:
          "Validado ou com pendência tratada. O GO exige todos os campos decididos (contador \"N de M\").",
      },
    ],
    campos: [
      { campo: "Linha por campo", significado: "Campo do briefing, status e resultado das checagens." },
      { campo: "Botão Validar", significado: "POST /validacoes/{campo} — executa a checagem na fonte e anexa evidência." },
      { campo: "Abrir pendência", significado: "Registra pendência (bloqueante por padrão) ancorada no campo." },
      { campo: "Painel de evidência", significado: "Detalhe da verificação selecionada: ✓ contagem · ✓ schema · ✓ frescor." },
      { campo: "Contador de decididos", significado: "Quantos campos já estão decididos (ex.: \"1 de 5\") — a régua do GO." },
    ],
    casosDeUso: [
      "Sanear o briefing antes do GO — pegar público inexistente ou verba incoerente cedo.",
      "Registrar um risco real como pendência para discussão no War Room.",
      "Conferir o frescor da fonte antes de confiar numa contagem.",
      "Reunir evidências objetivas para a decisão de GO.",
    ],
    exemplo: [
      "Na OS-2026-0457, abra Validação.",
      "Clique Validar no campo público: a linha ganha ✓ contagem · ✓ schema · ✓ frescor e o painel mostra a evidência (fonte Hybris D-1 nas fixtures).",
      "Num campo duvidoso, clique Abrir pendência — nasce a Pendência #1, bloqueante.",
      "Vá ao War Room e tente o GO: 409 listando a pendência. Resolva-a e o GO libera.",
    ],
    pegadinhas: [
      "Pendência bloqueante aberta trava o GO — o 409 lista exatamente o motivo; não é bug, é o QA funcionando.",
      "Validação consulta a fonte de verdade: se a fonte está defasada, o frescor reprova mesmo com o campo \"certo\".",
      "A pendência nasce com 1 clique, sem diálogo de título/descrição (achado A9) — detalhe-a depois no War Room.",
      "Aceitar um risco não é apagar: exige accountable + justificativa e fica auditável para sempre.",
    ],
    relacionados: ["briefing", "warroom", "audiencia"],
  },

  warroom: {
    titulo: "War Room de Decisão",
    fase: "Principal",
    destino: "os:warroom",
    descricao:
      "Threads ancoradas em campos, quadro de pendências e o GO formal — que congela SLAs e versões em os.frozen.",
    oQueE: [
      "O War Room é a sala do GO: aqui o time discute (threads ancoradas em campos específicos do briefing), trata as pendências abertas e toma a decisão formal de seguir para produção.",
      "O GO não é um clique simbólico: ele muda a fase para \"criada\", congela em os.frozen as versões publicadas dos agentes, a versão da política, o tarifário e os SLAs — e gera um documento executivo (.docx) do que foi decidido.",
      "Se algo estiver pendente — campo não decidido ou pendência bloqueante — o GO retorna 409 com a lista exata dos bloqueios.",
    ],
    fundamentos: [
      {
        termo: "GO",
        definicao:
          "Decisão formal que move a OS para a fase \"criada\" e congela o contexto (frozen). A partir daqui os SLAs correm oficialmente.",
      },
      {
        termo: "os.frozen",
        definicao:
          "Snapshot do contexto no GO: versões dos agentes, versão da política, tarifário e SLAs. Publicações futuras de skills/políticas NÃO afetam a campanha em voo.",
      },
      {
        termo: "Thread ancorada",
        definicao:
          "Discussão amarrada a um campo do briefing — o histórico da decisão fica junto do dado discutido.",
      },
      {
        termo: "Segregação de papéis",
        definicao:
          "Aceites exigem o papel accountable; mais adiante, quem cria o snapshot não pode aprová-lo (checado no servidor).",
      },
    ],
    campos: [
      { campo: "Threads", significado: "Discussões por campo do briefing, com resumo da discussão." },
      { campo: "Quadro de pendências", significado: "Tipo (risk/assumption/issue/dependency), severidade, bloqueante, status, ações resolver/aceitar." },
      { campo: "Painel do GO", significado: "Estado dos bloqueios e o botão do GO; sucesso congela frozen e gera o .docx." },
      { campo: "Aceite de pendência", significado: "Requer accountable + justificativa; gera evento de domínio auditável." },
    ],
    casosDeUso: [
      "Discutir um campo divergente com o histórico ancorado nele.",
      "Formalizar o aceite de um risco com justificativa e responsável.",
      "Dar o GO e congelar o contexto da campanha.",
      "Recuperar o documento executivo da decisão.",
    ],
    exemplo: [
      "Na OS-2026-0457, abra o War Room.",
      "Crie uma thread ancorada no campo verba e registre a discussão.",
      "Trate as pendências abertas na Validação (resolver ou aceitar com justificativa).",
      "Clique GO: com pendência bloqueante → 409 listando-a; sem bloqueios → fase \"criada\", frozen preenchido e .docx gerado.",
    ],
    pegadinhas: [
      "GO com campo não decidido ou pendência bloqueante → 409; a lista de motivos vem na própria resposta.",
      "Depois do GO, publicar uma skill ou política nova NÃO muda esta campanha — ela roda com as versões congeladas (frozen).",
      "Os SLAs congelam no GO: a partir daí, atraso passa a pintar a saúde da OS de \"em risco\".",
      "Aceitar pendência sem ser o accountable não funciona — a checagem é do servidor, não da tela.",
    ],
    relacionados: ["validacao", "workflow", "portoes"],
  },

  workflow: {
    titulo: "Esteira de Produção",
    fase: "Principal",
    destino: "os:workflow",
    descricao:
      "As 7 etapas da produção (ex-Hike) com responsável, SLA, checklist e dependências entre etapas.",
    oQueE: [
      "A Esteira é o quadro operacional da produção: sete etapas na ordem — briefing, discovery, audiência, criativos, configuração, disparo e acompanhamento — cada uma com responsável, SLA em dias, checklist e dependências.",
      "Ela herda o método do Hike: campanhas antigas podem ser importadas preservando o histórico (hike_ref guarda o card original). As regras são duras: uma etapa com dependência insatisfeita não inicia — o servidor responde 409 e a tela explica o bloqueio em um banner.",
      "Criativos nasce com 4 subtarefas padrão e Acompanhamento com os marcos D+1 / D+7 / D+15.",
    ],
    fundamentos: [
      {
        termo: "Dependência entre etapas",
        definicao:
          "Etapa só vai a \"em andamento\" com as dependências concluídas — tentar fora de ordem devolve 409 (RFC-7807) com o motivo.",
      },
      {
        termo: "Checklist",
        definicao:
          "Subtarefas com autor e data (ex.: as 4 de Criativos). São contrato do módulo, não decoração.",
      },
      {
        termo: "hike_ref",
        definicao:
          "Referência ao card importado do Hike (id, data de importação, URL arquivada) — o histórico não se perde.",
      },
      {
        termo: "SLA por etapa",
        definicao:
          "Prazo congelado no GO; estourar SLA derruba a saúde da OS para \"em risco\".",
      },
    ],
    campos: [
      { campo: "Linha da etapa", significado: "Ordem, nome, responsável, SLA (dias) e estado (pendente/em andamento/concluída/bloqueada)." },
      { campo: "Iniciar / Concluir", significado: "Transições de estado — o servidor valida dependências antes." },
      { campo: "Checklist", significado: "Subtarefas da etapa com quem fez e quando." },
      { campo: "Painel da etapa", significado: "Detalhe da selecionada, incluindo hike_ref quando importada." },
      { campo: "Banner de erro", significado: "Explica o 409 quando uma transição é bloqueada por dependência." },
    ],
    casosDeUso: [
      "Acompanhar em que pé está a produção da campanha.",
      "Identificar qual dependência está segurando uma etapa.",
      "Cumprir o checklist de Criativos antes de dar a etapa por concluída.",
      "Auditar o histórico de uma campanha importada do Hike.",
    ],
    exemplo: [
      "Na OS-2026-0457, abra a Esteira: as 7 etapas aparecem na ordem.",
      "Clique Iniciar na etapa 1 — ela vai a \"em andamento\".",
      "Tente iniciar a etapa 3 com dependência insatisfeita: um banner explica o 409 e a etapa segue pendente.",
      "Abra a etapa Criativos e confira as 4 subtarefas padrão do checklist.",
    ],
    pegadinhas: [
      "Dependência insatisfeita → 409: o backend sempre segurou; o banner explicativo foi adicionado após o UAT (A6) — se nada parece acontecer, leia o banner.",
      "Concluir etapa não pula checklist — subtarefas abertas ficam registradas.",
      "O acompanhamento D+1/D+7/D+15 é etapa da esteira, não lembrete informal.",
      "Importação do Hike cria OSs com histórico preservado — não recadastre campanhas na mão.",
    ],
    relacionados: ["warroom", "criativo", "lancamento"],
  },

  audiencia: {
    titulo: "Estúdio de Audiência",
    fase: "Produção",
    destino: "os:audiencia",
    descricao:
      "Waterfall base→líquido, SQL do Engineer com evidências, holdout e certificação do Guard determinístico.",
    oQueE: [
      "Aqui o público-alvo vira um segmento auditável. O Engineer (agente 120B) gera o SQL de segmentação com explicação por cláusula e evidências do dicionário de dados; a recontagem roda em dry-run no read model e devolve o waterfall: base bruta → cortes por etapa → líquido com opt-in válido.",
      "O holdout (grupo de controle) é definido no slider — a política estabelece o mínimo. O passo final é a certificação do Guard: um validador 100% determinístico (nunca LLM) que varre as 7 listas de supressão e o opt-in e emite o certificado de elegibilidade com hash e validade.",
      "O princípio: IA escreve a consulta e explica; código decide quem pode ser abordado.",
    ],
    fundamentos: [
      {
        termo: "Engineer + exige_evidencia",
        definicao:
          "O agente só gera SQL citando evidências RAG do dicionário de dados. Sem evidência, ele RECUSA — guard-rail de compliance, não defeito.",
      },
      {
        termo: "Guard determinístico",
        definicao:
          "Validador por código: 7 listas (blacklist, fraude, não perturbe, optout, procon, inadimplente, reprovado crédito) + opt-in. LLM não participa do veredito.",
      },
      {
        termo: "Certificado de elegibilidade",
        definicao:
          "Documento com hash, contagens suprimidas por lista, líquido final e validade. O publish (compilador) recusa certificado expirado; no disparo há re-varredura last-mile.",
      },
      {
        termo: "Waterfall",
        definicao:
          "Sequência de cortes com motivo e restante em cada etapa — o caminho auditável do bruto ao líquido.",
      },
      {
        termo: "Holdout",
        definicao:
          "Percentual reservado como controle do experimento; sem ele não há medição honesta de lift.",
      },
    ],
    campos: [
      { campo: "Base do segmento (bruta)", significado: "Contagem inicial antes de qualquer corte." },
      { campo: "Waterfall", significado: "Cada corte: etapa, quantos saíram, quantos restaram e o motivo." },
      { campo: "Líquido com opt-in", significado: "Quem pode de fato ser abordado após compliance." },
      { campo: "SQL do Engineer", significado: "Consulta gerada com explicação por cláusula e evidências citadas (via_ai)." },
      { campo: "Slider de holdout", significado: "Percentual de controle; a política valida o mínimo." },
      { campo: "Certificar (Guard)", significado: "Emite o certificado com hash e validade." },
      { campo: "Frescor por fonte", significado: "Idade do dado de cada fonte (ex.: Hybris D-1)." },
    ],
    casosDeUso: [
      "Gerar o SQL de segmentação com rastreabilidade de cada coluna usada.",
      "Recontar após um ajuste de critério e entender o waterfall.",
      "Definir o holdout respeitando o mínimo da política.",
      "Emitir o certificado de elegibilidade exigido pelos QA.",
    ],
    exemplo: [
      "Na OS-2026-0457 (segmento demo de 847.312), abra Audiência.",
      "Clique \"Gerar SQL (Engineer)\": o SQL vem com as 7 listas no WHERE e explicação por cláusula.",
      "Recontar → waterfall bruto → cortes → líquido com opt-in.",
      "Ajuste o holdout no slider (a política valida o mínimo).",
      "Clique Certificar: o Guard varre as listas e emite o certificado com hash e validade.",
    ],
    pegadinhas: [
      "O Engineer recusa gerar SQL sem evidência RAG (\"não disponho das evidências…\") — visto ao vivo no UAT (A11); é o compliance funcionando: provisione a base dicionario_dados, não force o agente.",
      "SQL sem as 7 listas no WHERE → o Guard reprova a certificação (há teste com SQL adulterado).",
      "Certificado tem validade — expirou, o publish recusa; e o disparo ainda faz re-varredura last-mile.",
      "Percentuais do relatório são sobre o líquido, não sobre o bruto — cuidado ao comparar.",
      "Holdout abaixo do mínimo da política não passa; e sem holdout não existe experimento nem lift medível.",
    ],
    relacionados: ["datacloud", "portoes", "twin"],
  },

  datacloud: {
    titulo: "Segmentos do Data Cloud",
    fase: "Produção",
    destino: "os:datacloud",
    descricao:
      "Catálogo dinâmico (consulta, não cópia), relatório bruto→elegível→líquido e volume de abordagem por canal.",
    oQueE: [
      "Esta tela conecta a plataforma aos segmentos já publicados no Salesforce Data Cloud — por consulta, nunca por cópia. O catálogo mostra membros, DMOs, ciclo de republicação e há quanto tempo cada segmento foi republicado.",
      "Selecionar um segmento abre o relatório de tamanho de público: bruto → elegível (menos as 7 listas) → líquido, com sobreposição nomeada com outros segmentos e frescor por fonte. Na sequência vem o volume de abordagem por canal: quantos contatos restam de verdade em e-mail, SMS, push e WhatsApp depois de caps de frequência, quiet hours e colisões com outras campanhas (arbitradas pelo Contact Governor).",
      "Se o segmento serve, \"Usar como entrada no Estúdio\" o transforma em segmento da OS com lineage preservado.",
    ],
    fundamentos: [
      {
        termo: "Consulta, não cópia",
        definicao:
          "A plataforma não replica o Data Cloud (non-goal do v1): mantém um cache com frescor e sempre indica a idade do dado.",
      },
      {
        termo: "Volume de abordagem",
        definicao:
          "Contagem por canal APÓS caps, quiet hours e colisões — o número que realmente importa para planejar o disparo.",
      },
      {
        termo: "Contact Governor",
        definicao:
          "Árbitro de pressão de contato entre campanhas: aponta colisões e recomenda o mix de canais.",
      },
      {
        termo: "Lineage",
        definicao:
          "Ao usar um segmento do DC, a origem (dc_segment_id) fica registrada — dá para rastrear de onde veio o público.",
      },
    ],
    campos: [
      { campo: "Catálogo", significado: "Segmentos com membros, DMOs, \"republicado há X\", ciclo e status (incl. \"republicando\")." },
      { campo: "Relatório de público", significado: "Bruto → elegível (−7 listas) → líquido → sobreposição nomeada." },
      { campo: "Frescor por fonte", significado: "Ex.: data cloud 6 h · hybris 24 h · governor 2 h." },
      { campo: "Volume por canal", significado: "Contagem e % do líquido por canal, com colisões do governor e mix recomendado." },
      { campo: "Usar como entrada", significado: "Cria segmento origem data_cloud na OS, com lineage." },
    ],
    casosDeUso: [
      "Aproveitar um segmento já publicado em vez de escrever SQL do zero.",
      "Dimensionar o volume real por canal antes de decidir o mix.",
      "Verificar sobreposição com outra campanha no ar e evitar fadiga de contato.",
      "Trazer o segmento para o Estúdio com rastreabilidade.",
    ],
    exemplo: [
      "Na OS-2026-0457, abra Data Cloud: o catálogo lista 4 segmentos.",
      "Selecione o principal: relatório 1.240.580 (bruto) → 1.180.200 (elegível, −7 listas) → 826.580 (líquido).",
      "Observe a sobreposição nomeada (~121 mil com DC-SEG-002) e o frescor por fonte.",
      "No volume de abordagem: E-mail 603,6 mil (73%) … WhatsApp 252 mil (30,5%), com colisões do governor.",
      "Clique \"Usar como entrada no Estúdio\" — o segmento vira entrada da OS com lineage.",
    ],
    pegadinhas: [
      "Números do catálogo têm frescor: um segmento \"republicando\" pode mudar de contagem — confira o \"republicado há\".",
      "A soma dos canais não bate com o líquido de propósito: caps, quiet hours e colisões cortam por canal (soma ≤ líquido).",
      "A plataforma não edita critérios do Data Cloud — critérios se ajustam lá; aqui se consulta e se usa.",
      "O botão \"Usar como entrada\" existe desde a correção A12 do UAT — sem esse passo o segmento NÃO entra na OS.",
    ],
    relacionados: ["audiencia", "twin", "portoes"],
  },

  criativo: {
    titulo: "Estúdio Criativo",
    fase: "Produção",
    destino: "os:criativo",
    descricao:
      "Matriz canal × variante nascida do KV master, preview por device, validadores por canal e aprovação por célula.",
    oQueE: [
      "O Estúdio gera a matriz de peças: a partir do Key Visual master (DCO), cada canal × variante vira uma célula com preview no device correspondente. Copy/Visual/Content (agentes 120B) propõem adaptações; a decisão é sempre humana.",
      "Cada célula tem estado próprio e validadores por canal: SMS até 160 caracteres, template de WhatsApp com status válido na Meta, compliance de linguagem (regras determinísticas + aviso de LLM).",
      "Regra de ouro: nenhuma célula chega a \"aprovado\" pela mão de um agente — apenas um humano com papel analista ou superior aprova.",
    ],
    fundamentos: [
      {
        termo: "KV master (DCO)",
        definicao:
          "A peça-mãe da qual as variações derivam. Editá-la rebaixa TODAS as células derivadas para \"adaptado_revisar\".",
      },
      {
        termo: "Aprovação por célula",
        definicao:
          "Cada combinação canal × variante é aprovada individualmente, por humano analista+ — o agente propõe, nunca aprova.",
      },
      {
        termo: "Validadores por canal",
        definicao:
          "SMS ≤ 160 caracteres (161 → 422), template WhatsApp com status aprovado, limites por canal validados no servidor.",
      },
      {
        termo: "adaptado_revisar",
        definicao:
          "Estado de célula cuja origem mudou — precisa de nova revisão humana antes de voltar a valer.",
      },
    ],
    campos: [
      { campo: "Matriz canal × variante", significado: "Grade de células; cada uma com estado (rascunho, adaptado_revisar, aprovado…)." },
      { campo: "Preview no device", significado: "A peça renderizada no formato do canal (e-mail, SMS, push, WhatsApp)." },
      { campo: "KV master", significado: "Peça-mãe; editar propaga \"adaptado_revisar\" às derivadas." },
      { campo: "Validador do canal", significado: "Erros/avisos específicos (tamanho de SMS, template Meta, linguagem)." },
      { campo: "Copiloto Copy", significado: "Propostas de texto como prévia — Aplicar/Rejeitar." },
    ],
    casosDeUso: [
      "Gerar a matriz completa de peças a partir do KV master.",
      "Revisar e aprovar célula a célula com preview fiel ao canal.",
      "Adaptar a mensagem por canal respeitando os limites de cada um.",
      "Regenerar uma variação fraca sem perder as aprovadas.",
    ],
    exemplo: [
      "Na OS-2026-0457, abra o Criativo e gere a matriz a partir do KV master.",
      "Escreva um SMS com 161 caracteres: o validador devolve 422 na hora — corte para ≤ 160.",
      "Edite o KV master: repare que as células derivadas caem para \"adaptado_revisar\".",
      "Aprove as células revisadas uma a uma (papel analista+).",
    ],
    pegadinhas: [
      "SMS com 161 caracteres → 422; o limite é contrato, não sugestão.",
      "Editar o KV master rebaixa TODAS as derivadas para \"adaptado_revisar\" — planeje edições da peça-mãe antes da rodada de aprovações.",
      "Agente nunca aprova célula; se uma célula está \"aprovada\", um humano clicou — e o via_ai mostra quem.",
      "WhatsApp exige template com status válido — texto livre fora de template não passa.",
      "No demo, o KV master default é da campanha de franquia mesmo em OS de recarga (achado A8, aberto) — não estranhe o placeholder.",
    ],
    relacionados: ["workflow", "twin", "aprovacao"],
  },

  twin: {
    titulo: "Twin · Canvas da Jornada",
    fase: "Produção",
    destino: "os:twin",
    descricao:
      "O grafo canônico (JGC) da jornada no React Flow — paleta Journey Builder, taxímetro e ajuste por diff.",
    oQueE: [
      "O canvas é o coração do produto: a jornada é um grafo canônico JSON (JGC) versionado — o Digital Twin do Journey Builder. O que você vê aqui é a fonte da verdade; o SFMC recebe uma materialização compilada dela, nunca o contrário.",
      "O agente Flow gera a primeira versão a partir do briefing (sempre como prévia), e você refina: nós na paleta visual do Journey Builder (entrada verde, mensagens teal, decisões laranja, otimização roxa, updates azul), inspetor de nó com a prévia exata do JSON que o compilador vai gerar, e o taxímetro no rodapé somando volume × tarifa por canal — cálculo por código, não por IA.",
      "Ajustes podem ser pedidos em texto livre (\"adicione um reforço D+3 para quem não abriu\"): a resposta vem como diff Aplicar/Rejeitar — nunca aplicada direto.",
    ],
    fundamentos: [
      {
        termo: "JGC",
        definicao:
          "Journey Graph Canônico: JSON versionado com hash (RFC 8785 + sha256). Cada save que muda o grafo é uma versão nova em rascunho.",
      },
      {
        termo: "Tipos de nó fechados",
        definicao:
          "entrySource, splits (random/decision/engagement/frequency), sto, wait, channel.*, updateContact, goal, exit, exception — tipo fora da lista é rejeitado.",
      },
      {
        termo: "Validação semântica (§5.3)",
        definicao:
          "A cada save: braço órfão, soma de percentuais ≠ 100, canal sem opt-in, grafo sem goal etc. → 422 apontando o nó.",
      },
      {
        termo: "Taxímetro",
        definicao:
          "Custo projetado = Σ (volume esperado × tarifa vigente do canal). Recalculado a cada edição, sempre por código.",
      },
      {
        termo: "Modos Desenho/Simulação/Dinâmico",
        definicao:
          "Desenho = edição; Simulação = resultados do Ensaio sobre o grafo; Dinâmico = campanha no ar.",
      },
    ],
    campos: [
      { campo: "Canvas", significado: "Nós e arestas na paleta Journey Builder; losangos laranja = decisões." },
      { campo: "Inspetor de nó", significado: "Dados do nó + prévia do JSON SFMC que o compilador gerará." },
      { campo: "Taxímetro (rodapé)", significado: "Custo projetado ao vivo; contadores de nós/arestas e meta do JGC." },
      { campo: "Chips de premissas", significado: "Premissas assumidas pelo Flow ao gerar/ajustar — leia antes de aplicar." },
      { campo: "Ajustar por texto", significado: "Pedido em linguagem natural → diff proposto com Aplicar/Rejeitar." },
    ],
    casosDeUso: [
      "Gerar a primeira versão da jornada com o Flow e refinar na mão.",
      "Inspecionar exatamente o que será criado no SFMC, nó a nó.",
      "Pedir um ajuste em texto e revisar o diff antes de aplicar.",
      "Acompanhar o custo projetado enquanto desenha.",
    ],
    exemplo: [
      "Na OS-2026-0457, abra o Twin: o grafo demo carrega com 13 nós e taxímetro de R$ 31.800.",
      "Clique num nó channel.email e veja a prévia JSON SFMC no inspetor.",
      "Use \"Ajustar por texto\" e peça um reforço; o diff chega para Aplicar/Rejeitar.",
      "Provoque um erro: deixe um braço de split sem destino e salve — 422 apontando o nó órfão.",
    ],
    pegadinhas: [
      "Editar o grafo cria versão nova em rascunho — a simulação anterior deixa de valer para ela: re-simule antes de avançar (o snapshot amarra tudo por hash).",
      "Braço órfão, percentuais que não somam 100 ou grafo sem goal → 422 no save; o erro aponta o nó.",
      "Reentrada ≠ \"não\" com experimento travado → 422: reentrada quebra o experimento (contrato de re-entrada).",
      "O taxímetro usa a tarifa vigente — tarifa mudou, custo projetado muda; e variação de custo >10% depois da aprovação invalida a aprovação.",
      "Sem segmento definido, o taxímetro mostra volume 0 honestamente — não é bug, é falta de audiência.",
    ],
    relacionados: ["simulacao", "audiencia", "prevoo"],
  },

  simulacao: {
    titulo: "Ensaio Geral (Simulação)",
    fase: "Avaliação",
    destino: "os:simulacao",
    descricao:
      "Monte Carlo com personas sintéticas — P10/P50/P90, funil por nó, semáforo e o Previsto congelado.",
    oQueE: [
      "Nada dispara sem ensaio: o simulador roda a jornada com 10.000 personas sintéticas × 500 execuções Monte Carlo, com relógio virtual que respeita waits, quiet hours, throttle e STO. As personas vêm de agregados estatísticos — nunca de registros individuais.",
      "A saída é a previsão honesta da campanha: conversões, custo, receita, ROAS e lift em três cenários (P10 pessimista / P50 mediano / P90 otimista), funil por nó, gargalos e um semáforo verde/amarelo/vermelho.",
      "O passo decisivo é Congelar o Previsto: o P50 congelado vira a régua imutável contra a qual o Monitoramento comparará o realizado. O copiloto Simulate apenas narra os achados — todos os números são código.",
    ],
    fundamentos: [
      {
        termo: "QA obrigatório",
        definicao:
          "Semáforo vermelho bloqueia QA e Pré-voo. Vermelho = ROAS P50 < 1 ou colisão crítica do governor.",
      },
      {
        termo: "Previsto congelado",
        definicao:
          "O resultado da simulação gravado no snapshot. É a régua do previsto × realizado — não muda nunca mais.",
      },
      {
        termo: "P10/P50/P90",
        definicao:
          "Percentis da distribuição Monte Carlo: cenário ruim, mediano e ótimo. Planeje pelo P50, proteja-se pelo P10.",
      },
      {
        termo: "Poder estatístico",
        definicao:
          "Se o n do holdout é menor que o mínimo para o MDE, o QA de experimento fica vermelho e a simulação amarela.",
      },
      {
        termo: "Reprodutibilidade",
        definicao:
          "Seed fixa ⇒ mesmos P50s em qualquer re-execução — auditável por definição.",
      },
    ],
    campos: [
      { campo: "KPIs P50", significado: "Conversões, custo total, receita projetada, ROAS e lift esperado — com faixas P10/P90." },
      { campo: "Funil por nó", significado: "Quantas personas passam em cada nó/aresta — onde a jornada perde gente." },
      { campo: "Gargalos", significado: "Pontos de estrangulamento (quiet hours, throttle, colisões)." },
      { campo: "Semáforo", significado: "Verde/amarelo/vermelho — vermelho bloqueia o avanço." },
      { campo: "Comparador de cenários", significado: "Duas simulações lado a lado para decidir entre variantes." },
      { campo: "Congelar Previsto", significado: "Grava a régua do pós-disparo no snapshot." },
    ],
    casosDeUso: [
      "Ensaiar a jornada antes de pedir aprovação — encontrar surpresas no ambiente seguro.",
      "Comparar dois cenários (ex.: com/sem canal caro) lado a lado.",
      "Detectar gargalos de quiet hours ou throttle antes do mundo real.",
      "Congelar o Previsto que servirá de régua para o Monitor.",
    ],
    exemplo: [
      "Na OS-2026-0457, abra o Ensaio Geral e clique Simular.",
      "Confira os KPIs P50 com as faixas P10/P90 e o funil por nó.",
      "Rode de novo: os P50s repetem (seed fixa) — a simulação é reprodutível.",
      "Congele o Previsto: é contra ele que o Monitor comparará (na demo, o realizado veio +24,1pp de lift).",
    ],
    pegadinhas: [
      "Semáforo vermelho bloqueia QA e Pré-voo — ROAS P50 < 1 ou colisão crítica não passam; resolva a causa e re-simule.",
      "Poder insuficiente pinta o experimento de vermelho e a simulação de amarelo — aumente o holdout ou o público, ou aceite um MDE maior.",
      "Editou o twin depois de simular? A simulação não vale mais para a nova versão — re-simule antes de montar o snapshot.",
      "O Monitor compara contra o Previsto CONGELADO, nunca contra a última simulação — congelar é um ato consciente.",
      "O Simulate (LLM) apenas narra; se um número parecer estranho, a fonte é o simulador determinístico, não o texto.",
    ],
    relacionados: ["twin", "portoes", "monitor"],
  },

  portoes: {
    titulo: "QA de Governança",
    fase: "Avaliação",
    destino: "os:portoes",
    descricao:
      "Os 4 QAs bloqueantes — Certificado LGPD, Experimento, Custo & Alçada, Contact Governor — e o snapshot + link mágico.",
    oQueE: [
      "Antes de qualquer pacote ir ao aprovador, quatro QAs objetivos precisam estar verdes: o Certificado de Elegibilidade (Guard determinístico, LGPD), o experimento pré-registrado (holdout, n mínimo, MDE, janela), o custo dentro da alçada da política e o Contact Governor sem colisão crítica.",
      "Com os QAs satisfeitos, monta-se o snapshot: um pacote imutável com hash composto de JGC + SQL + criativos + políticas + custo + experimento. É esse hash — e somente ele — que segue para aprovação e depois para o SFMC.",
      "O fechamento é o link mágico (T10): uma URL pública de uso único enviada ao aprovador. Segregação garantida no servidor: quem cria o snapshot não pode aprová-lo.",
    ],
    fundamentos: [
      {
        termo: "QA (gate)",
        definicao:
          "Critério objetivo e bloqueante — não é checklist de boas intenções: vermelho segura o fluxo.",
      },
      {
        termo: "Snapshot",
        definicao:
          "Pacote imutável por hash composto; o que foi aprovado é exatamente o que será publicado (homolog → prod com o MESMO hash).",
      },
      {
        termo: "Experimento pré-registrado",
        definicao:
          "Holdout, n mínimo, MDE e janela travados ANTES do disparo — pré-registro evita 'ajustar a régua' depois (anti-peeking).",
      },
      {
        termo: "Alçada",
        definicao:
          "Faixas de valor da política definem quem pode aprovar. Custo variando >10% após a aprovação re-dispara o processo.",
      },
      {
        termo: "Segregação",
        definicao: "Criador ≠ aprovador, verificado no servidor — não há como se auto-aprovar.",
      },
    ],
    campos: [
      { campo: "Certificado de Elegibilidade", significado: "Estado do certificado do Guard: hash, validade, contagens suprimidas." },
      { campo: "Experimento pré-registrado", significado: "Holdout %, n mínimo, MDE (pp), janela e validação de poder." },
      { campo: "Custo & Alçada", significado: "Custo projetado vs faixas da política; envio à alçada correta." },
      { campo: "Contact Governor", significado: "Pressão de contato e colisões com outras campanhas." },
      { campo: "Montar snapshot", significado: "Gera o pacote imutável com hash composto." },
      { campo: "Gerar link mágico", significado: "URL pública de uso único para o aprovador (T10)." },
    ],
    casosDeUso: [
      "Conferir de uma vez os 4 QAs antes de envolver o aprovador.",
      "Pré-registrar o experimento com poder estatístico validado.",
      "Enviar o custo à alçada certa segundo a política.",
      "Montar o snapshot e disparar o link mágico.",
    ],
    exemplo: [
      "Na OS-2026-0457, abra QA: os 4 cartões mostram seu estado.",
      "Confira o certificado emitido na Audiência (hash e validade).",
      "Valide o experimento pré-registrado (holdout 10%, n mínimo, MDE, janela).",
      "Monte o snapshot — o hash composto aparece — e gere o link mágico para o aprovador.",
    ],
    pegadinhas: [
      "Quem cria não aprova — a segregação é validada no servidor; peça o aceite a quem tem alçada.",
      "Variação de custo >10% APÓS a aprovação invalida a aprovação: snapshot novo, aprovação nova (aceite A4 do M8).",
      "Certificado expirado bloqueia — o Guard tem validade e o publish confere de novo.",
      "Simulação vermelha segura o snapshot: os QAs leem o semáforo do Ensaio.",
      "Ressalvas do aprovador viram pendências automáticas na OS — elas não se perdem no e-mail.",
    ],
    relacionados: ["simulacao", "aprovacao", "prevoo"],
  },

  aprovacao: {
    titulo: "Portal de Aprovação (link mágico)",
    fase: "Avaliação",
    destino: null,
    descricao:
      "Página standalone do aprovador: snapshot imutável, replay do Previsto, hash visível e decisão única.",
    oQueE: [
      "O aprovador não precisa de login: o link mágico carrega um token que é a própria credencial. A página abre fora do shell da plataforma — sem menu, sem ações de IA — com foco total na decisão.",
      "O conteúdo é o snapshot imutável: resumo executivo (público líquido, investimento, ROAS previsto, holdout), waterfall da audiência, criativos e o replay do Previsto da simulação, com o hash do pacote visível para conferência.",
      "A decisão é única: Aprovar, Aprovar com ressalvas ou Reprovar. Ressalvas viram pendências automáticas na OS; a decisão registra IP e device.",
    ],
    fundamentos: [
      {
        termo: "Link mágico",
        definicao:
          "URL pública com token de uso único e prazo de expiração. Usou ou venceu → não abre de novo; gere outro link.",
      },
      {
        termo: "Snapshot imutável",
        definicao:
          "O que se aprova é um hash: qualquer mudança posterior (grafo, custo, criativos) exige novo snapshot e nova aprovação.",
      },
      {
        termo: "Aprovado com ressalvas",
        definicao:
          "Aprova o pacote e registra condições — cada ressalva vira pendência rastreável na OS automaticamente.",
      },
      {
        termo: "Invalidação por custo",
        definicao:
          "Custo variando >10% depois da decisão invalida a aprovação (registrado com motivo).",
      },
    ],
    campos: [
      { campo: "Resumo executivo", significado: "Público líquido, investimento, ROAS previsto e holdout — os 4 números da decisão." },
      { campo: "Waterfall", significado: "Como o público saiu do bruto ao líquido (compliance visível)." },
      { campo: "Criativos", significado: "As peças aprovadas que serão disparadas." },
      { campo: "Replay do Previsto", significado: "A previsão congelada da simulação — a promessa contra a qual se cobra depois." },
      { campo: "Hash do snapshot", significado: "Identidade do pacote — o mesmo hash segue para homolog e prod." },
      { campo: "Decisão", significado: "Aprovar · Aprovar com ressalvas · Reprovar (com campo de ressalvas)." },
    ],
    casosDeUso: [
      "Aprovar remotamente sem criar conta nem senha.",
      "Aprovar com ressalvas que viram pendências rastreáveis.",
      "Reprovar com registro formal de quando e de onde.",
      "Conferir pelo hash que o pacote é exatamente o discutido.",
    ],
    exemplo: [
      "O aprovador recebe a URL /aprovacao/{token} (na demo, via Mailpit).",
      "Abre e confere: público líquido, investimento, ROAS previsto, holdout, waterfall e criativos.",
      "Faz o replay do Previsto e anota o hash do snapshot.",
      "Decide \"Aprovar com ressalvas\" com um texto — as ressalvas aparecem como pendências na OS e a decisão grava IP/device.",
    ],
    pegadinhas: [
      "O token é de uso ÚNICO e expira — link já usado ou vencido não abre; gere um novo em QA.",
      "A decisão é única e definitiva — não há \"mudar de ideia\" no mesmo token.",
      "Custo subir >10% depois da aprovação invalida a decisão — o fluxo volta para novo snapshot.",
      "A página é standalone de propósito: sem Bearer, sem shell — não estranhe a ausência do menu.",
    ],
    relacionados: ["portoes", "prevoo", "lancamento"],
  },

  prevoo: {
    titulo: "Plano de Compilação & Pré-voo",
    fase: "Avaliação",
    destino: "os:prevoo",
    descricao:
      "Plan/apply determinístico para o SFMC, bateria de pré-voo pass/warn/fail e monitor de drift.",
    oQueE: [
      "Aqui o snapshot aprovado vira realidade no SFMC — no estilo Terraform: primeiro o plan (lista declarativa do que será criado/alterado/mantido/destruído, com avisos destrutivos), depois o apply idempotente, com chaves externas derivadas do hash e rollback compensatório em caso de falha.",
      "Antes do apply em produção roda a bateria de pré-voo: DEs e schemas, frescor das fontes, opt-in, listas last-mile, lint de AMPscript, limites do SFMC, drift zero e seed dry-run — cada item pass/warn/fail. FAIL bloqueia; WARN documenta.",
      "O compilador é 100% determinístico — LLM proibido neste caminho. O agente Sync apenas traduz o plano técnico para impacto de negócio. O drift (alguém mexeu direto no SFMC) é vigiado a cada 30 min e pode ser resolvido com adopt/enforce/exceção.",
    ],
    fundamentos: [
      {
        termo: "Plan / Apply",
        definicao:
          "Plan = lista do que vai acontecer (sem tocar em nada); Apply = execução na ordem de dependências, com orçamento de chamadas e rollback do que criou se falhar.",
      },
      {
        termo: "Idempotência",
        definicao:
          "ExternalKey = jrn-{hash12}-{noId}: aplicar duas vezes o mesmo hash = 0 mutações na segunda.",
      },
      {
        termo: "Pré-voo",
        definicao:
          "Bateria objetiva pass/warn/fail com evidência por item; resultado verde/amarelo/vermelho por snapshot × ambiente.",
      },
      {
        termo: "Drift",
        definicao:
          "Divergência twin ↔ SFMC. Em produção, drift abre pendência automática BLOQUEANTE. Resoluções: adopt (aceitar no twin), enforce (reimpor o twin), exceção.",
      },
      {
        termo: "Homolog → prod",
        definicao:
          "Mesmo hash nos dois ambientes; prod exige aprovação decidida + certificado válido + pré-voo verde.",
      },
    ],
    campos: [
      { campo: "Plano declarativo", significado: "Recurso a recurso: criar/alterar/manter/destruir + avisos destrutivos." },
      { campo: "Resultado do apply", significado: "sync_run com estado (ok/parcial/revertido/falhou) e nº de chamadas de API." },
      { campo: "Bateria de pré-voo", significado: "Itens pass/warn/fail com evidência; resultado geral verde/amarelo/vermelho." },
      { campo: "Painel de drift", significado: "Recursos em sincronia / drift SFMC / twin à frente, com diff e resolução." },
      { campo: "Narrativa do Sync", significado: "O plano traduzido para impacto de negócio (LLM narra, nunca executa)." },
    ],
    casosDeUso: [
      "Planejar a publicação em homolog e revisar os avisos destrutivos.",
      "Rodar o pré-voo e tratar os FAILs antes de prod.",
      "Aplicar em produção com todas as garantias (aprovação + certificado + verde).",
      "Investigar e resolver um drift detectado.",
    ],
    exemplo: [
      "Na OS-2026-0457, abra Pré-voo e rode o Plan em homolog.",
      "Leia o plano: DEs → Event Definition → Assets → Journey, com avisos como \"recriar Event Source reinicia contatos em espera\".",
      "Rode a bateria de pré-voo até ficar verde.",
      "Apply: o sync_run registra tudo; rode Apply de novo com o mesmo hash — 0 mutações (idempotência).",
      "Para prod: só com aprovação decidida, certificado válido e pré-voo verde.",
    ],
    pegadinhas: [
      "Apply sem plan prévio → 409; o plan é obrigatório e recente.",
      "Apply em prod exige a tríade: aprovação (aprovado/aprovado_ressalvas) + certificado NÃO expirado + pré-voo verde — qualquer um faltando, 409.",
      "FAIL bloqueia o apply; WARN não bloqueia, mas fica registrado — leia os warns, eles viram incidentes depois.",
      "Drift em produção abre pendência bloqueante automática — resolver o drift vem antes de qualquer novo apply.",
      "Avisos destrutivos são reais: recriar Event Source reinicia contatos em espera na jornada.",
    ],
    relacionados: ["portoes", "lancamento", "twin"],
  },

  lancamento: {
    titulo: "Torre de Lançamento",
    fase: "Operação",
    destino: "os:lancamento",
    descricao:
      "Rampa canário 1% → 10% → 100% com breakers congelados, kill switch em 2 etapas e timeline de eventos.",
    oQueE: [
      "Disparo aqui nunca é um botão binário: a campanha sobe em ondas — 1%, 10%, 100% — com um QA automático entre elas. Os breakers (limites de bounce, opt-out etc.) são congelados da política no momento de armar.",
      "Se um breaker estoura durante uma onda, a rampa congela sozinha — essa é a única ação autônoma do sistema, e é a conservadora. Retomar é sempre decisão humana; incidentes SEV1 exigem dois aprovadores para retomada.",
      "O kill switch mata a campanha em 2 etapas (intenção + confirmação). Todo o caminho é 100% determinístico — zero LLM entre você e o disparo.",
    ],
    fundamentos: [
      {
        termo: "Rampa canário",
        definicao:
          "Ondas de 1% → 10% → 100% do público; cada avanço checa os breakers antes de liberar.",
      },
      {
        termo: "Breaker",
        definicao:
          "Limite objetivo congelado no armar (ex.: opt-out > 0,6%). Estourou ⇒ estado \"pausado_breaker\" automático.",
      },
      {
        termo: "Kill switch em 2 etapas",
        definicao:
          "Matar exige intenção + confirmação; após SEV1, retomar exige 2 aprovadores distintos.",
      },
      {
        termo: "Estados",
        definicao: "ARMADO → NO AR → (PAUSADO breaker) → MORTO / CONCLUÍDO — sempre visíveis no topo.",
      },
      {
        termo: "Incidente SEV1",
        definicao:
          "Ex.: disparo para contato em lista de supressão ⇒ incidente SEV1 + kill automático (guarda-corpo LGPD).",
      },
    ],
    campos: [
      { campo: "Estado do lançamento", significado: "ARMADO · ● NO AR · ‖ PAUSADO (breaker) · ■ MORTO · ✓ CONCLUÍDO." },
      { campo: "Ondas", significado: "Percentual de cada onda e a onda atual (ex.: 2/3)." },
      { campo: "Breakers", significado: "Limites congelados da política e o valor corrente de cada métrica vigiada." },
      { campo: "Timeline de eventos", significado: "Tudo que aconteceu: armar, avanço de onda, breaker, kill, retomada." },
      { campo: "Kill switch", significado: "Abortar em 2 etapas; retomada pós-SEV1 exige 2 aprovadores." },
      { campo: "Vigia", significado: "Copiloto que narra a saúde da rampa — narração, nunca ação." },
    ],
    casosDeUso: [
      "Armar o lançamento com os breakers da política congelados.",
      "Avançar de onda com segurança após checar as métricas.",
      "Reagir a um breaker disparado entendendo a causa antes de retomar.",
      "Abortar uma campanha com problema grave de forma controlada.",
    ],
    exemplo: [
      "Na OS-2026-0457 (demo em onda 2/3), abra Lançamento.",
      "Veja os breakers congelados e as métricas correntes de cada um.",
      "Clique Avançar onda: o sistema checa os breakers antes de liberar a próxima.",
      "Simule mentalmente um opt-out acima de 0,6%: o estado iria a \"PAUSADO (breaker)\" sozinho — e só um humano retomaria.",
    ],
    pegadinhas: [
      "Retomar rampa NUNCA é automático — pausar é a única ação autônoma; a retomada é sempre humana (SEV1: dois aprovadores).",
      "Disparo para contato em lista de supressão = incidente SEV1 + kill automático — o guarda-corpo é implacável.",
      "Os breakers valem como estavam NO ARMAR: publicar política nova depois não muda os limites desta campanha.",
      "Kill não é pause: morto é morto — retomar campanha morta é novo ciclo.",
    ],
    relacionados: ["prevoo", "monitor", "workflow"],
  },

  monitor: {
    titulo: "Monitoramento Dinâmico",
    fase: "Operação",
    destino: "os:monitor",
    descricao:
      "Todo KPI como par previsto × realizado contra o Previsto congelado — barra fantasma vs sólida, IC95 e reconciliação.",
    oQueE: [
      "A pergunta do monitor nunca é \"quanto deu?\", e sim \"deu o que prometemos?\". Todo KPI aparece como um par: o realizado (barra sólida) sobre o Previsto congelado no snapshot (barra fantasma) — nunca contra a simulação corrente.",
      "O lift é medido contra o holdout com intervalo de confiança de 95%: só é vitória quando o IC exclui zero. O hash do snapshot aparece no cabeçalho — você sabe exatamente contra qual promessa está comparando.",
      "A telemetria é dupla: ENS (tempo real) + extracts (conciliação diária). Divergência acima de 2% gera alerta de reconciliação. Zero LLM neste caminho — o Insight apenas narra no painel.",
    ],
    fundamentos: [
      {
        termo: "Previsto congelado",
        definicao:
          "A régua imutável gravada no snapshot pelo Ensaio Geral. Re-simular depois NÃO muda o monitor.",
      },
      {
        termo: "Barra fantasma × sólida",
        definicao:
          "Gramática visual universal da plataforma: fantasma = previsto, sólida = realizado — em todo gráfico.",
      },
      {
        termo: "Lift vs holdout",
        definicao:
          "Diferença entre expostos e controle, com IC95. Significativo = IC excluindo zero.",
      },
      {
        termo: "Telemetria dupla",
        definicao:
          "ENS em tempo real; extract é conciliação (não soma!). Divergência > 2% ⇒ alerta de dado.",
      },
    ],
    campos: [
      { campo: "Conversões", significado: "Realizado vs previsto (ex.: 271 vs 248 · +9,3%)." },
      { campo: "Lift vs holdout", significado: "Em pontos percentuais, com IC95 e selo de significância." },
      { campo: "ROAS", significado: "Retorno sobre investimento realizado vs P50 previsto." },
      { campo: "Custo real / Receita", significado: "Execução financeira vs o congelado no snapshot." },
      { campo: "Snapshot hash", significado: "Identifica a régua da comparação — a promessa aprovada." },
      { campo: "Onda atual", significado: "Em qual onda da rampa a campanha está (ex.: 2/3)." },
    ],
    casosDeUso: [
      "Acompanhar a campanha no ar contra a promessa aprovada.",
      "Detectar desvio de custo ou conversão cedo, quando ainda dá para agir.",
      "Validar o lift com rigor estatístico antes de comemorar.",
      "Conferir se a telemetria está íntegra (reconciliação ENS × extract).",
    ],
    exemplo: [
      "Na OS-2026-0457, abra o Monitor.",
      "Leia os pares: conversões 271 (prev. 248 · +9,3%), lift +24,1pp (prev. +21 · IC95 18,6–29,6 · significativo), ROAS 18,5x (prev. 15,2x).",
      "Repare na barra fantasma sob cada sólida — é o Previsto congelado.",
      "Confira o hash do snapshot no cabeçalho: é a mesma régua que o aprovador viu no link mágico.",
    ],
    pegadinhas: [
      "A régua é o Previsto do SNAPSHOT — re-simular a jornada não mexe no monitor; comparar com \"a última simulação\" é erro conceitual.",
      "Extract é conciliação, não soma: somar ENS + extract duplica números.",
      "Divergência ENS × extract > 2% é alerta de DADO (pipeline), não de campanha — investigue a telemetria antes de culpar a jornada.",
      "Lift sem IC excluindo zero não é vitória — espere a significância antes de decisões.",
    ],
    relacionados: ["lancamento", "perguntas", "retro"],
  },

  perguntas: {
    titulo: "Pergunte aos Dados",
    fase: "Operação",
    destino: "os:perguntas",
    descricao:
      "Linguagem natural → consulta NOMEADA da camada semântica, sempre com a query anexada; PII é recusada sem executar.",
    oQueE: [
      "Esta tela deixa qualquer pessoa perguntar aos números da campanha em português: \"qual o ROAS?\", \"qual canal converteu mais por real gasto?\". O agente Insight traduz para uma consulta NOMEADA da camada semântica versionada (views vw_metricas_*) — nunca SQL livre inventado.",
      "A resposta sempre anexa a consulta executada: você pode inspecionar exatamente de onde veio o número. Perguntas fora do escopo — especialmente PII, como CPF — recebem recusa padrão sem executar consulta alguma.",
      "Cada pergunta grava uma invocação no ledger via_ai (LGPD Art. 20): quem perguntou, o que rodou, o que voltou.",
    ],
    fundamentos: [
      {
        termo: "Camada semântica",
        definicao:
          "Conjunto versionado de views de métricas (custo, receita, ROAS, lift, metas). O Insight só enxerga essas views — nada de tabelas cruas.",
      },
      {
        termo: "Consulta nomeada",
        definicao:
          "A pergunta vira uma view conhecida (ex.: vw_metricas_custo_por_pedido), não um SQL ad-hoc — previsível e auditável.",
      },
      {
        termo: "Recusa de PII",
        definicao:
          "Pedidos de dado pessoal (CPF, telefone…) são recusados ANTES de qualquer execução — \"nenhuma consulta foi executada\".",
      },
      {
        termo: "Query anexada",
        definicao:
          "Todo número vem com a consulta que o produziu — o contrato de auditoria da tela.",
      },
    ],
    campos: [
      { campo: "Caixa de pergunta", significado: "Pergunta livre em português sobre os números da jornada." },
      { campo: "Chips de sugestões", significado: "Perguntas prontas de um clique (inclusive um exemplo de recusa de PII)." },
      { campo: "Resposta", significado: "Número + contexto previsto × realizado (P10/P50/P90) + a consulta executada." },
      { campo: "Badge via_ai", significado: "A invocação registrada — inspecionável como qualquer ação de IA." },
    ],
    casosDeUso: [
      "Responder rápido a um executivo sem abrir dashboard.",
      "Comparar previsto vs realizado de uma métrica específica.",
      "Descobrir o custo por pedido por canal sem escrever SQL.",
      "Demonstrar a governança: pedir um CPF e mostrar a recusa.",
    ],
    exemplo: [
      "Na OS-2026-0457, abra Pergunte aos Dados.",
      "Pergunte: \"qual canal deu mais conversão por real gasto?\" → o Insight executa vw_metricas_custo_por_pedido (R$ 14,06/pedido na demo) e anexa a query.",
      "Clique no chip com pergunta de CPF: recusa padrão — \"nenhuma consulta foi executada\".",
      "Abra o badge via_ai e veja a invocação registrada.",
    ],
    pegadinhas: [
      "O Insight só responde o que a camada semântica cobre — fora dela, recusa. Se recusar uma pergunta legítima, reformule usando o nome da métrica (o mapeamento de sinônimos foi ampliado após o UAT, A17).",
      "PII nunca sai daqui — nem tentando: a recusa acontece antes de qualquer execução.",
      "Número sem query anexada não existe nesta tela — se citar um número da plataforma em reunião, leve a query junto.",
      "Toda pergunta vira invocação auditável — inclusive as recusadas.",
    ],
    relacionados: ["monitor", "retro", "cockpit"],
  },

  retro: {
    titulo: "Otimização & Retro",
    fase: "Operação",
    destino: "os:retro",
    descricao:
      "Propostas do Optimize com impacto pré-simulado, apuração anti-peeking, clone com aprendizados e calibração.",
    oQueE: [
      "É o loop que fecha o ciclo: o agente Optimize analisa o realizado e PROPÕE mudanças ranqueadas por lift × esforço × risco — cada proposta é um diff do grafo (JGC) com impacto já pré-simulado. Aprovar dispara um mini-ciclo expresso: nova versão da jornada, re-simulação e aprovação.",
      "A apuração do experimento respeita o pré-registro: antes do fim da janela, o endpoint responde 425 Too Early (anti-peeking); e \"significativo\" só existe com intervalo de confiança excluindo zero.",
      "\"Clonar com aprendizados\" instancia a próxima campanha já herdando o que foi aceito; o Calibrate publica priors novos para o simulador — somente com backtest aprovado. Aprendizados promovidos entram na base RAG de resultados.",
    ],
    fundamentos: [
      {
        termo: "Proposta = diff + impacto",
        definicao:
          "O Optimize nunca aplica: entrega diff JGC com impacto pré-simulado e score de esforço/risco. Aprovar gera nova versão e mini-ciclo M8→M9.",
      },
      {
        termo: "Anti-peeking (425)",
        definicao:
          "Apurar antes da janela devolve 425 Too Early — espiar resultado parcial destrói a validade estatística do experimento.",
      },
      {
        termo: "Significância",
        definicao: "significativo = true SOMENTE com IC95 excluindo zero. Sem isso, é ruído.",
      },
      {
        termo: "Clone com aprendizados",
        definicao:
          "Nova OS herdando aprendizados aceitos e priors atualizados (campo herdado_de) — a próxima campanha começa mais inteligente.",
      },
      {
        termo: "Calibração",
        definicao:
          "Ajuste dos priors do simulador com backtest obrigatório — previsões futuras ficam mais honestas.",
      },
    ],
    campos: [
      { campo: "Propostas do Optimize", significado: "Ranqueadas por lift × esforço × risco, cada uma com diff JGC e impacto pré-simulado." },
      { campo: "Apuração do experimento", significado: "Lift, IC95, significância e ROAS — liberada só após a janela." },
      { campo: "Clonar com aprendizados", significado: "Cria a próxima OS herdando o que foi aceito." },
      { campo: "Calibração", significado: "Priors novos + backtest; publicar exige backtest aprovado." },
    ],
    casosDeUso: [
      "Colher propostas de otimização com impacto estimado antes de mexer.",
      "Apurar o experimento com rigor no fim da janela.",
      "Clonar a campanha para a próxima onda já otimizada.",
      "Publicar priors calibrados para melhorar as próximas simulações.",
    ],
    exemplo: [
      "Na OS-2026-0457, abra Otimização · Retro.",
      "Analise as propostas do Optimize — cada uma com diff e impacto pré-simulado.",
      "Aprove uma proposta: nasce nova versão da jornada e o mini-ciclo expresso (re-simular → re-aprovar).",
      "Tente apurar o experimento antes da janela: 425 Too Early. Depois da janela: lift com IC95 e significância.",
      "Clone com aprendizados para a próxima campanha.",
    ],
    pegadinhas: [
      "Apurar antes da janela → 425 Too Early: não é bug, é proteção estatística (anti-peeking) do pré-registro.",
      "\"Significativo\" exige IC excluindo zero — lift positivo com IC cruzando zero é ruído, não resultado.",
      "Aprovar proposta NÃO publica nada: dispara o mini-ciclo com nova simulação e nova aprovação — os QAs continuam valendo.",
      "Calibração sem backtest aprovado não publica priors.",
      "Só aprendizados ACEITOS são herdados no clone — registre o aceite, senão a próxima campanha começa do zero.",
    ],
    relacionados: ["monitor", "twin", "atelie"],
  },

  atelie: {
    titulo: "Ateliê de Agentes",
    fase: "Plataforma",
    destino: "/atelie",
    descricao:
      "Roster por etapa, SKILL.md visível, harness como QA de publicação, policy-as-code e auditoria via_ai.",
    oQueE: [
      "O Ateliê é a sala de máquinas da IA: o roster de agentes organizado por etapa do workflow, cada um com versão publicada, perfil de modelo (120B/20B), SKILL vinculada e score no harness. O system prompt (SKILL.md canônico) é visível — nada de caixa-preta.",
      "O ciclo de vida é no-code: editar a skill → rodar o harness (bateria de casos golden julgada por um judge 120B em correção, evidência, compliance e formato) → publicar. Harness verde (≥ 90 por dimensão) é o QA de release.",
      "Aqui também vivem as políticas (policy-as-code: caps, quiet hours, alçadas, breakers — draft → publicada) e a auditoria: todo evento via_ai é clicável (prompt + evidências + judge + humano) e reconstruível (LGPD Art. 20).",
    ],
    fundamentos: [
      {
        termo: "SKILL.md canônico",
        definicao:
          "Front-matter YAML (nome, versão, perfil, bases RAG, exige_evidencia) + corpo com as instruções. É o contrato do agente, versionado.",
      },
      {
        termo: "Harness como QA",
        definicao:
          "Casos golden + judge 120B com rubrica fixa; publicar exige score ≥ 90 em TODAS as dimensões — senão 409.",
      },
      {
        termo: "Frozen protege o voo",
        definicao:
          "Publicar skill/política nova NÃO altera campanhas em voo: elas rodam com as versões congeladas no GO.",
      },
      {
        termo: "Policy-as-code",
        definicao:
          "Frequency cap, quiet hours, blackout, holdout mínimo, alçadas, retenção e breakers como configuração versionada draft → publicada.",
      },
      {
        termo: "Auditoria / reconstrução",
        definicao:
          "Qualquer invocação pode ser reconstruída: input, evidências e output exatamente da época (Art. 20).",
      },
    ],
    campos: [
      { campo: "Roster por etapa", significado: "Agentes agrupados pela etapa do workflow, com versão, perfil 120b/20b e score." },
      { campo: "Painel do agente", significado: "SKILL.md visível, bases RAG autorizadas, execution profile." },
      { campo: "Harness", significado: "Rodar a bateria golden; score por dimensão; histórico de runs." },
      { campo: "Dry-run lado a lado", significado: "Comparar a skill editada com a publicada no mesmo input." },
      { campo: "Políticas", significado: "Conteúdo da política, estado draft/publicada e relatório de policy drift sobre OSs em voo." },
      { campo: "Auditoria", significado: "Trilha de eventos via_ai com filtros; clique abre prompt+evidências+judge+humano." },
    ],
    casosDeUso: [
      "Refinar o prompt de um agente sem escrever código e medir no harness.",
      "Publicar uma versão nova com segurança (QA de qualidade).",
      "Alterar a política de contato (caps, quiet hours) com versionamento.",
      "Auditar uma decisão assistida por IA de ponta a ponta.",
    ],
    exemplo: [
      "Abra o Ateliê e localize o Engineer na etapa de audiência.",
      "Leia o SKILL.md: exige_evidencia: true e as bases dicionario_dados, historico_campanhas — é por isso que ele recusa sem RAG.",
      "Edite a skill, rode o harness e tente publicar com score < 90: 409.",
      "Na auditoria, clique num evento via_ai da OS-2026-0457 e reconstrua a invocação: input, evidências e output da época.",
    ],
    pegadinhas: [
      "Harness < 90 em qualquer dimensão → 409: não publica — o QA vale até para o admin.",
      "Publicar skill NÃO muda campanhas em voo (frozen do GO) — a versão nova só vale para OSs novas ou próximo GO.",
      "O Guard não aparece como skill editável de LLM: ele é determinístico por definição — o 20B apenas explica o veredito.",
      "Mudar EMBED_DIM exige re-embed completo da base RAG — a busca fica indisponível durante o reindex (aviso na UI).",
      "No demo, triagens aparecem zeradas e harness \"sem run\" (achado A18) — o roster completo do §7.2 prevê 5 triagens.",
    ],
    relacionados: ["cockpit", "retro", "perguntas"],
  },
};

/** Resolve a chave do guia a partir do pathname atual. */
export function chaveDaRota(pathname: string): ChaveGuia {
  if (pathname === "/") return "cockpit";
  if (pathname.startsWith("/atelie")) return "atelie";
  if (pathname.startsWith("/aprovacao")) return "aprovacao";
  const sub = pathname.split("/")[3];
  if (sub && sub in CONTEUDO_GUIA) return sub as ChaveGuia;
  return "cockpit";
}

/** Href navegável de uma página do guia (null = não navegável no contexto atual). */
export function hrefDaChave(chave: ChaveGuia, osAtualId: string | null): string | null {
  const destino = CONTEUDO_GUIA[chave].destino;
  if (!destino) return null;
  if (destino.startsWith("os:")) {
    return osAtualId ? `/os/${osAtualId}/${destino.slice(3)}` : null;
  }
  return destino;
}
