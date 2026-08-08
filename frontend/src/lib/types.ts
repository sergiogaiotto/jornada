/**
 * Tipos do contrato de API — espelham 1:1 os modelos Pydantic dos routers do SDD §8
 * (backend/api/v1). Nunca inventar campo fora do SDD (§1.3.5).
 */

// ---------------------------------------------------------------- RFC-7807 (§8)
export interface Problem {
  type?: string;
  title?: string;
  status?: number;
  detail?: string;
  instance?: string;
  /** extras de domínio, ex.: `pendencias`, `campos_nao_decididos`, `modo: "degraded"` */
  [extra: string]: unknown;
}

// ------------------------------------------------------------------- M1 · OS
export type FaseOs =
  | "pensada"
  | "discutida"
  | "criada"
  | "avaliada"
  | "configurada"
  | "disparada"
  | "monitorada"
  | "encerrada";

export type Tshirt = "P" | "M" | "G" | "GG";

/** Entrada de campo do briefing (§8-M3): `{valor, inferido, evidencias?}` — ou valor cru. */
export interface CampoBriefing {
  valor: unknown;
  inferido: boolean;
  evidencias?: unknown[];
}

export type Briefing = Record<string, CampoBriefing | unknown>;

export interface OsOut {
  id: string;
  tenant_id: string;
  codigo: string;
  nome: string;
  tshirt: Tshirt | string;
  fase: FaseOs | string;
  briefing: Briefing;
  frozen: Record<string, unknown> | null;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface PendenciaOut {
  id: string;
  os_id: string;
  numero: number;
  tipo: string | null;
  titulo: string;
  descricao: string | null;
  severidade: "baixa" | "media" | "alta" | null;
  bloqueante: boolean;
  bloqueia_etapa: string | null;
  status: "aberta" | "resolvida" | "aceita" | string;
  accountable: string | null;
  aceite: Record<string, unknown> | null;
  origem: string | null;
  via_ai: boolean;
  created_at: string;
}

export interface SaudeOut {
  os_id: string;
  saude: "normal" | "em_risco";
}

// ---------------------------------------------------------------- M3 · Intake
export type EstadoPedido = "rascunho" | "completo" | "convertido" | "arquivado";

/** Os 5 campos obrigatórios do pedido (espelho de CAMPOS_OBRIGATORIOS §8-M3) —
 * ordem canônica = ordem em que `faltantes` é reportado pelo backend. */
export const CAMPOS_PEDIDO: { campo: string; rotulo: string; dica: string }[] = [
  { campo: "objetivo", rotulo: "Objetivo", dica: "o que a campanha precisa alcançar" },
  { campo: "publico", rotulo: "Público", dica: "quem será abordado" },
  { campo: "oferta", rotulo: "Oferta", dica: "o que será ofertado" },
  { campo: "verba", rotulo: "Verba", dica: "orçamento (ex.: R$ 500 mil)" },
  { campo: "janela", rotulo: "Janela", dica: "período do disparo (ex.: 01–15/09)" },
];

export interface PedidoOut {
  id: string;
  tenant_id: string;
  solicitante: Record<string, unknown>;
  conteudo: Briefing;
  completude: number;
  faltantes: string[];
  estado: EstadoPedido;
  os_id: string | null;
  updated_at: string | null;
}

/** Item de `GET /pedidos` (emenda §8-M3): resumo SEM `conteudo`. */
export interface PedidoResumo {
  id: string;
  solicitante: Record<string, unknown>;
  completude: number;
  faltantes: string[];
  estado: EstadoPedido;
  os_id: string | null;
  updated_at: string | null;
}

export interface MensagemOut {
  resposta: string;
  conteudo: Briefing;
  completude: number;
  faltantes: string[];
  estado: EstadoPedido;
}

export interface BriefingOut {
  os_id: string;
  briefing: Briefing;
}

// ------------------------------------------------------------- M4 · Validação
export interface ChecagemOut {
  tipo: string; // contagem|schema|frescor|fonte
  ok: boolean;
  detalhe: string;
}

/** Decisão VIGENTE da checagem de um campo (uma por campo — emenda B01). */
export interface ValidacaoOut {
  id: string;
  os_id: string;
  campo: string;
  veredito: "ok" | "falha";
  checagens: ChecagemOut[];
  evidencia: Record<string, unknown>;
  created_at: string; // primeira checagem do campo
  por: string | null; // quem executou a checagem vigente
  atualizado_em: string | null; // quando (null em linhas anteriores à emenda B01)
}

export interface MensagemThreadOut {
  autor: string;
  texto: string;
  em: string;
}

export interface ThreadOut {
  id: string;
  os_id: string;
  campo: string;
  titulo: string | null;
  mensagens: MensagemThreadOut[];
  status: "aberta" | "resolvida";
  created_at: string;
}

export interface DocumentoPortaoOut {
  id: string;
  os_id: string;
  portao: string;
  nome_arquivo: string;
  tamanho_bytes: number;
  hash: string;
  created_at: string;
}

export interface GoOut {
  os: OsOut;
  documento: DocumentoPortaoOut;
}

// -------------------------------------------------------------- M2 · Esteira
export interface ChecklistItemOut {
  item: string;
  feito: boolean;
  por?: string | null;
  em?: string | null;
}

export interface EtapaOut {
  id: string;
  os_id: string;
  ordem: number;
  nome: string; // briefing|discovery|audiencia|criativos|configuracao|disparo|acompanhamento
  responsavel: string | null;
  sla_dias: number | null;
  estado: "pendente" | "em_andamento" | "concluida" | "bloqueada" | string;
  checklist: ChecklistItemOut[];
  dependencias: string[];
  hike_ref: Record<string, unknown> | null;
}

export interface WorkflowOut {
  os_id: string;
  etapas: EtapaOut[];
}

// -------------------------------------------------- M5 · Audiência (T5/T5a)
/** Etapa do waterfall (§4.1): `{etapa, corte, restante, motivo}`. */
export interface EtapaWaterfall {
  etapa: string;
  corte: number;
  restante: number;
  motivo: string;
}

/** Volume de abordagem por canal (§8-M5-A2): n ≤ líquido, pct sobre o líquido. */
export interface VolumeCanal {
  n: number;
  pct: number;
}

export interface SegmentoOut {
  id: string;
  os_id: string | null;
  origem: "estudio_sql" | "data_cloud";
  dc_segment_id: string | null;
  sql_publico: string | null;
  criterios_resumo: string | null;
  contagem_bruta: number | null;
  contagem_liquida: number | null;
  waterfall: EtapaWaterfall[];
  volume_abordagem: Record<string, VolumeCanal>;
  holdout_pct: number;
  /** {fonte: ultima_atualizacao ISO} — frescor por fonte (§8-M5-A4) */
  frescor: Record<string, string>;
}

/** Prévia do engineer (roster §7.2): SQL + explicação por cláusula + evidências. */
export interface GerarSqlOut {
  segmento: SegmentoOut;
  explicacao: Record<string, string>[];
  evidencias: string[];
  avisos: string[];
  via_ai: boolean;
  invocacao_id: string;
}

export interface CertificadoOut {
  id: string;
  os_id: string;
  hash: string;
  /** {lista: contagem} — as 7 listas (§4.1) */
  suprimidos: Record<string, number>;
  liquido: number;
  emitido_em: string;
  valido_ate: string | null;
  last_mile: Record<string, unknown> | null;
}

/** Linha de `dc_segment_cache` (§4.1) — consulta ao Data Cloud, não cópia (T5a). */
export interface DcSegmentoOut {
  id: string;
  nome: string | null;
  criterios_resumo: string | null;
  membros: number | null;
  dmos: string[];
  republicado_em: string | null;
  ciclo: string | null;
  status: string | null;
  atualizado_em: string | null;
}

/** Relatório T5a (§8-M5): funil, waterfall, sobreposição, volume por canal, frescor. */
export interface RelatorioDcOut {
  segmento: {
    id: string;
    nome: string | null;
    criterios_resumo: string | null;
    dmos: string[];
    ciclo: string | null;
    status: string | null;
    republicado_em: string | null;
  };
  funil: { bruto: number; elegivel: number; liquido: number };
  waterfall: EtapaWaterfall[];
  sobreposicao: Record<string, number>;
  volume_abordagem: Record<string, VolumeCanal>;
  /** por canal — vêm do governor (§8-M5-A2) */
  colisoes: Record<string, number>;
  frescor: Record<string, string>;
}

// ------------------------------------------------------------ M6 · Criativo
export type CanalCriativo = "email" | "sms" | "push" | "whatsapp";

export type EstadoCelula = "gerado" | "aprovado" | "revisar" | "adaptado_revisar";

/** Conteúdo por canal (§4.1 criativo): {assunto?, titulo?, mensagem, cta?, template?}. */
export interface ConteudoCelula {
  assunto?: string;
  titulo?: string;
  mensagem?: string;
  cta?: string;
  template?: string;
  [extra: string]: unknown;
}

export interface CelulaOut {
  canal: CanalCriativo;
  variante: string;
  conteudo: ConteudoCelula;
  estado: EstadoCelula;
  aprovada_por: string | null;
  aprovada_em: string | null;
  observacao: string | null;
}

export interface CriativoOut {
  id: string;
  os_id: string;
  kv_master: Record<string, unknown>;
  kv_master_ref: string | null;
  celulas: CelulaOut[];
  created_at: string | null;
  updated_at: string | null;
}

export interface GerarCriativosOut {
  criativo: CriativoOut;
  avisos: string[];
  via_ai: boolean;
  invocacao_ids: string[];
}

export interface KvMasterOut {
  criativo: CriativoOut;
  avisos: string[];
}

/**
 * KV master de PARTIDA do Estúdio (GET /os/{id}/criativos/kv-padrao) — derivado do
 * briefing da OS por código determinístico (`via_ai:false`). `suficiente:false` → veio
 * com placeholders "(defina …)"; nunca copy de outra campanha (§8-M6, achado A8).
 */
export interface KvPadraoOut {
  os_id: string;
  kv_master: Record<string, string>;
  derivado_de: string[];
  suficiente: boolean;
  via_ai: boolean;
}

// --------------------------------------------------------- M7 · Twin Canvas
/** Nó do JGC (§5.2 — tipos fechados; o validador rejeita fora da lista). */
export interface NoJgc {
  id: string;
  type: string;
  data: Record<string, unknown>;
}

export interface ArestaJgc {
  id: string;
  from: string;
  to: string;
  cond?: string | null;
}

/** JGC — Journey Graph Canônico (§5.1). */
export interface GrafoJgc {
  jgcVersion: string;
  meta: {
    osCodigo?: string;
    tenant?: string;
    reentrada?: string;
    quietHours?: { inicio: string; fim: string } | null;
    [extra: string]: unknown;
  };
  nodes: NoJgc[];
  edges: ArestaJgc[];
}

export interface JornadaOut {
  id: string;
  os_id: string;
  versao: number;
  grafo: GrafoJgc;
  hash: string;
  estado: string;
  premissas: string[];
  custo_projetado: number | null;
  created_at?: string | null;
}

/** Item de `GET /os/{id}/jornadas` (emenda §8-M7): linha do tempo SEM grafo. */
export interface JornadaResumoOut {
  id: string;
  versao: number;
  estado: string;
  hash: string;
  custo_projetado: number | null;
  created_at: string | null;
}

/** `GET /jornadas/{a}/diff/{b}` (emenda §8-M7) — mesmo diff.py do ajustar/M11. */
export interface DiffVersoesOut {
  de: { id: string; versao: number; hash: string };
  para: { id: string; versao: number; hash: string };
  nodes: DiffIds;
  edges: DiffIds;
  meta_alterada: boolean;
}

/** Item da memória do taxímetro (§8-M7-A2): volume × tarifa por nó de canal. */
export interface ItemMemoriaTaximetro {
  no: string;
  canal: string;
  volume: number;
  tarifa: string;
  custo: string;
}

export interface TaximetroOut {
  custo_projetado: number;
  memoria: ItemMemoriaTaximetro[];
  avisos: string[];
}

export interface GerarJornadaOut {
  jornada: JornadaOut;
  resumo: string;
  taximetro: TaximetroOut;
  via_ai: boolean;
  invocacao_id: string;
}

export interface GrafoOut {
  jornada: JornadaOut;
  taximetro: TaximetroOut;
}

export interface DiffIds {
  adicionados: string[];
  removidos: string[];
  alterados: string[];
}

/** Diff PROPOSTO (§8-M7): nunca aplicado — aplicar é PUT humano do grafo proposto. */
export interface AjustarOut {
  jornada_id: string;
  aplicado: boolean;
  grafo_proposto: GrafoJgc;
  diff: { nodes: DiffIds; edges: DiffIds; meta_alterada: boolean };
  premissas: string[];
  resumo: string;
  valido: boolean;
  erros: { no?: string; regra?: string; mensagem?: string }[];
  custo_projetado_atual: number | null;
  custo_projetado_proposto: number;
  avisos: string[];
  via_ai: boolean;
  invocacao_id: string;
}

// ------------------------------------------- M8 (parte 1) · Simulador T8 (§6)
/** Percentis padrão do Ensaio Geral (§6): P10/P50/P90. */
export interface P105090 {
  p10: number;
  p50: number;
  p90: number;
}

export type Semaforo = "verde" | "amarelo" | "vermelho";

export interface PressaoCanal {
  msgs_por_contato: P105090;
  cap_janela: number | null;
  colisao_critica: boolean;
}

export interface Gargalo {
  no: string;
  tipo: string;
  espera_horas_p50: number;
}

/** Validação de poder (§6): insuficiente ⇒ QA experimento vermelho (A2). */
export interface PoderOut {
  aplicavel: boolean;
  portao: string; // verde|vermelho|nao_aplicavel
  suficiente?: boolean | null;
  n_disponivel?: number;
  n_minimo?: number;
  mde_pp?: number;
  poder?: number;
  poder_minimo?: number;
  detalhe?: string;
}

/** Saída do motor Monte Carlo (§6) persistida em `jornada_versao.simulacao`. */
export interface SimulacaoResultado {
  runs: number;
  n_personas: number | null;
  volume_entrada: number;
  funil: Record<string, P105090 & { tipo: string }>;
  conversoes: P105090;
  custo: P105090;
  receita: P105090;
  roas: P105090 | null;
  lift_pp: P105090;
  horas_ate_concluir: P105090;
  pressao_contato: Record<string, PressaoCanal>;
  gargalos: Gargalo[];
  poder: PoderOut;
  semaforo: Semaforo;
  motivos_semaforo: string[];
  portoes: { experimento: string };
  avisos: string[];
  premissas: string[];
  parametros: {
    seed: number;
    runs: number;
    n_personas: number;
    segmento_id: string;
    ticket_medio: number;
    priors_versao: unknown;
  };
  executada_em: string;
  /** presentes só no bloco `previsto` (congelar-previsto) */
  congelado_em?: string;
  congelado_por?: string;
}

export interface JornadaSimuladaOut {
  id: string;
  os_id: string;
  versao: number;
  hash: string;
  estado: string;
  simulacao: SimulacaoResultado | null;
  previsto: SimulacaoResultado | null;
}

export interface CenarioComparado {
  jornada_id: string;
  os_id: string;
  versao: number;
  semaforo: Semaforo;
  p50: Record<string, number | null>;
  parametros: Record<string, unknown>;
  delta_vs_baseline: Record<string, number | null>;
}

export interface CompararOut {
  baseline: string;
  cenarios: CenarioComparado[];
}

// ----------------------------- M8 (parte 2) · QA T9 + Aprovação T10 (§8-M8)
export type EstadoPortao = "verde" | "vermelho" | "pendente";

/** QA do painel T9 — campos extras variam por QA (hash, faixa, poder…). */
export interface PortaoOut {
  estado: EstadoPortao;
  motivo?: string | null;
  [extra: string]: unknown;
}

export interface PortoesOut {
  os_id: string;
  portoes: {
    certificado: PortaoOut;
    experimento: PortaoOut;
    custo_alcada: PortaoOut;
    governor: PortaoOut;
    /** §8-M8-A8 (D09): a cor do Ensaio é portão — vermelho recusa o snapshot. */
    simulacao: PortaoOut;
  };
  aprovacao: PortaoOut;
}

export interface ExperimentoOut {
  id: string;
  os_id: string;
  holdout_pct: number;
  n_minimo: number;
  mde_pp: number;
  janela_dias: number;
  metricas: Record<string, unknown>;
  travado_em: string | null;
  estado: string;
}

export interface ExperimentoPreRegistradoOut {
  experimento: ExperimentoOut;
  poder: Record<string, unknown>;
}

export interface FaixaAlcada {
  ate: number;
  papel: string;
}

export interface AlcadaOut {
  os_id: string;
  custo_previsto: number;
  faixa: FaixaAlcada;
  enviado_em: string;
  enviado_por: string;
}

export interface SnapshotOut {
  id: string;
  os_id: string;
  hash: string;
  conteudo: Record<string, unknown>;
  previsto: SimulacaoResultado | null;
  created_at: string | null;
}

/** Token retornado UMA única vez (§8-M8-A3) — nunca persistido em claro. */
export interface LinkMagicoOut {
  aprovacao_id: string;
  snapshot_id: string;
  token: string;
  url: string;
  alcada: string;
  /** A6 (§10.5): a quem o link foi ENDEREÇADO — o servidor recusa o criador do snapshot. */
  aprovador_email: string;
  expira_em: string;
}

export type DecisaoAprovacao = "aprovado" | "aprovado_ressalvas" | "reprovado";

export interface RessalvaRegistrada {
  texto: string;
  pendencia_numero: number;
}

/** Página standalone do link mágico (GET /aprovacao/{token} — §8-M8). */
export interface AprovacaoPayloadOut {
  os: { codigo: string; nome: string; fase: string };
  snapshot: { id: string; hash: string; created_at: string | null };
  alcada: string;
  /** A6 (§10.5): quem o servidor vai registrar como decisor — null em link antigo. */
  aprovador_email: string | null;
  expira_em: string;
  resumo: {
    custo: { previsto_p50: number; moeda: string };
    politica_versao: number;
    experimento: {
      id: string;
      holdout_pct: number;
      n_minimo: number;
      mde_pp: number;
      janela_dias: number;
    } | null;
    jgc: { jornada_id: string; versao: number; hash: string };
  };
  waterfall: EtapaWaterfall[] | null;
  volume_abordagem: Record<string, VolumeCanal> | null;
  criativos: { id: string; celulas: Record<string, string> }[];
  previsto: SimulacaoResultado | null;
  decisao: DecisaoAprovacao | null;
  decidido_em: string | null;
  ressalvas: RessalvaRegistrada[];
  invalidada: boolean;
  invalidada_motivo: string | null;
}

export interface DecisaoOut {
  id: string;
  snapshot_id: string;
  alcada: string;
  decisao: DecisaoAprovacao;
  decidido_em: string;
  decidido_meta: Record<string, unknown>;
  ressalvas: RessalvaRegistrada[];
  pendencias_criadas: number[];
}

// --------------------------------------- M9 · Compilador & Pré-voo T11 (§5.4, §8-M9)
export type AmbienteSync = "homolog" | "prod";

export type AcaoPlano = "criar" | "alterar" | "manter" | "destruir";

/** Item do plano declarativo (§5.4.1): externalKey `jrn-{hash[0:12]}-{noId}`. */
export interface ItemPlano {
  recurso: string;
  tipo_sfmc: string;
  no_jgc?: string | null;
  acao: AcaoPlano;
  aviso: string | null;
  payload?: Record<string, unknown>;
  [extra: string]: unknown;
}

export interface SyncRunOut {
  id: string;
  snapshot_id: string;
  ambiente: string;
  fase: "plan" | "apply";
  plano: ItemPlano[] | null;
  resultado: Record<string, unknown> | null;
  estado: "pendente" | "ok" | "parcial" | "revertido" | "falhou";
  api_calls: number;
  created_at: string | null;
}

export interface ItemPreflight {
  item: string;
  /** `n/a` (C04): item que NÃO pôde ser verificado (sem insumo para comparar) — não
   *  bloqueia, mas também não conta como aprovação (a bateria não fica verde). */
  status: "pass" | "warn" | "fail" | "n/a";
  evidencia: Record<string, unknown>;
  [extra: string]: unknown;
}

export interface PreflightOut {
  id: string;
  snapshot_id: string;
  ambiente: string;
  resultado: Semaforo;
  itens: ItemPreflight[];
  created_at: string | null;
}

export interface DriftCheckOut {
  id: string;
  snapshot_id: string;
  recurso: string;
  estado: "em_sincronia" | "drift_sfmc" | "twin_a_frente";
  diff: Record<string, unknown>;
  resolucao: "adopt" | "enforce" | "excecao" | null;
  checked_at: string | null;
}

// ------------------------------------------- M10 · Torre de Lançamento T12 (§8-M10)
export type EstadoLaunch = "armado" | "em_rampa" | "pausado_breaker" | "morto" | "concluido";

export interface OndaLaunch {
  pct: number;
  [extra: string]: unknown;
}

/** Entrada do histórico auditável da rampa (`launch.eventos` §4.1). */
export interface EventoLaunch {
  tipo: string;
  por?: string;
  em?: string;
  [extra: string]: unknown;
}

export interface LaunchOut {
  id: string;
  snapshot_id: string;
  ondas: OndaLaunch[];
  onda_atual: number;
  estado: EstadoLaunch;
  breakers: Record<string, number>;
  eventos: EventoLaunch[];
}

export interface KillOut {
  etapa: 1 | 2;
  confirmacao: string | null;
  launch: LaunchOut;
}

export interface RetomarOut {
  retomado: boolean;
  aprovacoes: number;
  exigidas: number;
  launch: LaunchOut;
}

/** Disparo de breaker (409 `disparos` — §8-M10): veredito por código. */
export interface DisparoBreaker {
  breaker: string;
  valor: number;
  limite: number;
  sev: string;
  kill: boolean;
  detalhe: string;
  [extra: string]: unknown;
}

// ------------------------------------ M10 (parte 2) · Monitor T13 (§8-M10)
/** TODO KPI do monitor é PAR `{previsto, realizado}` (§1.1.2). */
export interface Par<P = unknown, R = unknown> {
  previsto: P;
  realizado: R;
}

/** Lift realizado vs holdout (monitor.py): pp + IC95 + significância (§8-M11-A2). */
export interface LiftRealizado {
  valor_pp: number | null;
  ic95_pp: [number, number] | null;
  significativo: boolean | null;
  n_tratado?: number;
  n_holdout?: number;
  conversoes_tratado?: number;
  conversoes_holdout?: number;
  detalhe?: string;
}

export interface CanalMonitor {
  disparos: Par<number | null, number>;
  custo: Par<number | null, number>;
}

export interface ReconciliacaoTipo {
  ens: number;
  extract: number;
  divergencia_pct: number;
  acima_limite: boolean;
}

export interface AlertaReconciliacao {
  id: string;
  sev: string;
  tipo: string;
  titulo: string;
}

export interface MonitorOut {
  os: { id: string; codigo: string; nome: string; fase: string };
  snapshot: { id: string; hash: string; previsto_congelado_em: string | null };
  launch: {
    id: string;
    estado: EstadoLaunch;
    onda_atual: number;
    ondas: OndaLaunch[];
  } | null;
  kpis: {
    conversoes: Par<P105090 | null, number>;
    lift_pp: Par<P105090 | null, LiftRealizado>;
    roas: Par<P105090 | null, number | null>;
    custo: Par<P105090 | null, number>;
    receita: Par<P105090 | null, number>;
  };
  canais: Record<string, CanalMonitor>;
  metas: Record<string, Par<number | null, number | null>>;
  fontes: { ens: number; extract: number };
  premissas: string[];
  reconciliacao: {
    limite_pct: number;
    por_tipo: Record<string, ReconciliacaoTipo>;
    divergencias: string[];
    divergente: boolean;
    alertas: AlertaReconciliacao[];
  };
}

// ------------------------------ M10 (parte 3) · Pergunte aos Dados T14 (§8-M10)
/** A consulta NOMEADA executada — sempre anexada à resposta (§8-M10). */
export interface ConsultaExecutadaOut {
  nome: string; // vw_metricas_*
  metrica: string;
  versao: string;
  parametros: Record<string, unknown>;
  sql: string;
  resultado: Record<string, unknown>;
}

export interface PerguntaOut {
  resposta: string;
  recusado: boolean;
  motivo_recusa: string | null;
  consulta_executada: ConsultaExecutadaOut | null;
  camada_semantica: { versao?: string; consultas?: string[]; [extra: string]: unknown };
  via_ai: boolean;
  invocacao_id: string;
}

// -------------------------------- M11 · Otimização/Retro/Calibração T15 (§8-M11)
/** Proposta do optimize: diff JGC + impacto PRÉ-SIMULADO + ranking (§8-M11). */
export interface PropostaOut {
  id: string;
  os_id: string;
  jornada_base_id: string;
  titulo: string;
  motivacao: string;
  diff: { nodes: DiffIds; edges: DiffIds; meta_alterada: boolean };
  impacto: {
    base: Record<string, number | null>;
    proposto: Record<string, number | null>;
    deltas: Record<string, number | null>;
    semaforo_proposto?: string;
    parametros?: Record<string, unknown>;
  };
  esforco: number;
  risco: number;
  score: number;
  estado: "proposta" | "aprovada" | "rejeitada" | string;
  motivo_rejeicao: string | null;
  jornada_gerada_id: string | null;
  via_ai: boolean;
  decidido_por: string | null;
  decidido_em: string | null;
  created_at: string | null;
}

export interface PropostasOut {
  os_id: string;
  propostas: PropostaOut[];
  geradas_agora: boolean;
  resumo?: string;
  degradado?: boolean;
  avisos: unknown[];
}

export interface AprovarPropostaOut {
  proposta: PropostaOut;
  jornada: {
    id: string;
    versao: number;
    hash: string;
    estado: string;
    custo_projetado: number | null;
  };
  mini_ciclo: { aprovacao_expressa_necessaria: boolean; passos: string[] };
}

export interface RejeitarPropostaOut {
  proposta: PropostaOut;
  sinal: { id: string };
}

/** Resultado da apuração (§4.1 `experimento.resultado`): lift, IC95, significativo. */
export interface ApuracaoOut {
  experimento_id: string;
  estado: string;
  resultado: {
    lift: number | null;
    ic95: [number, number] | null;
    significativo: boolean | null;
    roas: number | null;
    detalhe: Record<string, unknown>;
  };
  aprendizado: { id: string; status: string };
}

export interface AprendizadoHerdado {
  id: string;
  origem: string;
  status: string;
  texto: string;
  herdado_de: string;
}

export interface CloneOut {
  os: { id: string; codigo: string; nome: string; tshirt: string; fase: string };
  origem: { id: string; codigo: string };
  herdados: { aprendizados: AprendizadoHerdado[]; priors: Record<string, unknown> };
}

export interface CalibracaoOut {
  id: string;
  tenant_id: string;
  tipo_campanha: string | null;
  versao: number;
  priors: Record<string, unknown>;
  score: number;
  backtest: Record<string, unknown>;
  publicada_em: string;
}

// ----------------------------------------------- M12 · Ateliê T16 (§8-M12, §7)
export interface SkillResumoOut {
  id: string;
  versao: string;
  estado: "draft" | "em_revisao" | "publicada" | string;
  harness_score: number | null;
  publicada_em: string | null;
}

export interface AgenteOut {
  id: string;
  tenant_id: string;
  nome: string;
  camada: "maestro" | "triagem" | "especialista" | string;
  etapa_workflow: string | null;
  modelo_perfil: "120b" | "20b" | null;
  deterministico: boolean;
  versao_publicada: string | null;
  skills: SkillResumoOut[];
}

export interface HarnessRunOut {
  id: string;
  skill_versao_id: string;
  score: number | null;
  passou: boolean | null;
  score_por_dimensao: Record<string, number> | null;
  dimensoes_reprovadas: string[] | null;
  casos: number;
  created_at: string | null;
}

export interface SkillOut extends SkillResumoOut {
  agente_id: string;
  skill_md: string;
  execution_profile: Record<string, unknown>;
  bases_rag: string[];
  harness_runs: HarnessRunOut[];
}

export interface DryRunLado {
  skill_id: string;
  versao: string;
  estado: string;
  saida: string;
}

export interface DryRunOut {
  agente: string;
  entrada: Record<string, unknown>;
  atual: DryRunLado | null;
  candidata: DryRunLado | null;
  avisos: string[];
}

/** Detalhe do ledger `invocacao` embutido no evento via_ai (GET /auditoria — §8-M12).
 * `tokens`/`latencia_ms` são `number | null` por CONTRATO (I04): null = o provedor não
 * mandou usage — ausência de medida, exibida como "—", jamais como 0. */
export interface InvocacaoDetalheOut {
  invocacao_id: string;
  os_id: string | null;
  agente_id: string | null;
  agente: string | null;
  skill_versao: string | null;
  usuario_portador: string;
  // J05: conteúdo do Art. 20 — objeto/null para dpo|lider|admin; string de redação
  // ("[restrito ...]") para os demais papéis. As métricas (tokens/latência) sempre vêm.
  input: Record<string, unknown> | string | null;
  output: Record<string, unknown> | string | null;
  evidencias: unknown[] | string;
  judge: Record<string, unknown> | string | null;
  aceito_por: string | null;
  aceito_em: string | null;
  tokens: number | null;
  latencia_ms: number | null;
  created_at: string | null;
}

export interface EventoAuditoriaOut {
  id: number;
  tipo: string;
  os_id: string | null;
  actor: string | null;
  via_ai: boolean;
  payload: Record<string, unknown>;
  created_at: string | null;
  invocacao?: InvocacaoDetalheOut | null;
}

export interface AuditoriaOut {
  eventos: EventoAuditoriaOut[];
  total: number;
  limit: number;
  offset: number;
}

// ------------------------------------------------------------------ helpers
/** Normaliza a entrada de campo do briefing para `{valor, inferido}`. */
export function campoBriefing(entrada: CampoBriefing | unknown): CampoBriefing {
  if (
    typeof entrada === "object" &&
    entrada !== null &&
    "valor" in (entrada as Record<string, unknown>)
  ) {
    const e = entrada as CampoBriefing;
    return { valor: e.valor, inferido: Boolean(e.inferido), evidencias: e.evidencias };
  }
  return { valor: entrada, inferido: false };
}

/** Renderização amigável de um valor de campo do briefing. */
export function valorLegivel(valor: unknown): string {
  if (valor === null || valor === undefined) return "—";
  if (typeof valor === "string") return valor;
  if (Array.isArray(valor)) return valor.map(valorLegivel).join(" · ");
  if (typeof valor === "object") return JSON.stringify(valor);
  return String(valor);
}
