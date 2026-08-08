/**
 * IA Responsável (§10.2 · F03) — a tela onde o DPO vê e MUDA o governo da IA.
 *
 * A régua desta tela é o achado 8 do UAT #5: *parametrização que não muda comportamento
 * é pior que nenhuma — vira teatro auditável*. Duas consequências de desenho:
 *
 * 1. **Cada parâmetro aparece com o EFEITO escrito, não com o valor cru.** As frases
 *    vêm do servidor (`efeitos`, montadas em `ia_responsavel_service`), no presente do
 *    indicativo: "CPF detectado INTERROMPE a chamada ao modelo". Nunca "recomenda-se".
 *    Se o efeito não couber numa frase dessas, o parâmetro não deveria estar aqui.
 * 2. **A ORIGEM é a primeira coisa que se lê.** `seed` = default de fábrica, ninguém
 *    publicou; `policy_versao` = alguém assinou, e o nome está na tela. A pergunta que
 *    uma auditoria faz é essa, e ela não pode depender de abrir o banco.
 * 3. **Cada categoria de PII declara a NATUREZA do detector e os seus LIMITES** (F04).
 *    `cpf` é detectado pela FORMA; `nome` é detectado pelo CONTEXTO, com buracos
 *    conhecidos. Mostrar as duas com o mesmo seletor e a mesma firmeza é o achado 8 um
 *    nível mais fundo: o parâmetro governa, mas o DPO assina acreditando numa cobertura
 *    que não existe. Os limites vêm do servidor (`vocabulario.categorias_pii`), onde
 *    moram junto do detector — escritos aqui, envelheceriam na primeira mexida nele.
 *
 * O formulário não redigita vocabulário: categorias de PII, ações, ações automatizáveis
 * e o roster de agentes vêm do `vocabulario` da própria resposta. Lista mantida no
 * cliente divergiria do conjunto FECHADO do domínio na primeira mudança — e o DPO veria
 * opções que o servidor rejeita.
 *
 * Publicar exige papel `dpo` (admin passa). Quem não tem o papel vê tudo e não vê o
 * formulário: ler sob que política a plataforma opera não é privilégio de ninguém.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState, type FormEvent } from "react";

import { BannerErro, EstadoVazio, TituloTela } from "../components/ui/basics";
import { ApiError, get, post } from "../lib/api";
import { useSessao } from "../lib/sessao";

// ------------------------------------------------------------------ contratos da API
interface ItemEfeito {
  chave: string;
  rotulo?: string;
  valor: unknown;
  efeito: string;
}

interface BlocoEfeito {
  parametro: string;
  titulo: string;
  resumo: string;
  itens: ItemEfeito[];
}

interface Conteudo {
  dados_llm: { acoes: Record<string, string> };
  retencao: { reter_prompt: boolean; reter_resposta: boolean; dias_trace: number };
  decisao_automatizada: { pode_aplicar_sozinho: string[] };
  modelos_permitidos: Record<string, string[]>;
  /** (d) J02 — opcional: política publicada antes da onda 6 não tem o bloco;
   * ausente/null = sem teto (o comportamento de sempre). */
  teto_tokens?: { tokens_por_dia: number | null };
}

/** Um buraco declarado do detector (§10.2 · F04) — texto do DPO + exemplo que vaza. */
interface LimiteDeteccao {
  texto: string;
  exemplo: string;
  /** Preenchida quando o buraco é de CHAVE de formulário: o exemplo é o VALOR. */
  chave: string;
}

interface CategoriaPii {
  chave: string;
  rotulo: string;
  natureza: string;
  natureza_rotulo: string;
  natureza_texto: string;
  exemplo_detectado: string;
  limites: LimiteDeteccao[];
}

interface Vocabulario {
  categorias_pii: CategoriaPii[];
  acoes_dado: string[];
  acoes_via_ai: string[];
  agentes: Record<string, string[]>;
}

interface Vigente {
  versao: number;
  origem: string;
  nunca_publicada: boolean;
  conteudo: Conteudo;
  efeitos: BlocoEfeito[];
  default_conservador: Conteudo;
  vocabulario: Vocabulario;
  autor_nome: string | null;
  publicado_por_nome: string | null;
  publicada_em: string | null;
  motivo: string | null;
}

interface PoliticaResumo {
  id: string;
  versao: number;
  estado: string;
  autor_nome: string | null;
  publicado_por_nome: string | null;
  publicada_em: string | null;
  motivo: string | null;
}

interface ListaPoliticas {
  politicas: PoliticaResumo[];
  vigente: Vigente;
}

const CHAVE = ["ia-responsavel", "politicas"] as const;

/** `origem` do backend — `seed` é o default de fábrica (ninguém publicou). */
const ORIGEM_SEED = "seed";

/**
 * `natureza` da detecção (§10.2 · F04) — vem do domínio junto do detector. Só o valor
 * de CONTEXTO é comparado aqui, e só para escolher a cor do selo: o texto que o DPO lê
 * (`natureza_rotulo`, `natureza_texto`, `limites`) é servido pronto pelo backend.
 */
const NATUREZA_CONTEXTO = "contexto";

function dataCurta(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString("pt-BR");
}

/** Erros ACUMULADOS do 422 (§7.1) — o servidor manda todos, a tela mostra todos. */
function errosDe(erro: unknown): string[] {
  if (!(erro instanceof ApiError)) return [];
  const lista = erro.problem["erros"];
  return Array.isArray(lista) ? lista.map(String) : [];
}

// ------------------------------------------------------------------------ subcomponentes
function SeloOrigem({ vigente }: { vigente: Vigente }) {
  if (vigente.origem === ORIGEM_SEED) {
    return (
      <div className="mcard border-warn-line bg-warn-bg">
        <div className="text-[13px] font-semibold text-ink2">
          Vigora o default conservador de fábrica — ninguém publicou ainda
        </div>
        <div className="mt-1 text-[12.5px] text-muted">
          A plataforma <b>não fica sem governo</b> antes da primeira publicação: as regras
          abaixo estão valendo agora. O que não existe é assinatura humana — nenhuma pessoa
          deste tenant decidiu estes valores. Publicar abaixo cria a v1, com autor e data.
        </div>
      </div>
    );
  }
  return (
    <div className="mcard">
      <div className="flex flex-wrap items-center gap-2">
        <span className="mchip-g">v{vigente.versao} publicada</span>
        <span className="text-[12.5px] text-muted">
          por <b className="text-ink2">{vigente.publicado_por_nome ?? "—"}</b> em{" "}
          {dataCurta(vigente.publicada_em)}
        </span>
      </div>
      {vigente.motivo && (
        <div className="mt-2 text-[12.5px] text-ink">
          <span className="text-muted">Motivo declarado: </span>
          {vigente.motivo}
        </div>
      )}
    </div>
  );
}

function BlocoDeEfeito({ bloco }: { bloco: BlocoEfeito }) {
  return (
    <div className="mcard">
      <div className="text-[13.5px] font-semibold text-ink2">{bloco.titulo}</div>
      <div className="mt-0.5 text-[12.5px] text-muted">{bloco.resumo}</div>
      <ul className="mt-3 flex flex-col gap-1.5">
        {bloco.itens.map((item) => (
          <li key={item.chave} className="flex gap-2 text-[12.5px]">
            <span className="mt-[3px] inline-block h-[7px] w-[7px] flex-none rounded-[2px] bg-linesoft" />
            <span>
              <b className="text-ink2">{item.rotulo ?? item.chave}</b>{" "}
              <span className="text-muted">({String(item.valor)})</span> — {item.efeito}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * Uma linha do seletor de PII — com a NATUREZA da detecção ao lado da ação (F04).
 *
 * Antes desta frente as onze categorias apareciam na mesma linha, com o mesmo seletor,
 * como se `nome: bloquear` fechasse a porta do mesmo jeito que `cpf: bloquear`. Não
 * fecha: CPF é detectado pela FORMA (o formato basta, o dígito verificador confirma) e
 * nome é detectado pelo CONTEXTO (depende de como o dado aparece escrito, e tem buracos
 * conhecidos). É o achado 8 um nível mais fundo — o parâmetro muda comportamento, mas o
 * DPO assina acreditando numa cobertura que não existe.
 *
 * Nada aqui é texto do cliente: natureza, exemplos e limites descem do
 * `vocabulario.categorias_pii` do backend, onde moram junto do detector e onde um teste
 * executa cada exemplo contra ele a cada CI. Escrito aqui, envelheceria na primeira
 * mexida em `mascarar.py` — e a tela passaria a mentir na direção contrária.
 */
function LinhaCategoria({
  categoria,
  acoesDisponiveis,
  acaoAtual,
  acaoDeFabrica,
  onMudar,
}: {
  categoria: CategoriaPii;
  acoesDisponiveis: string[];
  acaoAtual: string;
  acaoDeFabrica: string | undefined;
  onMudar: (acao: string) => void;
}) {
  const porContexto = categoria.natureza === NATUREZA_CONTEXTO;
  const limites = categoria.limites;
  return (
    <div className="flex flex-col gap-1 border-t border-linesoft py-1.5 first:border-t-0">
      <label className="flex flex-wrap items-center gap-2 text-[12.5px]">
        <span className="w-56 text-ink2">{categoria.rotulo}</span>
        <select
          className="rounded border border-line px-2 py-1 text-[12.5px]"
          value={acaoAtual}
          onChange={(e) => onMudar(e.target.value)}
        >
          {acoesDisponiveis.map((acao) => (
            <option key={acao} value={acao}>
              {acao === "bloquear" ? "bloquear (a chamada não acontece)" : "mascarar"}
            </option>
          ))}
        </select>
        {/* A natureza fica ao LADO do seletor, não numa nota de rodapé: é ela que diz
            quanto vale a ação que se acabou de escolher. */}
        <span className={porContexto ? "mchip-w" : "mchip-n"}>{categoria.natureza_rotulo}</span>
        {acaoDeFabrica === acaoAtual && <span className="mchip-n">de fábrica</span>}
      </label>

      <details className="ml-2 text-[12px] text-muted">
        <summary className="cursor-pointer">
          {limites.length > 0
            ? `Cobertura: ${limites.length} caso(s) em que ${categoria.rotulo} sai em claro`
            : `Como ${categoria.rotulo} é reconhecido`}
        </summary>
        <div className="mt-1 flex flex-col gap-1.5 pl-3">
          <div>{categoria.natureza_texto}</div>
          <div>
            <b className="text-ink2">Detectado hoje:</b>{" "}
            <code className="rounded bg-linesoft/40 px-1">{categoria.exemplo_detectado}</code>
          </div>
          {limites.map((limite) => (
            <div key={limite.texto} className="border-l-2 border-warn-line pl-2">
              <div className="text-ink">{limite.texto}</div>
              <div className="mt-0.5">
                <b className="text-ink2">Sai em claro:</b>{" "}
                <code className="rounded bg-linesoft/40 px-1">
                  {limite.chave ? `campo "${limite.chave}": "${limite.exemplo}"` : limite.exemplo}
                </code>
              </div>
            </div>
          ))}
        </div>
      </details>
    </div>
  );
}

// ------------------------------------------------------------------------ formulário
function Formulario({ vigente }: { vigente: Vigente }) {
  const cliente = useQueryClient();
  const [rascunho, setRascunho] = useState<Conteudo>(() => structuredClone(vigente.conteudo));
  const [motivo, setMotivo] = useState("");

  // O rascunho parte SEMPRE do que está valendo (não do vazio): publicar sem enxergar o
  // ponto de partida é como o DPO afrouxaria um parâmetro sem perceber.
  useEffect(() => {
    setRascunho(structuredClone(vigente.conteudo));
  }, [vigente.versao, vigente.origem, vigente.conteudo]);

  const publicar = useMutation({
    mutationFn: (corpo: { conteudo: Conteudo; motivo: string }) =>
      post<Vigente>("/ia-responsavel/politicas", corpo),
    onSuccess: () => {
      setMotivo("");
      void cliente.invalidateQueries({ queryKey: CHAVE });
    },
  });

  const conservador = vigente.default_conservador;
  const igualAoConservador = useMemo(
    () => JSON.stringify(rascunho) === JSON.stringify(conservador),
    [rascunho, conservador],
  );

  function enviar(e: FormEvent) {
    e.preventDefault();
    publicar.mutate({ conteudo: rascunho, motivo });
  }

  const erros = errosDe(publicar.error);

  return (
    <form onSubmit={enviar} className="mcard flex flex-col gap-4">
      <div>
        <div className="text-[13.5px] font-semibold text-ink2">Publicar nova versão</div>
        <div className="text-[12.5px] text-muted">
          A partir do envio, é esta versão que governa — imediatamente e para todas as OS,
          inclusive as em voo (política de privacidade não é congelada por OS: um titular não
          tem menos direito porque a campanha é antiga).
        </div>
      </div>

      {publicar.error != null && erros.length === 0 && (
        <BannerErro erro={publicar.error} contexto="Publicação recusada" />
      )}
      {erros.length > 0 && (
        <div className="rounded-lg border border-crit/40 bg-crit-soft px-4 py-3 text-[12.5px] text-ink">
          <b>Publicação recusada — conjunto FECHADO de parâmetros:</b>
          <ul className="mt-1 list-disc pl-5">
            {erros.map((erro) => (
              <li key={erro}>{erro}</li>
            ))}
          </ul>
        </div>
      )}

      {/* (a) dados que podem ir ao LLM */}
      <fieldset className="flex flex-col gap-1.5">
        <legend className="text-[12.5px] font-semibold text-ink2">
          Dados pessoais que podem sair para o modelo
        </legend>
        <div className="text-[12px] text-muted">
          Não existe “permitir”: mascarar é o piso de contrato (§10.2) e a política só aperta.
          Conservador de fábrica: tudo <b>mascarar</b>. A ação escolhida só age sobre o que o
          detector ENCONTRA — por isso cada categoria abre a própria cobertura aqui embaixo.
        </div>
        {vigente.vocabulario.categorias_pii.map((categoria) => (
          <LinhaCategoria
            key={categoria.chave}
            categoria={categoria}
            acoesDisponiveis={vigente.vocabulario.acoes_dado}
            acaoAtual={rascunho.dados_llm.acoes[categoria.chave] ?? "mascarar"}
            acaoDeFabrica={conservador.dados_llm.acoes[categoria.chave]}
            onMudar={(acao) =>
              setRascunho((atual) => ({
                ...atual,
                dados_llm: {
                  acoes: { ...atual.dados_llm.acoes, [categoria.chave]: acao },
                },
              }))
            }
          />
        ))}
      </fieldset>

      {/* (b) retenção */}
      <fieldset className="flex flex-col gap-1.5">
        <legend className="text-[12.5px] font-semibold text-ink2">
          Retenção de prompt, resposta e trace
        </legend>
        <div className="text-[12px] text-muted">
          Reter o mínimo é o mínimo <i>necessário</i>: o Art. 20 exige reconstruir a decisão
          automatizada. O prazo do LEDGER não é definido aqui — é <code>retencao_dias</code> na
          política do M12, que é quem o purge (§10.4) lê.
        </div>
        <label className="flex items-center gap-2 text-[12.5px]">
          <input
            type="checkbox"
            checked={rascunho.retencao.reter_prompt}
            onChange={(e) =>
              setRascunho((a) => ({
                ...a,
                retencao: { ...a.retencao, reter_prompt: e.target.checked },
              }))
            }
          />
          Gravar o prompt enviado ao modelo
        </label>
        <label className="flex items-center gap-2 text-[12.5px]">
          <input
            type="checkbox"
            checked={rascunho.retencao.reter_resposta}
            onChange={(e) =>
              setRascunho((a) => ({
                ...a,
                retencao: { ...a.retencao, reter_resposta: e.target.checked },
              }))
            }
          />
          Gravar a resposta do modelo
        </label>
        <label className="flex items-center gap-2 text-[12.5px]">
          <span className="w-56 text-ink2">Dias de trace (diagnóstico)</span>
          <input
            type="number"
            min={1}
            className="w-24 rounded border border-line px-2 py-1 text-[12.5px]"
            value={rascunho.retencao.dias_trace}
            onChange={(e) =>
              setRascunho((a) => ({
                ...a,
                retencao: { ...a.retencao, dias_trace: Number(e.target.value) },
              }))
            }
          />
          <span className="text-[12px] text-muted">
            de fábrica: {conservador.retencao.dias_trace}
          </span>
        </label>
      </fieldset>

      {/* (c) decisão automatizada — Art. 20 */}
      <fieldset className="flex flex-col gap-1.5">
        <legend className="text-[12.5px] font-semibold text-ink2">
          Decisão automatizada (LGPD Art. 20)
        </legend>
        <div className="text-[12px] text-muted">
          Conservador de fábrica: <b>nenhuma</b> marcada — a IA propõe e um humano aplica.
          Marcar uma ação retira o humano do caminho dela.
        </div>
        {vigente.vocabulario.acoes_via_ai.map((acao) => (
          <label key={acao} className="flex items-center gap-2 text-[12.5px]">
            <input
              type="checkbox"
              checked={rascunho.decisao_automatizada.pode_aplicar_sozinho.includes(acao)}
              onChange={(e) =>
                setRascunho((a) => ({
                  ...a,
                  decisao_automatizada: {
                    pode_aplicar_sozinho: e.target.checked
                      ? [...a.decisao_automatizada.pode_aplicar_sozinho, acao]
                      : a.decisao_automatizada.pode_aplicar_sozinho.filter((x) => x !== acao),
                  },
                }))
              }
            />
            <code>{acao}</code>
            <span className="text-muted">
              {rascunho.decisao_automatizada.pode_aplicar_sozinho.includes(acao)
                ? "— a IA aplica sozinha"
                : "— a IA propõe, um humano aplica"}
            </span>
          </label>
        ))}
      </fieldset>

      {/* (f) modelos permitidos por agente */}
      <fieldset className="flex flex-col gap-1.5">
        <legend className="text-[12.5px] font-semibold text-ink2">
          Modelos permitidos por agente (roster §7.2)
        </legend>
        <div className="text-[12px] text-muted">
          Desmarcar todos os perfis de um agente o impede de chamar modelo nenhum. Agente fora
          do roster é recusado na publicação — um typo viraria entrada morta e o agente
          seguiria liberado.
        </div>
        <div className="grid grid-cols-1 gap-1 md:grid-cols-2">
          {Object.entries(vigente.vocabulario.agentes).map(([agente, perfisDoRoster]) => (
            <div key={agente} className="flex items-center gap-2 text-[12.5px]">
              <span className="w-40 truncate text-ink2">{agente}</span>
              {perfisDoRoster.length > 0 &&
                ["120b", "20b"].map((perfil) => (
                  <label key={perfil} className="flex items-center gap-1">
                    <input
                      type="checkbox"
                      checked={(rascunho.modelos_permitidos[agente] ?? []).includes(perfil)}
                      onChange={(e) =>
                        setRascunho((a) => {
                          const atuais = a.modelos_permitidos[agente] ?? [];
                          return {
                            ...a,
                            modelos_permitidos: {
                              ...a.modelos_permitidos,
                              [agente]: e.target.checked
                                ? [...atuais, perfil]
                                : atuais.filter((x) => x !== perfil),
                            },
                          };
                        })
                      }
                    />
                    {perfil}
                  </label>
                ))}
            </div>
          ))}
        </div>
      </fieldset>

      {/* (d) teto de consumo — J02 */}
      <fieldset className="flex flex-col gap-1.5">
        <legend className="text-[12.5px] font-semibold text-ink2">
          Teto de consumo de tokens (por tenant, por dia UTC)
        </legend>
        <div className="text-[12px] text-muted">
          Vazio = sem teto (o comportamento de sempre). Com teto, a chamada que encontrar o
          gasto do dia no limite é recusada ANTES de custar (429); o orçamento reinicia à
          meia-noite UTC. Limite declarado: o teto governa o gasto <b>medido</b> — linha de
          ledger sem usage do provedor conta 0.
        </div>
        <label className="flex items-center gap-2 text-[12.5px]">
          <span className="w-56 text-ink2">Tokens por dia</span>
          <input
            type="number"
            min={1}
            className="w-32 rounded border border-line px-2 py-1 text-[12.5px]"
            value={rascunho.teto_tokens?.tokens_por_dia ?? ""}
            onChange={(e) =>
              setRascunho((a) => ({
                ...a,
                teto_tokens: {
                  tokens_por_dia: e.target.value === "" ? null : Number(e.target.value),
                },
              }))
            }
          />
          <span className="text-[12px] text-muted">
            de fábrica: {conservador.teto_tokens?.tokens_por_dia ?? "sem teto"}
          </span>
        </label>
      </fieldset>

      <label className="flex flex-col gap-1 text-[12.5px]">
        <span className="font-semibold text-ink2">Motivo da mudança (obrigatório)</span>
        <span className="text-[12px] text-muted">
          Política de privacidade que muda sem justificativa escrita é o que uma auditoria pede
          para ver e não encontra.
        </span>
        <textarea
          required
          minLength={5}
          maxLength={500}
          rows={2}
          className="rounded border border-line px-2 py-1 text-[12.5px]"
          value={motivo}
          onChange={(e) => setMotivo(e.target.value)}
          placeholder="Ex.: bloqueio de cartão pedido pelo comitê de privacidade em 06/08."
        />
      </label>

      <div className="flex flex-wrap items-center gap-2">
        <button type="submit" className="mbtn" disabled={publicar.isPending}>
          {publicar.isPending ? "Publicando…" : "Publicar política"}
        </button>
        <button
          type="button"
          className="mbtn-gh"
          onClick={() => setRascunho(structuredClone(conservador))}
          disabled={igualAoConservador}
          title="Volta o formulário ao conservador de fábrica (§10.2)"
        >
          Restaurar defaults conservadores
        </button>
        {igualAoConservador && (
          <span className="text-[12px] text-muted">
            O rascunho é idêntico ao conservador de fábrica.
          </span>
        )}
      </div>
    </form>
  );
}

// ------------------------------------------------------------------------------ tela
export function IaResponsavel() {
  const sessao = useSessao((s) => s.sessao);
  const podePublicar = (sessao?.papeis ?? []).some((p) => p === "dpo" || p === "admin");

  const { data, error, isLoading } = useQuery({
    queryKey: CHAVE,
    queryFn: ({ signal }) => get<ListaPoliticas>("/ia-responsavel/politicas", signal),
  });

  return (
    <div className="flex flex-col gap-4 p-4">
      <TituloTela
        titulo="IA Responsável"
        subtitulo="O que a IA pode ver, guardar, decidir sozinha e com qual modelo (§10.2 · LGPD Art. 20)"
      />

      {error != null && <BannerErro erro={error} contexto="Política de IA" />}
      {isLoading && <EstadoVazio>Carregando a política vigente…</EstadoVazio>}

      {data && (
        <>
          <SeloOrigem vigente={data.vigente} />

          <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
            {data.vigente.efeitos.map((bloco) => (
              <BlocoDeEfeito key={bloco.parametro} bloco={bloco} />
            ))}
          </div>

          {podePublicar ? (
            <Formulario vigente={data.vigente} />
          ) : (
            <div className="mcard text-[12.5px] text-muted">
              Publicar exige o papel <b>dpo</b> — é a função que responde pelo titular na LGPD.
              A leitura acima é de qualquer pessoa autenticada.
            </div>
          )}

          <div className="mcard">
            <div className="text-[13.5px] font-semibold text-ink2">Histórico de versões</div>
            {data.politicas.length === 0 ? (
              <div className="mt-2 text-[12.5px] text-muted">
                Nenhuma versão publicada neste tenant — vigora o default de fábrica. Versão
                nova nunca apaga a anterior: a auditoria precisa das duas.
              </div>
            ) : (
              <table className="mt-2 w-full text-left text-[12.5px]">
                <thead className="text-muted">
                  <tr>
                    <th className="py-1 pr-3 font-medium">Versão</th>
                    <th className="py-1 pr-3 font-medium">Publicada por</th>
                    <th className="py-1 pr-3 font-medium">Quando</th>
                    <th className="py-1 font-medium">Motivo</th>
                  </tr>
                </thead>
                <tbody>
                  {[...data.politicas]
                    .sort((a, b) => b.versao - a.versao)
                    .map((politica) => (
                      <tr key={politica.id} className="border-t border-linesoft">
                        <td className="py-1 pr-3">
                          v{politica.versao}
                          {politica.versao === data.vigente.versao &&
                            data.vigente.origem !== ORIGEM_SEED && (
                              <span className="ml-2 mchip-g">vigente</span>
                            )}
                        </td>
                        <td className="py-1 pr-3">{politica.publicado_por_nome ?? "—"}</td>
                        <td className="py-1 pr-3">{dataCurta(politica.publicada_em)}</td>
                        <td className="py-1">{politica.motivo ?? "—"}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}
    </div>
  );
}
