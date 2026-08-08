"""Aceite K02 · O texto do produto não pode prometer o que o código não faz.

A auditoria da onda 7 mediu que o README e o Guia Interativo afirmavam quatro coisas
que o código não sustenta: um e2e de navegador que não existe, uma vigilância de drift
a cada 30 min que nenhum agendador executa, uma "tela de Políticas" que nunca foi
construída, e um `decisao_automatizada` que governa as 7 ações quando governa **uma**.

Isso é pior do que um README desatualizado por dois motivos:

1. `frontend/src/guia/conteudo.ts` é a **fonte única** enviada como contexto ao agente
   `ajuda` (SDD §7 · M-Guia). O que está errado ali, **a IA da plataforma repete ao
   usuário quando perguntada** — a mentira ganha voz e autoridade.
2. A doutrina do projeto é literal: *"limite declarado é controle; limite escondido é
   passivo"*. Um README que descreve o sistema ideal em vez do sistema real inverte o
   sinal — o leitor confia exatamente onde não deveria.

**Por que estes testes não são grep de prosa.** Cada um é *condicional ao estado do
código*: lê a peça que deveria existir e só então cobra a declaração. Quando alguém
finalmente instalar o cron do drift, o teste **para de exigir** a ressalva sozinho, em
vez de virar um literal que se briga com a realidade nova. É a diferença entre amarrar
texto a código e carimbar uma frase.

Limite declarado deste próprio arquivo: ele prova que a documentação **declara** o
limite. Não prova comportamento nenhum — quem prova comportamento são os aceites das
frentes que fecharem cada achado. Um teste documental que se vendesse como prova de
proteção seria a mesma doença que veio tratar.
"""

import re
from pathlib import Path

from application.services.portao_ia import ACOES_FIADAS
from domain.ia_responsavel.politica import ACOES_VIA_AI

RAIZ = Path(__file__).resolve().parents[3]
README = RAIZ / "README.md"
GUIA = RAIZ / "frontend" / "src" / "guia" / "conteudo.ts"
DEPLOY_SH = RAIZ / "deploy" / "deploy.sh"
FRONTEND_SRC = RAIZ / "frontend" / "src"


def _readme() -> str:
    return README.read_text(encoding="utf-8")


def _guia() -> str:
    return GUIA.read_text(encoding="utf-8")


# --------------------------------------------------- decisão automatizada: alcance real
def test_K02_o_readme_declara_o_alcance_real_da_decisao_automatizada() -> None:
    """O número sai das constantes, não da memória de quem escreveu o README.

    `ACOES_VIA_AI` é o vocabulário fechado que o DPO pode publicar; `ACOES_FIADAS` é o
    subconjunto com consumidor em runtime. Enquanto o segundo for menor que o primeiro,
    a tabela das 5 travas precisa dizer isso em voz alta — senão a plataforma afirma
    efeito onde não há, na tela em que o DPO governa.

    Inversão: fiar as 7 ações torna a exigência automaticamente dispensável; apagar o
    bloco de limite com o alcance ainda parcial reprova aqui.
    """
    texto = _readme()
    if len(ACOES_FIADAS) >= len(ACOES_VIA_AI):
        return  # todas fiadas: não há limite a declarar

    assert "Limite honesto (aberto)" in texto, (
        "o README não declara nenhum limite, mas `decisao_automatizada` alcança só "
        f"{len(ACOES_FIADAS)} das {len(ACOES_VIA_AI)} ações do vocabulário fechado"
    )
    # o número precisa estar escrito, e ser o número certo
    esperado = f"{len(ACOES_FIADAS)} das {len(ACOES_VIA_AI)} ações"
    assert esperado in texto, (
        f"o README precisa dizer literalmente '{esperado}' — um alcance parcial descrito "
        "por adjetivo ('parcial', 'algumas') é o que deixou o achado passar despercebido"
    )
    # e a ação que realmente tem consumidor precisa ser nomeada
    for acao in ACOES_FIADAS:
        assert acao in texto, f"o README não nomeia a ação fiada `{acao}`"


# ------------------------------------------------------------------ drift: sem agendador
def test_K02_o_guia_nao_promete_vigilancia_de_drift_que_nenhum_cron_faz() -> None:
    """A promessa mais cara do Guia, porque a IA a repete.

    O §5.4.5 especifica verificação de drift a cada 30 min. Nenhum cron a instala: o
    `deploy.sh` escreve apenas os crons do purge e do backup. Enquanto for assim, o Guia
    não pode dizer "vigiado a cada 30 min" — quem lê (ou pergunta ao agente `ajuda`)
    conclui que existe detecção automática entre uma checagem e outra, e não existe.

    Condicional de propósito: no dia em que o deploy instalar o executor do drift, este
    teste deixa de cobrar a ressalva sem que ninguém precise editá-lo.
    """
    deploy = DEPLOY_SH.read_text(encoding="utf-8")
    linha_de_cron_com_drift = r"^\s*\S+\s+\S+\s+\S+\s+\S+\s+\S+\s+\w+.*drift"
    tem_cron_de_drift = bool(re.search(linha_de_cron_com_drift, deploy, re.M))
    if tem_cron_de_drift:
        return  # o agendamento existe: a promessa passou a ser verdade

    guia = _guia()
    for promessa in ("vigiado a cada 30", "a cada 30 min", "a cada 30min"):
        assert promessa not in guia or "ainda não existe" in guia, (
            f"o Guia promete vigilância periódica ({promessa!r}) que nenhum cron executa — "
            "e este texto é o contexto que o agente `ajuda` repete ao usuário"
        )
    assert "SOB DEMANDA" in guia or "sob demanda" in guia, (
        "o Guia precisa dizer que a verificação de drift roda sob demanda"
    )

    readme = _readme()
    assert "não agendada" in readme or "Sob demanda, não agendada" in readme, (
        "o README também descreve o drift; sem a ressalva ele promete um job que não roda"
    )


# ------------------------------------------------------------------- e2e que não existe
def test_K02_o_readme_nao_reivindica_e2e_que_nao_existe() -> None:
    """Reivindicar prova é pior que não ter prova.

    Não há Playwright, spec, runner nem job ativo — `ci.yml` traz o `e2e-compose` como
    uma linha de comentário. Enquanto nada disso existir, o README não pode dizer que
    "um e2e prova" o modo degradado, e muito menos incluir o **editor** na lista do que
    está provado: nenhuma linha de React é executada por teste algum.
    """
    artefatos = [
        *FRONTEND_SRC.parent.glob("playwright.config.*"),
        *FRONTEND_SRC.parent.glob("e2e/**/*.spec.*"),
        *FRONTEND_SRC.parent.glob("tests/**/*.spec.*"),
    ]
    if artefatos:
        return  # alguém construiu o e2e: a reivindicação passou a ser legítima

    texto = _readme()
    assert "um e2e prova isso" not in texto, (
        "o README reivindica um e2e que não existe em lugar nenhum do repositório"
    )
    assert "não existe e2e de navegador" in texto, (
        "o limite precisa estar declarado, não apenas a frase falsa removida — "
        "silêncio sobre a ausência de cobertura de UI é limite escondido"
    )


# ------------------------------------------------------- tela que nunca foi construída
def test_K02_a_documentacao_nao_promete_tela_para_a_politica_do_41() -> None:
    """A política §4.1 (frequency cap, blackout, alçadas, breakers) não tem tela.

    Publica-se por `POST /api/v1/policies`. O frontend nunca chama essa rota. Enquanto
    for assim, nem o README nem o Guia podem descrever uma "tela de Políticas" — o
    operador iria procurá-la, e o Guia chegaria a descrever seus campos.

    Cuidado a preservar: a tela do DPO da **IA Responsável** (`IaResponsavel.tsx`)
    EXISTE e é outra coisa. Este teste não pode empurrar ninguém a apagá-la do texto.
    """
    # O arquivo do Guia é PROSA, não código: ele cita a rota justamente para dizer que
    # não há tela. Contá-lo como "o frontend chama /policies" faria o texto auditado
    # dispensar a própria auditoria — foi o que a inversão INV-3 pegou na primeira
    # versão deste teste, que ficava verde com a mentira reintroduzida.
    chama_policies = any(
        "/policies" in caminho.read_text(encoding="utf-8", errors="ignore")
        for caminho in FRONTEND_SRC.rglob("*.ts*")
        if caminho != GUIA
    )
    if chama_policies:
        return  # a tela (ou alguma chamada) passou a existir

    assert "tela de Políticas" not in _readme(), (
        "o README descreve uma tela de Políticas que o frontend não tem"
    )
    assert "policy drift" not in _guia(), (
        "o Guia descreve um relatório de policy drift que não existe em código nenhum"
    )
    # e a tela que EXISTE continua nomeada, para o conserto não virar apagamento
    assert (RAIZ / "frontend" / "src" / "pages" / "IaResponsavel.tsx").exists()
    assert "IA Responsável" in _guia()


# ------------------------------------------- campos do conjunto fechado sem consumidor
def test_K02_o_guia_declara_que_blackout_e_precedencia_nao_governam() -> None:
    """Parametrização que não muda comportamento é pior que nenhuma — então declare.

    `blackout` e `precedencia` estão no conjunto fechado da política e são aceitos e
    versionados, mas nenhum serviço os lê. O consumidor é procurado no código de
    verdade (domínio + aplicação, fora do arquivo que os DEFINE); enquanto não houver,
    o Guia precisa dizer que os dois não governam nada.
    """
    definicao = RAIZ / "backend" / "domain" / "governanca" / "politicas.py"
    consumidores = [
        caminho
        for caminho in (RAIZ / "backend").rglob("*.py")
        if caminho != definicao
        and "test" not in caminho.parts
        and re.search(r"""["']blackout["']""", caminho.read_text(encoding="utf-8", errors="ignore"))
    ]
    if consumidores:
        return  # alguém passou a ler o campo: a promessa virou verdade

    guia = _guia()
    assert "NÃO governam nada" in guia or "não governam nada" in guia, (
        "o Guia vende `blackout` como configuração que governa, e nenhum código o lê"
    )
