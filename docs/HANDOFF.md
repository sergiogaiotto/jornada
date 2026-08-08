# HANDOFF — Jornada (Digital Twin do Journey Builder)

**Escrito em:** 2026-08-07 · **Commit de referência:** `36c4f52` (main, local == remoto)
**Para:** continuar o trabalho em outra máquina, do zero, sem esta conversa.

Este documento é longo de propósito. Ele existe para que quem chegar agora entenda **por que** o
código está do jeito que está, não só o que ele faz. Onde houver decisão contra-intuitiva, o motivo
está escrito — quase sempre porque a alternativa óbvia já falhou e custou um achado.

---

## 1. O que é o projeto

Plataforma de marketing que funciona como **gêmeo digital do Journey Builder** do Salesforce
Marketing Cloud. O usuário desenha a jornada num canvas, o sistema simula o resultado antes de
disparar, congela o previsto como régua, compila para o SFMC e depois compara previsto × realizado.

Agentes de IA participam do fluxo (geram o SQL do segmento, propõem o grafo da jornada, escrevem
criativos), mas **nunca decidem** — todo portão é código determinístico. Essa é a regra §1.1.2 do
contrato, e boa parte dos achados desta jornada foi exatamente onde ela estava sendo violada na
prática.

**Contrato vinculante:** `SDD-Jornada.md`. Toda divergência necessária edita a seção afetada **e**
registra em `CHANGELOG-SDD.md`, no mesmo commit (regra §1.3.3). O CHANGELOG está em ordem cronológica
inversa e é a melhor porta de entrada para entender a história.

---

## 2. Estado atual — o que está no ar e o que não está

| Item | Estado |
|---|---|
| **Repositório** | `main` com a **onda 5** (I01–I05 + auditoria, `af3e80d`) + workflow `configurar-vps` (`bfe1cc2`) |
| **VPS** | **roda `bfe1cc2`** — ondas 4 e 5 deployadas em 2026-08-07 pelo CI, smoke A22 + funcional verdes |
| **Suíte** | **777 passed** (a onda 5 somou 33 testes aos 744), 1 skipped, 23 deselected, 1 xfailed |
| **Gates** | ruff, ruff format, mypy e `npm run build` verdes |
| **Ambiente** | `APP_ENV=dev` na VPS, `DEMO_MODE=true` — ainda **demo pública**, dado sintético |
| **PII real** | **NÃO liberado.** Faltam TLS, backup aplicado e o corte de ambiente |

### ✅ O impasse do deploy foi RESOLVIDO (2026-08-07) — registro histórico

A sequência, para quem chegar depois: (1) a cota do Actions voltou no mesmo dia em que este
handoff foi escrito; (2) o deploy passou a falhar por `APP_ENV` ausente no `.env` da VPS — a
exigência deliberada da onda 4 — e a máquina de operação nova não tinha a chave SSH para gravar a
variável; (3) o workflow **`configurar-vps`** (emenda I06, `workflow_dispatch`) resolveu usando o
SSH do próprio CI, com a decisão de ambiente explícita de quem dispara: `APP_ENV=dev` +
`DEMO_MODE=true` (explícito porque o default do compose virou `false` — sem a linha a demo
desligaria em silêncio); (4) o deploy seguinte passou inteiro, com smoke A22 + funcional verdes.

Para o corte de produção (§8.2): dispare `configurar-vps` com `app_env=prod` + `demo_mode=false`
— DEPOIS do TLS e junto dele, como o comentário do compose exige. O workflow nunca sobrescreve
variável existente: para TROCAR o ambiente é preciso editar o `.env` na VPS (chave SSH).

**Observação de 2026-08-07:** a listagem de variáveis do primeiro dispatch mostrou
`JORNADA_ROOT_EMAIL`/`JORNADA_ROOT_SENHA` presentes no `.env` — o §4.2 deste handoff dizia que não
existiam. Foram adicionadas depois da escrita; o bootstrap do root pode já ter rodado.

---

## 3. Como levantar o ambiente na máquina nova

```bash
git clone https://github.com/sergiogaiotto/jornada.git
cd jornada
```

### O ponto mais importante deste documento

**Não rode a suíte com o Python da sua máquina.** Rode no container, instalando do **lock**:

```bash
docker run --rm -v "$(pwd):/w" -w /w python:3.11-slim \
  bash -c "pip install -q -r requirements.lock && python -m pytest -m 'not integration' -q"
```

No Windows (Git Bash), prefixe com `MSYS_NO_PATHCONV=1` e use o caminho absoluto:

```bash
MSYS_NO_PATHCONV=1 docker run --rm -v "C:/caminho/para/jornada:/w" -w /w python:3.11-slim \
  bash -c "pip install -q -r requirements.lock && python -m pytest -m 'not integration' -q"
```

**Por que isso importa tanto:** a máquina de desenvolvimento diverge do CI, e isso já custou dois
achados. Na última sessão, 8 testes falhavam localmente e **todos os 8 passavam no container** — a
causa era `starlette` 0.41 local contra 1.4.1 do lock (`TestClient(client=...)` não existe na
antiga) e WSL quebrado. Se você "consertar" um teste que só falha na sua máquina, vai quebrar o que
está certo.

`requirements.lock` **não instala no Windows** (o `uvloop` é Linux-only). Isso é esperado, não é bug.

Demais gates, no mesmo container:

```bash
python -m ruff check . && python -m ruff format --check . && python -m mypy
```

Frontend (esse pode ser local):

```bash
cd frontend && npm ci && npm run build
```

---

## 4. Credenciais e acessos

> **Nenhum segredo está escrito neste arquivo, e isso é deliberado.** Ele vive no repositório. Abaixo
> estão os **caminhos** e os **nomes de variável**; os valores ficam no `.env` do servidor e na sua
> máquina.

### 4.1 SSH da VPS

| | |
|---|---|
| Host | `187.77.46.137` — `vps.falagaiotto.com.br` |
| Usuário | `root` |
| Chave (máquina antiga) | `~/.ssh/id_ed25519_jornada` |
| Chave do CI | `~/.ssh/id_ed25519_jornada_actions` → secret `VPS_SSH_KEY` no GitHub |
| Diretório do projeto | `/opt/jornada` |

**Na máquina nova você precisa copiar a chave privada** de `~/.ssh/id_ed25519_jornada` (ou gerar uma
nova e adicioná-la ao `~/.ssh/authorized_keys` da VPS). Sem ela não há deploy manual.

Se aparecer `REMOTE HOST IDENTIFICATION HAS CHANGED`, verifique **de onde** você está rodando: numa
das sessões o comando foi disparado de dentro da própria VPS, e o auto-SSH pelo IP externo dispara
esse aviso. Estando na VPS, não use SSH — rode o comando direto.

### 4.2 Acesso à aplicação hoje

A VPS está em `APP_ENV=dev`, então o acesso é por **token estático** no header:

```
Authorization: Bearer dev-admin        (ou dev-dpo, dev-lider, dev-aprovador, dev-analista, dev-solicitante)
X-Tenant: torre-movel
```

A interface em `http://vps.falagaiotto.com.br:8050` já manda isso sozinha.

**Não existe usuário criado no banco.** O mecanismo de bootstrap do root está pronto e nunca foi
executado — verifiquei: não há `JORNADA_ROOT_*` no `.env` da VPS nem linha de bootstrap no log.

### 4.3 Variáveis do `.env` da VPS (`/opt/jornada/.env`)

| Variável | O que é | Obrigatória |
|---|---|---|
| `APP_SECRET` | segredo da aplicação (`openssl rand -hex 32`) | sim |
| `JORNADA_DB_PASSWORD` | senha do Postgres da aplicação | não (default `jornada`) |
| `JORNADA_ROOT_EMAIL` / `JORNADA_ROOT_SENHA` | bootstrap do root; vazio = nenhum root criado | não |
| `JORNADA_PURGE_TOKEN` | credencial de máquina do purge; **vazio = porta fechada** | não |
| `LANGFUSE_PK` / `LANGFUSE_SK` | chaves do projeto Langfuse | sim |
| `LANGFUSE_DB_PASSWORD`, `LANGFUSE_NEXTAUTH_SECRET`, `LANGFUSE_SALT` | infra do Langfuse | sim |
| `LANGFUSE_INIT_EMAIL` / `LANGFUSE_INIT_PASSWORD` | usuário inicial da UI do Langfuse | sim |

Para ver quais existem hoje **sem revelar valores**:

```bash
ssh -i ~/.ssh/id_ed25519_jornada root@187.77.46.137 "cd /opt/jornada && cut -d= -f1 .env | sort"
```

### 4.4 Criar o root (quando decidir)

Rode **na VPS**, com `read -s` para a senha não ficar no histórico:

```bash
cd /opt/jornada && read -s -p "Senha do root: " S && \
  printf "\nJORNADA_ROOT_EMAIL=sergio.gaiotto\nJORNADA_ROOT_SENHA=%s\n" "$S" >> .env && unset S && \
  docker compose -f docker-compose.prod.yml --env-file .env up -d api
```

Mínimo de 12 caracteres, diferente do login, senão o boot recusa e **não cria a conta**. A conta
nasce com troca obrigatória no primeiro acesso.

**Recomendação:** não crie agora. Enquanto `APP_ENV=dev`, os tokens `dev-*` continuam válidos, então
a conta não fecha porta nenhuma — só adiciona credencial num ambiente aberto e sem TLS. Faça junto do
corte (§8).

### 4.5 HubGPU (LLM da Claro)

Só responde **de dentro da rede Claro** — e a VPS está nela. Da sua máquina, as chamadas de IA falham
e a aplicação degrada para 503 + modo manual (§10.6), o que é o comportamento correto.

```
LLM_120B_BASE_URL=https://hub-gpus.claro.com.br/gpt120/v1     modelo openai/gpt-oss-120b
LLM_20B_BASE_URL=https://hub-gpus.claro.com.br/gpt20/v1       modelo openai/gpt-oss-20b
EMBED_BASE_URL=https://hub-gpus.claro.com.br/embed06b/v1      Qwen3-Embedding-0.6B, 1024 dims
LLM_API_KEY=not-needed
```

---

## 5. A história dos achados

Cinco rodadas de UAT, cada uma documentada em `docs/`. Vale ler os documentos; aqui está o mapa e,
mais importante, **os padrões** que se repetiram.

| Rodada | Documento | Achados |
|---|---|---|
| UAT #1 | `docs/UAT-VPS-2026-08-05.md` | A1–A18 |
| UAT #2 | `docs/UAT2-VPS-2026-08-06.md` | B01–B03 |
| UAT #3 | `docs/UAT3-VPS-2026-08-06-adversarial.md` | C01–C04 |
| UAT #4 | `docs/UAT4-VPS-2026-08-06-twin.md` | D01–D07 |
| UAT #5 | `docs/UAT5-2026-08-06-cacada.md` | 23 achados + 6 padrões |

### 5.1 Os achados críticos e o que eles ensinaram

**D07 — três cópias da mesma função.** O simulador devolvia HTTP 500 para um grafo que o **próprio
sistema gerou** e que o validador aprovou. A adjacência do grafo estava implementada em três lugares;
uma correção anterior alcançou duas. Virou fonte única em `domain/jornada/adjacencia.py`.

**E05 — a mesma doença, uma cópia adiante.** Eu declarei o D07 fechado e **deixei a quarta cópia** no
compilador. Todo `decisionSplit` roteado por regra exportava sem saída: na jornada aprovada da demo,
push, SMS, WhatsApp e goal ficavam órfãos no Journey Builder — cerca de R$ 3.810 de canais que o
taxímetro cobrava e nunca disparariam. O golden file do teste de contrato não tinha nenhum
`decisionSplit`, por isso o CI ficava verde.

**E01 — o Guard das 7 listas era `if lista not in texto`.** Um SQL que mira **exatamente** os
contatos suprimidos (Procon, blacklist, não-perturbe) saía com certificado válido. Corrigido duas
vezes: a primeira fechou as cinco evasões catalogadas e **reabriu a classe** com operadores vizinhos
(`NOT (…)` genérico virava `not ( )` na estrutura e casava). A segunda inverteu para **reconhecer
forma canônica** — o que o parser não reconhece não passa.

**E02 — a segregação criador ≠ aprovador não existia.** `criado_por` era gravado e nunca lido.
Também corrigido duas vezes: a primeira comparava com quem *empacotou* em vez de com quem *emite*, e
montar o pacote é um clique disponível a qualquer analista.

**F05 — o detector de PII só via dígito.** Nome, endereço, CEP, data de nascimento e RG passavam
intactos para o LLM, para o ledger e para o índice RAG (de onde **reaparecem como precedente para
outro usuário**). Numa base de telco, é a PII mais comum. Reprovado na primeira entrega pelo auditor,
que achou três abreviações de logradouro (`av.`, `trav.`, `rod.`) escritas no regex e
**inalcançáveis**, e **35% de falso positivo** em briefing legítimo.

**F01 — a simulação não reproduzia entre ambientes.** `numpy` não constava do `requirements.txt`, e o
gerador troca de **algoritmo** conforme ele esteja instalado: o mesmo grafo com a mesma seed dava
conversões P50 de 1625,0 numa máquina e 1736,5 no CI. O §6 promete o contrário, e o Previsto congelado
é a régua do realizado.

### 5.2 Os padrões — valem mais que a lista

**P1 · A emenda vai onde o bug foi reportado, não onde a doença mora.** D07 → E05, E01 → E01b,
D05 → o lint do canvas. Toda correção de UAT deve terminar com um `grep` da lógica corrigida e um
teste que rode **todos** os consumidores.

**P2 · Validação por presença, nunca por valor.** Nenhum jsonschema roda em lugar nenhum do sistema.
O `jgc.schema.json`, que o SDD chama de fonte da verdade, é lido só para extrair `required` e o enum
de tipos. **Continua aberto** e é a melhor relação conserto/dano do relatório.

**P3 · O default silencioso é zero, não recusa.** Quando o dado não casa, o sistema inventa um zero e
segue: R$ 267 mil viram R$ 0,00 com semáforo verde. O que não casa deveria virar aviso ou erro.

**P4 · Contrato maior que o código.** Regras escritas com parâmetro que ninguém passa, NFRs sem
implementação, seções descrevendo arquitetura que não existe.

**P5 · A cobertura mente; só a mutação fala.** O Guard tinha **98% de cobertura de linha** e aceitou
as duas mutações que o quebram por completo. Dez de 17 mutações no código determinístico sobreviveram
com a suíte verde.

**P6 · Identidade e escopo vindos do cliente.** Tenant no header, aprovador no corpo, política numa
constante. Em todos, o servidor tinha a informação correta e escolhia não usá-la.

### 5.3 Uma classe de bug que apareceu quatro vezes: **o teste que passa por não enxergar**

Vale destaque porque é a mais perigosa — o CI fica verde e o controle não existe.

- `E05_A7` varria `app.routes` para provar que toda rota exige tenant. No FastAPI novo a lista deixou
  de ser plana: o aceite passou a enxergar **zero rota** e seguiu verde.
- `_ROTAS_DE_LEITURA` apontava para `/api/v1/atelie/agentes`, **rota que não existe**. Passou cinco
  meses invisível porque o 403 do middleware é emitido **antes** do roteamento — o aceite recebia o
  403 que esperava sem tocar rota nenhuma.
- O golden do compilador não tinha `decisionSplit`, então o E05 não era detectável.
- O aceite de PII criava a OS com briefing **vazio** e punha PII só em `instrucoes` — verde com o
  vazamento aberto.

**Regra que ficou:** todo aceite de segurança precisa de um guarda-corpo que prove que ele está
olhando para algo. Há três deles no repositório hoje (`test_E05_A6b`, `test_achado8_guarda_corpo_politica`,
`test_F03_vigia_portao_llm`).

---

## 6. As melhorias, onda a onda

Todas com detalhe em `CHANGELOG-SDD.md`.

**Onda 1 — os cinco críticos do UAT #5.** Guard estrutural; segregação criador ≠ aprovador;
calibração com backtest que pode reprovar + rollback; tenant vindo do token; D07 completado no
compilador. Mais o **smoke funcional** no CI, que exercita o caminho crítico contra a VPS
recém-deployada e derruba o deploy se falhar — antes o smoke só provava a *versão*.

**Onda 2 — autenticação local (G01).** Usuários com argon2id, sessão revogável por cookie httpOnly,
bloqueio por tentativas, login que não revela se o e-mail existe (nem pela mensagem, nem pelo tempo),
tokens `dev-*` restritos a `APP_ENV=dev`. O **link mágico virou ponteiro**: a identidade de quem
decide vem da sessão.

> Detalhe que vale carregar: a comparação que **concede** usa igualdade exata; a que **recusa** usa
> chave de identidade (colapsa `+tag`). Alargar do lado que recusa é conservador; do lado que concede
> é escalação de privilégio.

**Onda 3 — a política do M12 governa.** Era uma tela que publicava no banco e não mudava o
comportamento de nada. Agora `holdout_min=40` publicado faz o sistema recusar holdout de 15. Junto: o
purge do §10.4 ganhou consumidor, e a PII parou de entrar pelo briefing.

**Onda 3b — IA Responsável fiada.** O módulo saiu do domínio e passou a governar sete serviços.
Publicar muda a política vigente de `origem=seed` para `origem=policy_versao`.

**Onda 3c — os bloqueantes de PII.** Detector enxergando titular identificado; Ateliê no portão;
retenção alcançando evidências; purge com agendador real.

**Onda 4 — corte para produção (no repositório, não aplicado).** Rate limit por IP; disjuntor do hub;
`except APIError`; TLS e backup preparados; **a suíte passou a autenticar por sessão**, o que a torna
executável em `APP_ENV=prod`; e o `requirements.lock`.

---

## 7. Scripts — commit, PR e deploy

### 7.1 Commit e push

```bash
# Gates ANTES de commitar — no container, sempre
MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd):/w" -w /w python:3.11-slim \
  bash -c "pip install -q -r requirements.lock && python -m pytest -m 'not integration' -q && \
           python -m ruff check . && python -m ruff format --check . && python -m mypy"
cd frontend && npm run build && cd ..

git add -A
git commit -m "..."   # e emende SDD-Jornada.md + CHANGELOG-SDD.md no MESMO commit (§1.3.3)
git push origin main
```

### 7.2 Pull request

O fluxo tem sido commit direto na `main` com o CI como gate. Se preferir PR:

```bash
git checkout -b minha-frente
git push -u origin minha-frente
gh pr create --title "..." --body "..." --base main
gh pr checks --watch
gh pr merge --squash --delete-branch
```

### 7.3 Deploy — o caminho normal (CI)

Push na `main` dispara `.github/workflows/ci.yml`. O job `deploy` roda **só** com `backend`,
`frontend` e `compose-validate` verdes, e faz: SSH → `git reset --hard origin/main` →
`docker compose up -d --build` → smoke de versão (A22) → **smoke funcional**.

```bash
gh run list --limit 3
gh run watch <ID> --exit-status
```

### 7.4 Deploy manual — quando o CI está indisponível

Use **só** quando o CI estiver fora por infraestrutura (como agora, sem cota). Nunca para contornar
um gate que **reprovou** — essa distinção é a razão de o "deploy-fantasma" não ter voltado.

```bash
# 1. Gates completos no container (§7.1). Se algo falhar, PARE.

# 2. Aplicar
ssh -i ~/.ssh/id_ed25519_jornada root@187.77.46.137 \
  "cd /opt/jornada && git fetch origin && git reset --hard origin/main && \
   export GIT_SHA=\$(git rev-parse HEAD | cut -c1-7) && \
   docker compose -f docker-compose.prod.yml --env-file .env up -d --build && \
   docker compose -f docker-compose.prod.yml --env-file .env ps"

# 3. Prova de versão
curl -s http://vps.falagaiotto.com.br:8050/healthz     # sha tem de bater com o HEAD

# 4. Smoke funcional — o que prova que FUNCIONA, não só que subiu
python scripts/smoke_funcional.py \
  --base-url http://vps.falagaiotto.com.br:8050 --sha "$(git rev-parse HEAD | cut -c1-7)"
```

**Se algum passo falhar, reverta:**

```bash
ssh -i ~/.ssh/id_ed25519_jornada root@187.77.46.137 \
  "cd /opt/jornada && git reset --hard <SHA_ANTERIOR> && \
   export GIT_SHA=<SHA_ANTERIOR> && \
   docker compose -f docker-compose.prod.yml --env-file .env up -d --build"
```

### 7.5 Scripts operacionais no repositório

| Script | O que faz |
|---|---|
| `scripts/smoke_funcional.py` | caminho crítico ponta a ponta contra a VPS; roda no CI |
| `scripts/purge_retencao.sh` | purge §10.4; dry-run por padrão |
| `scripts/backup_bancos.sh` | dump dos dois Postgres |
| `scripts/restaura_teste.sh` | **restaura em container descartável e verifica** |
| `scripts/cert_status.sh` | validade do certificado TLS |
| `deploy/deploy.sh` | instala o cron do purge e do backup |
| `deploy/tls_setup.sh` | nginx + certbot no hostname existente |
| `nginx/jornada.conf` | proxy reverso 443 |

---

## 8. Próximos passos

### 8.1 Imediato

1. ~~**Deployar a onda 4**~~ Feito em 2026-08-07: ondas 4 e 5 no ar (`bfe1cc2`), smokes verdes.
2. ~~**Verificar a cota do Actions.**~~ Feito em 2026-08-07: a cota voltou; gates verdes.
3. **Copiar a chave SSH** (`id_ed25519_jornada`) para a máquina nova — sem ela não há §7.4 nem
   edição do `.env`; o CI cobre deploy e a configuração pontual (`configurar-vps`), mais nada.

### 8.2 Antes de PII real — bloqueantes

Nenhum destes é opcional:

**TLS.** Preparado, não aplicado. `vps.falagaiotto.com.br` **já resolve** para o IP — dá para emitir
Let's Encrypt sem criar DNS. Rode `deploy/tls_setup.sh`. Muda junto: cookie `Secure`, CORS,
`NEXTAUTH_URL` do Langfuse, `APP_BASE_URL` dos links mágicos e o `--base-url` do smoke.

**Backup com restauração testada.** Os scripts existem; falta instalar o cron (`deploy/deploy.sh`) e
**rodar `restaura_teste.sh` pelo menos uma vez**. Backup não testado não é backup. Limite conhecido: o
backup mora no mesmo disco da VPS — se o disco morre, morre junto. Considere destino externo.

**Corte de ambiente.** `APP_ENV=prod` + `DEMO_MODE=false` no `docker-compose.prod.yml`, os `dev-*`
desligados, o root criado. A suíte já cobre `prod` (`test_prod_corte_de_ambiente.py`).

**Rate limit em produção.** O middleware existe e está fiado. Considere uma segunda camada no nginx —
o middleware protege a aplicação, não a máquina.

### 8.3 Achados abertos, por gravidade

| Achado | O quê |
|---|---|
| ~~**P2**~~ | **Fechado na onda 5 (I01):** o jsonschema roda inteiro no `jgc_validate`; schema emendado às formas D05/D07 antes de ligar |
| **Camada 2 do Guard** | Inerte: o read model é fixture e ignora o `sql_publico`. **A onda 6 (J01) tentou executar o SQL num sqlite e a auditoria reprovou** (dialeto PG×sqlite, vocabulário do dicionário, monocultura da base) — revertido. Fecho REAL exige o read model de produção (Postgres com a base de contatos, dialeto de destino); não há fecho barato com fixtures. **Onda 7 (K05):** o *overclaim* derivado foi fechado — o certificado agora DECLARA `contagens_derivadas_do_sql` (assinado no hash, com contract test + alçapão contra adapter que minta a proveniência) e a T5 exibe o chip "contagens não medidas do SQL". Declara o limite; não fecha a Camada 2 |
| **Ação inerte na IA Responsável** | `decisao_automatizada` governa 1 das 7 ações (`ACOES_FIADAS` = `{jornada.ajustar}`); travado por teste, não escondido. **Onda 7 (K02):** o alcance real declarado no README, derivado das constantes. **Onda 7 (K06, fatia B):** a tela parou de mentir — três estados no efeito (fiada/marcada-inerte/não marcada), resumo conta só fiadas, o 201 avisa autorização sem consumidor, e o vigia virou DERIVADO dos call sites por AST (nome em `ACOES_FIADAS` sem fiação agora reprova). **Segue aberto:** fiar as outras 6 — `otimizacao.propor` exige a decisão de produto A0 por emenda (semântica da auto-aprovação, escopo, papéis); as demais são feature nova |
| **`blackout` e `precedencia`** | No conjunto fechado, **sem consumidor**. Correção da onda 7: a linha antiga dizia "na tela" — **falso**, a política do §4.1 nunca teve tela (publica-se por `POST /api/v1/policies`); a mesma frase errada está em `CHANGELOG-SDD.md` e em `politicas.py`. `blackout` é fechável (o J04 trouxe a janela ISO que faltava); `precedencia` **não é**: subtração comuta no waterfall, `suprimidos_por_lista` é dict e o `breakers` ordena — a única versão que governaria de verdade decide *pertinência*, e isso derrubaria o contrato fechado das 7 listas (§8-M5-A1) |
| ~~**Roteamento híbrido**~~ | **Fechado na onda 5 (I02):** regra bloqueante `roteamento_ambiguo` no §5.3 + espelho no lint + editor recusa criar o híbrido |
| ~~**D06**~~ | **Fechado na onda 7 (K04 · aceite §8-M7-B6):** `PUT /grafo` MINTA versão nova (origem byte a byte intacta) em vez de mutar o registro; guarda de no-op impede que auto-save/reordenação criem versão idêntica ou apaguem o Ensaio. Fecha por construção a janela em que um PUT entre `criar_snapshot` e a decisão publicava no SFMC grafo não aprovado com o hash aprovado. **Limite declarado:** `proxima_versao` é MAX+1 sem lock — saves simultâneos colidem no `unique(os_id, versao)` |
| ~~**D04 / throttle**~~ | **Fechado na onda 6 (J04):** `wait_alem_da_janela` ligado por `janela_inicio`/`janela_fim` (ISO) no briefing; todos os chamadores de `validar_grafo` passam a janela (save/retry/PUT/ajustar/Ensaio/Optimize). `wait` por `ate` segue fora, declarado |
| ~~**Nome sem âncora**~~ | **Fechado:** o código (detector+API+tela) já estava na onda 4 — esta linha do handoff estava stale; a emenda §10.2 entrou na onda 5 (I05) |
| ~~**Teto de tokens**~~ | **Fechado na onda 6 (J02):** medição (I04) + enforcement — `teto_tokens.tokens_por_dia` por tenant/dia UTC, 429 antes de custar no portão; obrigatoriedade congelada nos 4 campos v1 |
| **e2e Playwright** | Job comentado no CI (`ci.yml:99`); não existe. Faltam **cinco** peças, não uma: runner, spec, steps, entrada no `needs` e o serviço `web` do compose de **dev**, também comentado (`docker-compose.yml:100`). Consequência a não esquecer: **nenhuma linha de React é executada por teste algum** — `EditorJornada.tsx` tem cobertura zero e `frontend/src` está fora do `--cov-fail-under=80`. **Onda 7 (K02):** o README parou de reivindicar que "um e2e prova" o modo degradado |
| **Reconciliação diária / drift 30min** | Sem scheduler. São **dois** achados de maturidade diferente: o **drift** é fechável no molde já provado do §10.4 (script + cron do host + carimbo + vigia + syslog), porque `drift_service.verificar` já é escopado por tenant e só falta o gatilho; a **reconciliação diária** não é — `reconciliar` exige um `os_id` e não há fan-out, e decidir *quais* OSs um job varre é contrato (§8-M10), não implementação. **Onda 7 (K02):** README e Guia pararam de prometer vigilância a cada 30 min |
| **§10.2 sem aceite** | ~~Aberto~~ **Fechado na onda 7 (K01):** o backup entrou na onda 4 com script, cron, cifra e prova de restauração e **zero** testes; o vigia do F04 prendia só o *primeiro* bloco ```cron do README, então o do backup divergiu sem nada ficar vermelho. Agora a paridade README↔`deploy.sh` é genérica (qualquer cron, nos dois sentidos) e o §10.2 tem o mesmo contrato de falha visível do §10.4 |
| ~~**Motor §6 × classes D05**~~ | **Fechado (D08):** cond fora do mix do governor vira AVISO nomeando nó e chaves (semáforo amarelo), determinístico e fora do loop de runs — M8-A1 preservado. ~~Aberto derivado~~ **Fechado na onda 7 (K03 · emenda D09 · aceite §8-M8-A8):** interseção VAZIA entre conds e classes (100% do volume evapora) virou bloqueante em canal próprio, com `motivos.extend(bloqueantes)` ANTES do `return "vermelho"` — e, o que importa, com CONSUMIDOR: `POST /snapshots` recusa 409 e a T9 ganhou o quinto portão. Perda parcial segue amarela por decisão. **Aberto derivado novo:** `randomSplit` tem o mesmo `.get(cond, 0)` mudo e não é coberto — a emenda nomeia `frequencySplit` de propósito |
| ~~**Tela T16 × tokens**~~ | **Fechado na onda 6 (J05):** painel de auditoria via_ai na T16 com tokens/latência (null → "—"); o conteúdo do ledger (Art. 20) redigido para quem não é dpo\|lider |
| ~~**Hash sensível à ordem**~~ | **Fechado na onda 5 (I03):** nodes/edges ordenados por id na persistência e no hash; golden intacto por construção |

### 8.4 ~~Emenda pendente ao SDD~~ — APLICADA na onda 5 (I05)

O §10.2 registra as **duas naturezas** da detecção (forma verificável × contexto probabilístico com
buracos nomeados), aponta a fonte única (`DETECCAO_DA_CATEGORIA`) sem redigitar a lista, e nomeia o
limite intransponível (nome sem âncora). A tela do DPO já exibia os limites ao lado do seletor
desde a onda 4 (`36c4f52`) — a linha desta tabela que dizia o contrário estava desatualizada.

---

## 9. Como trabalhar neste repositório

O que funcionou, e por que:

**Gates no container, sempre.** Custou dois achados aprender.

**Auditor cético separado de quem escreve.** Em quase toda onda o auditor achou algo que o autor não
viu — inclusive **reprovando** duas entregas. O prompt do auditor pergunta sempre a mesma coisa: *isto
protege de verdade, ou passa no teste que o próprio autor escreveu?*

**Inversão verificada.** Todo teste novo precisa **falhar** sem o código. Reverta a linha-chave, rode,
restaure, mostre as duas saídas. Teste que não morre sem o código é decoração.

**Limite declarado é controle; limite escondido é passivo.** Vale para o detector de PII, para o
backup e para qualquer parâmetro que não governe.

**Comentário que parece controle é pior que controle nenhum.** O cron do purge existiu como comentário
por semanas — a auditoria o contava como existente. O comentário do compose hoje avisa explicitamente
que ali não mora cron.

**Parâmetro que não muda comportamento é teatro auditável.** Se um parâmetro não tem teste que prove a
mudança **por rota HTTP**, ele não está fiado — declare como pendente em vez de entregar.
