# UAT #4 — Digital Twin do Journey Builder (exaustivo)

**Alvo:** `http://vps.falagaiotto.com.br:8050` · SHA deployado `8969688` · tenant `torre-movel`
**Data:** 2026-08-06 · **Foco:** construção do fluxo — validação, edição, versionamento, hash,
simulação, exportação e geração por IA. Tudo executado contra a **VPS real** (Postgres real,
HubGPU real, gpt-oss-120b real). Nenhum mock.

**Placar:** 13 casos de uso · **7 achados** (1 crítico, 3 médios, 3 menores) · 3 corrigidos com
teste de regressão, 1 documentado como limitação, 3 registrados sem correção.

---

## Sumário dos achados

| # | Gravidade | O quê | Situação |
|---|---|---|---|
| **D07** | **Crítico** | `POST /simular` → HTTP 500 (`KeyError: 'to'`) em grafo gerado pelo próprio Flow | **Corrigido** + teste |
| **D03** | Médio | `wait.duracao` aceita qualquer string; bypass silencioso da janela da oferta | **Corrigido** + teste |
| **D05** | Médio | `frequencySplit` com classe-objeto é impossível de salvar | **Corrigido** + teste |
| **D06** | Médio | Editar o grafo **sobrescreve** a versão — sem histórico | Registrado (decisão de produto) |
| **D04** | Médio | Regra `wait_alem_da_janela` nunca executa em produção | Documentada como inerte |
| **D01** | Menor | "Começar do zero" bloqueado em OS com experimento pré-registrado | Registrado |
| **D02** | Menor | Chave `braços` acentuada sem alias ASCII | Registrado |

---

## UC01 — Criar o twin do zero

`POST /os/{id}/jornada` numa OS limpa devolve o esqueleto mínimo, **sem LLM**:

```
v1 | rascunho | hash cc53628f9d
nós:   [('entrada','entrySource'), ('meta','goal'), ('saida','exit')]
edges: [('entrada','meta'), ('meta','saida')]
```

**Achado D01 (menor).** A mesma chamada na OS `b52e9afe` (que ganhou um experimento
pré-registrado no UAT #3) devolve **422**:

> Experimento pré-registrado exige braço de holdout no grafo (§5.3).

A validação cruzada está **certa** — um experimento travado sem holdout invalida a medição. O
problema é de sequência: o esqueleto mínimo não tem como nascer com holdout, então "começar do
zero" fica impossível nessa OS sem edição manual do JSON. Duas saídas razoáveis: o esqueleto
passa a incluir `randomSplit` de holdout quando a OS tem experimento, ou a regra só vale ao
publicar. Não corrigido — é decisão de produto.

---

## UC02 — Bateria de validação §5.3: 12 grafos inválidos

Um grafo por regra, todos via `PUT /jornadas/{id}/grafo`. **12 de 12 bloqueados com 422** e
`problem+json` nomeando nó e regra:

| Caso | Regra disparada |
|---|---|
| Nó órfão (inalcançável da entrada) | `no_orfao` + `braco_sem_destino` |
| Aresta apontando para nó inexistente | `estrutura` |
| Aresta sem campo `to` | `estrutura` |
| `randomSplit` sem o campo de braços | `campo_obrigatorio` |
| Canal sem opt-in | `optin_ausente` |
| Ids de nó duplicados | `estrutura` |
| Grafo sem `goal` | `sem_goal` |
| Grafo sem `entrySource` | `no_orfao` (×4) |
| Tipo de nó inventado (`channel.telepatia`) | `tipo_de_no` |
| Nó sem objeto `data` | `campo_obrigatorio` |
| Ciclo sem saída | `no_orfao` |
| `randomSplit` com soma 90 ≠ 100 | `soma_pcts` |
| Braço de split sem aresta de destino | `braco_sem_destino` |
| `decisionSplit` sem `regras` | `campo_obrigatorio` |
| Canal com opt-in mas sem `assetRef` | `campo_obrigatorio` |
| `goal` sem métrica | `campo_obrigatorio` (×2) |

A lista de tipos é **fechada em 16** e lida direto do `jgc.schema.json` — tipo inventado não
entra. Mensagens citam a seção do SDD.

**Achado D02 (menor).** A chave canônica dos braços é `braços` — **com cedilha e til**. Enviar
`bracos` produz "sem campo obrigatório `braços`", que parece dizer que o campo não foi enviado.
Arestas têm alias ASCII desde a emenda A13 (`source`/`target` → `from`/`to`); braços não. Para
um LLM ou integrador externo, chave acentuada é uma armadilha.

**Achado D03 (médio) — bypass, não só laxidão.** `wait` com `duracao: "3 dias"` foi **aceito**.
A validação só conferia a presença do campo. Pior: a regra `wait_alem_da_janela` faz
`if dias is not None`, então uma duração malformada **escapa em silêncio** do limite da janela
da oferta. Confirmado com `"90 dias"`, `"P90"` e `"PT90D"` — todos salvos. Depois reapareceu
sozinho no UC12, gerado pelo 120b. **Corrigido.**

---

## UC03 — Grafo com os 16 tipos de nó

17 nós e 20 arestas exercitando **todos** os tipos do §5.2 num único grafo: `entrySource`,
`randomSplit` com holdout, `wait`, `sto`, os cinco canais (email, sms, push, whatsapp, rcs),
`engagementSplit`, `decisionSplit`, `frequencySplit`, `updateContact`, `exception`, `goal`,
`exit`. **Aceito** — `16/16 tipos distintos`, hash `05e30b282a92`.

**Achado D05 (médio).** Só passou depois de trocar `classes` de objeto para string. Com a forma
documentada no §5.2 — `[{"id":"baixa","max":2},{"id":"alta","min":3}]` — o save falha sempre:

```
[422] classes=[{id,max},{id,min}]  ->  Classe {'id': 'baixa', 'max': 2} sem aresta de destino
[200] classes=['baixa','alta']     ->  aceito
```

A regra comparava `str(classe)` (a repr do dict) contra as `cond` das arestas. Nunca casa. O nó
era **inutilizável na sua forma canônica**, com todas as arestas corretas. **Corrigido.**

---

## UC04 — Taxímetro

`PUT` devolve o custo com memória de cálculo linha a linha e aviso honesto quando falta base:

```json
{"custo_projetado": 0.0,
 "memoria": [{"no":"em","canal":"email","volume":0,"tarifa":"0.0018","custo":"0.00"}],
 "avisos": ["OS sem segmento recontado (M5) — taxímetro calculado com volume 0."]}
```

Não inventa volume nem tarifa. Numa OS com segmento real o custo saiu **R$ 31.800,00**.

**Achado D04 (médio) — regra morta.** `wait_alem_da_janela` nunca executa: `validar_grafo` tem
`janela_oferta_dias=None` por default e o único chamador de produção
(`jornada_service.py:453`) não passa o argumento. Nenhum teste a cobre — o grep de
`janela_oferta_dias` em `tests/` volta vazio, o que explica o verde permanente. **Não corrigida
de propósito:** a janela vive como texto livre no briefing (`"01/07 a 15/08 (rampa canário…)"`)
e derivá-la por parser inventaria semântica (§1.3.5). Ligar a regra exige janela estruturada —
mudança de escopo. Documentada no §5.3 como limitação conhecida.

---

## UC05 — Hash canônico

| Cenário | Resultado |
|---|---|
| Mesmo grafo salvo 2× | hash **idêntico** — determinístico |
| Um caractere alterado (`ast-1`→`ast-2`) | hash **diferente** — sensível |
| Ordem de `nodes`/`edges` invertida | hash **diferente** |

Os dois primeiros são o contrato. O terceiro merece nota: RFC 8785 canonicaliza chaves de
objeto, mas arrays preservam ordem — então dois analistas desenhando **o mesmo grafo** em ordem
diferente produzem hashes diferentes, logo `externalKey` diferentes. Ordenar `nodes`/`edges` por
`id` antes de hashear tornaria o hash verdadeiramente semântico. Fica registrado como
observação de design, não como defeito (o comportamento atual é o do JCS).

---

## UC06 — Versionamento

`GET /os/{id}/jornadas` lista a linha do tempo. Na OS demo: v1 `aprovado` (13 nós, custo
R$ 31.800), criação de v2 do zero → **v1 permanece intacta**, hash inalterado. Restaurar a v1
gerou **v3 com hash idêntico ao da v1** — cópia fiel comprovada pelo content-addressable.

**Achado D06 (médio).** Cerca de **25 `PUT` de grafo produziram uma única versão**. O
`atualizar_grafo` faz mutação in-place (`jornada.grafo = grafo` → `salvar_jornada`): o desenho
anterior é perdido para sempre. Versão nova só nasce em `gerar`, `criar_manual` e `restaurar`.
Consequência prática: o analista que passa uma hora desenhando, apaga um ramo por engano e
salva **não tem como voltar** — "restaurar" só oferece versões geradas pela IA, e o "diff entre
versões" raramente tem duas versões para comparar num fluxo de edição real.

Não é bug de implementação — o §1.2 diz "sem edição ao vivo" e o estado `aprovado` é
corretamente imutável. Mas o usuário pediu "controle de versão" equivalente ao Journey Builder,
e lá cada save versiona. Sugestão: snapshot automático a cada `PUT` que mude o hash, ou um
"salvar como nova versão" explícito no editor.

---

## UC07 — Diff entre versões

`GET /jornadas/{a}/diff/{b}` devolve diff estrutural por id, com os hashes dos dois lados:

```json
{"nodes": {"adicionados": ["entrada","meta","saida"],
           "removidos": ["n1","n2",…,"n13"], "alterados": []},
 "edges": {"adicionados": [], "removidos": ["e3",…,"e11"], "alterados": ["e1","e2"]},
 "meta_alterada": true}
```

Correto e legível.

---

## UC08 — Exportação

| Formato | Resultado |
|---|---|
| default / `json` | `activities[]` com `key: jrn-{hash12}-{no}` e `outcomes` |
| `xml` | XML **bem-formado**, `Interaction` + `Manifest` + `Triggers` + `Activities` + `Goals` |
| `sfmc`, valor inválido | 422 — enum fechado |

O `Manifest` carrega `hashJgc`, `versao`, `geradoEm` e `plataforma`, e as `externalKey` seguem
`jrn-{hash[0:12]}-{noId}` (idempotência do §5.4.1). Duas observações honestas:

- As chaves de `Outcome` usam o **id cru da aresta** (`key="e2"`), sem o prefixo `jrn-{hash}-`
  que todas as outras chaves têm. Duas jornadas com arestas chamadas `e2` na mesma BU colidem.
- O XML valida contra `journey_export.xsd`, que é um **schema próprio do projeto** (usa
  `Argument nome=` em português). Não é o formato de importação oficial da Salesforce — o
  Journey Builder consome JSON via `/interaction/v1/interactions`. O export é fiel ao contrato
  interno e serve para versionamento e revisão; chamá-lo de "XML padrão do Journey Builder"
  seria impreciso.

---

## UC09 — Simulação e invalidação

Cadeia de pré-requisitos correta e com mensagens acionáveis:

- Simular sem segmento recontado → **409**: *"OS sem segmento com contagem líquida — reconte a
  audiência (M5) antes do Ensaio Geral"*.
- Congelar sem simulação → **409**: *"rode POST /jornadas/{id}/simular antes"*.
- Simular jornada `aprovado` → **409**: *"não se re-simula — novo ciclo exige nova versão"*.

Simulação real na OS demo: **500 runs**, ROAS P10/P50/P90 = 12,9 / 15,2 / 17,8, custo
R$ 4.100 / 4.246 / 4.400, e funil por nó com percentis.

**Invalidação verificada:** editar o grafo após simular zera `simulacao` e `previsto` e devolve
o estado a `rascunho` (§6/§1.1.2). O Previsto que vale segue sendo o do snapshot.

Observação menor: `JornadaOut` (o `GET`) não expõe `simulacao` nem `previsto` — eles só existem
na resposta do `POST`. Recarregar a página perde o overlay do Ensaio Geral no canvas. Não afeta
o previsto×realizado do Monitor, que lê do snapshot.

---

## UC10 — Geração do fluxo pelo Flow (gpt-oss-120b real)

`POST /os/{id}/jornada/gerar` — **34,5 s**, HTTP 201. O modelo produziu um JGC **válido** de
**15 nós e 21 arestas**:

```
entrySource → decisionSplit(elegibilidade) → randomSplit(holdout 10%) → randomSplit(mix de canais)
  → email 40% / push 30% / sms 20% / whatsapp 10% → wait → updateContact → goal → exit
  + exception com retry captando erro de envio dos 4 canais
  + exits separados para holdout e não-elegível
```

Custo projetado R$ 13.703,00 e premissas explicitadas em português ("10% dos contatos são
alocados ao braço de controle", "todos os canais possuem assetRef apontando para templates
aprovados"). A modelagem é boa: holdout presente, elegibilidade antes da divisão, tratamento de
exceção com `maxAttempts`, exits distintos por motivo.

**Achado D07 (CRÍTICO).** Simular esse mesmo grafo — o que o produto acabou de gerar — devolve
**HTTP 500**:

```
File "/srv/domain/simulacao/motor.py", line 79, in _saidas
    {"from": str(no["id"]), "to": str(regra["to"]), …}
KeyError: 'to'
```

O `decisionSplit` veio com `regras: [{"id":"eligible","cond":"optIn"}]` — sem `to`, porque o
roteamento está nas arestas com `cond`. Forma legítima, aprovada pelo validador. **O caminho
feliz do produto (gerar → simular) terminava em erro genérico.**

Causa: **três cópias** da mesma função `_saidas` — validador, taxímetro e motor. A emenda A13
("dado torto não estoura `KeyError`") havia sido aplicada em duas; o motor ficou de fora. Bug de
classe, não de instância.

O mesmo grafo trouxe também um `wait` com `duracao: "imediato_apos_quiet_hours"` — o achado D03
aparecendo sozinho em produção, o que o promoveu de teórico a real.

---

## UC11 — Ajuste por linguagem natural

`POST /jornadas/{id}/ajustar` com *"adicione um lembrete por SMS 3 dias depois do e-mail para
quem não abriu, e aumente o holdout para 15%"* — **24,8 s**:

- `aplicado: false` — o diff é **proposto**, nunca aplicado (§8-M7). Confirmado: o grafo real
  continuou com 15 nós e **hash inalterado**.
- O grafo proposto tem 18 nós: adicionou `engagementSplit` + `wait` + `channel.sms` e alterou o
  `randomSplit` do holdout. Entendeu as duas instruções corretamente.

Comportamento exemplar: a IA propõe, o humano aplica.

---

## UC12 — Recusa honesta do Engineer

`POST /os/{id}/segmento/gerar-sql` pedindo "sem uso de dados nos últimos 45 dias" → **422** com
a recusa do agente:

> Falta definição de coluna que indique consumo de dados nos últimos 45 dias. Sem essa
> informação não é possível gerar o SQL conforme as regras de segmentação exigidas.

O agente **não inventou coluna** (§7.1 `exige_evidencia`). Num sistema que dispara campanhas
para milhões de contatos, inventar um filtro seria o pior desfecho possível. A recusa persiste
mesmo quando as instruções pedem outras colunas, porque o **briefing da OS** continua exigindo a
que não existe — validação contra o contrato, não só contra o último texto digitado.

---

## UC13 — Estados e imutabilidade

| Ação | Estado | Resultado |
|---|---|---|
| `PUT` grafo em `rascunho` | rascunho | 200 |
| `PUT` grafo em `simulado` | simulado | 200 + invalida simulação → `rascunho` |
| `simular` em `aprovado` | aprovado | **409** |
| `PUT` grafo em `aprovado` | aprovado | **409** — "novo ciclo exige nova versão" |

A imutabilidade do aprovado é respeitada em todos os caminhos testados.

---

## Correções aplicadas nesta rodada

Todas com teste de regressão em `backend/tests/unit/test_twin_uat4.py` (21 casos) e **inversão
verificada** — a lógica anterior foi executada contra os mesmos grafos e falha:

```
CÓDIGO ANTIGO (commit 8969688) ->  KeyError: 'to'                        (D07)
CÓDIGO NOVO                    ->  saídas de n2: ['n3', 'n0']

D05 antigo: str({'id':'baixa','max':2}) in conds  ->  False  (nunca casa)
D05 novo:   classe['id'] in conds                 ->  True

D03 antigo: só checava presença                   ->  aceito
D03 novo:   duracao_em_dias('imediato_apos_…')    ->  None -> rejeitado
```

- **D07** — `backend/domain/jornada/adjacencia.py`: `saidas_do_grafo()` como fonte única,
  consumida por validador, taxímetro e motor. As três cópias foram removidas.
- **D03** — `wait.duracao` conferida contra o ISO-8601 do `duracao_em_dias`, regra
  `duracao_invalida`. `ate` segue valendo.
- **D05** — `frequencySplit` casa classe por `id`, como o `randomSplit`. Classe sem aresta
  continua barrada.

**Gates:** `pytest -m "not integration"` **267 passed** · `ruff check` limpo · `ruff format`
270 arquivos · `mypy` (escopo do CI) sem erros.

---

## Recomendações não implementadas

1. **Versionar cada save** (D06) — snapshot automático quando o hash muda, ou "salvar como nova
   versão" explícito. Hoje uma edição errada é irreversível.
2. **Janela estruturada no briefing** (D04) — `janela_inicio`/`janela_fim` para ativar a regra
   `wait_alem_da_janela`, hoje inerte.
3. **Alias ASCII para `braços`** (D02) — mesma cortesia que as arestas já têm.
4. **Esqueleto com holdout** quando a OS tem experimento (D01).
5. **`externalKey` nos `Outcome`** do XML — prefixar com `jrn-{hash12}-` como as demais chaves.
6. **Ordenar `nodes`/`edges` por id antes do hash** — tornaria o hash semântico, imune à ordem
   de desenho.
7. **Expor `simulacao`/`previsto` no `GET`** da jornada, para o canvas recuperar o overlay do
   Ensaio Geral após um reload.
