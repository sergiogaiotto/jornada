"""F04 · reprodutibilidade: `requirements.lock` é a verdade da máquina (§3.2/§13).

## O achado que abriu esta frente

`~=X.Y` parece um pin e não é: significa `>=X.Y, <X+1.0`. Medido no container,
`fastapi~=0.115` instalou **0.141** — 26 minor versions de folga. Como cada máquina
resolvia na sua data, dev, CI e VPS podiam estar rodando bibliotecas diferentes no MESMO
commit, e o commit deixava de determinar o comportamento.

Já cobrou o preço: o aceite `E05_A7` varria `app.routes` para provar que toda rota exige
tenant. No FastAPI novo a lista deixou de ser plana, o aceite passou a enxergar ZERO rota
e continuou VERDE (emenda F01). Um aceite de SEGURANÇA que passa por cegueira é pior que
aceite nenhum, porque ele assina embaixo.

## Por que pip-compile e não `pip freeze`

`pip freeze` fotografa um AMBIENTE: leva junto o que alguém instalou à mão (o próprio
pip-tools, o `pytest-cov` que só o CI usa, um pacote de debug esquecido) e não sabe dizer
por que cada linha existe. Congelar a máquina de dev é justamente o gesto que a emenda
F01 proíbe — a máquina de dev DIVERGE.

`pip-compile` RESOLVE a partir da declaração, dentro do mesmo `python:3.11-slim` que roda
em produção, e anota `# via` em cada linha: dá para ver que `anthropic` está ali por causa
de `deepagents`, e não por acaso. Essa anotação não é só documentação — é o que torna este
gate possível: `# via -r requirements.txt` marca quais linhas do lock são dependências
DIRETAS, e é comparando esse conjunto com `requirements.txt` que se descobre que os dois
arquivos se separaram.

## Hashes ficaram de fora, e é uma escolha, não esquecimento

`--generate-hashes` daria garantia de supply-chain, e foi testado. Ele liga o
`--require-hashes` GLOBAL do pip: a partir daí nenhum requisito pode vir com faixa, e
`pip install -r requirements.txt` (com os `~=X.Y` legíveis) passa a falhar. O resultado
seria dev instalando de um arquivo e CI de outro — reintroduzindo, pela porta dos fundos,
exatamente a divergência que esta frente veio fechar. Hashes entram quando `requirements.
txt` deixar de ser instalável por humano, não antes.

## Os três gates aqui, e por que são três

1. lock × requirements — os ARQUIVOS combinam (roda em qualquer lugar);
2. ambiente × lock — o que está INSTALADO é o do lock (só onde o gate está armado; é
   este que teria pego o F01, porque arquivo com arquivo não vê ambiente);
3. Dockerfile/CI × gate — o (2) continua ARMADO. Sem o (3), apagar uma linha do
   Dockerfile transforma o (2) num skip permanente e o gate apodrece calado.
"""

import importlib.metadata as metadata
import os
import re
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

RAIZ = Path(__file__).resolve().parents[3]
REQUIREMENTS = RAIZ / "requirements.txt"
LOCK = RAIZ / "requirements.lock"
DOCKERFILE = RAIZ / "backend" / "Dockerfile"
CI = RAIZ / ".github" / "workflows" / "ci.yml"

# Variável que ARMA o gate de ambiente. Setada no `backend/Dockerfile` e no job `backend`
# do CI — os dois lugares onde o ambiente foi construído a partir do lock. Na máquina de
# dev ela não existe, e o teste pula em vez de acusar uma divergência que o
# desenvolvedor não pediu (ele pode ter instalado de `requirements.txt` de propósito).
GATE_ARMADO = "JORNADA_DEPS_DO_LOCK"

_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._\-]*)==([^\s#]+)\s*$")


def _declaradas() -> dict[str, Requirement]:
    """Dependências DIRETAS, como o humano as escreveu em `requirements.txt`."""
    diretas: dict[str, Requirement] = {}
    for linha in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        crua = linha.split(" #")[0].strip()
        if not crua or crua.startswith(("#", "-")):
            continue
        requisito = Requirement(crua)
        diretas[canonicalize_name(requisito.name)] = requisito
    return diretas


def _travadas() -> dict[str, tuple[str, set[str]]]:
    """`{pacote: (versao, vias)}` do lock. `vias` = quem pediu (anotação do pip-compile).

    Duas formas de anotação convivem no arquivo e as duas contam: `# via fastapi` numa
    linha só, e o bloco `# via` seguido de `#   fastapi` / `#   -r requirements.txt`
    quando mais de um pacote pede o mesmo.
    """
    travadas: dict[str, tuple[str, set[str]]] = {}
    atual: str | None = None
    for linha in LOCK.read_text(encoding="utf-8").splitlines():
        casamento = _PIN.match(linha)
        if casamento:
            atual = canonicalize_name(casamento.group(1))
            travadas[atual] = (casamento.group(2), set())
            continue
        anotacao = linha.strip()
        if not anotacao.startswith("#") or atual is None:
            continue
        conteudo = anotacao.lstrip("#").strip()
        if conteudo.startswith("via"):
            conteudo = conteudo[len("via") :].strip()
        if conteudo:
            travadas[atual][1].add(conteudo)
    return travadas


def test_lock_existe_e_so_tem_versao_exata() -> None:
    """Uma única faixa no lock e ele deixa de ser lock: volta a resolver na data do build."""
    assert LOCK.exists(), "requirements.lock não existe — o Dockerfile e o CI instalam dele"
    frouxas = [
        linha
        for linha in LOCK.read_text(encoding="utf-8").splitlines()
        if linha.strip() and not linha.startswith(("#", " ", "\t")) and not _PIN.match(linha)
    ]
    assert frouxas == [], f"lock com linha que não é `pacote==versao`: {frouxas}"


def test_toda_dependencia_declarada_esta_travada_e_dentro_da_faixa() -> None:
    """O gate que impede os dois arquivos de se separarem em silêncio.

    Pega os três jeitos de divergir: acrescentar linha em `requirements.txt` sem
    regenerar (some do lock), apertar a faixa sem regenerar (o pin fica fora dela) e
    trocar `~=0.115` por `~=0.200` achando que o ambiente acompanha (não acompanha — o
    ambiente vem do lock).
    """
    travadas = _travadas()
    ausentes = [nome for nome in _declaradas() if nome not in travadas]
    assert ausentes == [], (
        f"{ausentes} estão em requirements.txt e NÃO no lock. Regenere o lock — o "
        "comando reprodutível está no cabeçalho dele."
    )
    fora_da_faixa = [
        f"{requisito.name}: lock tem {travadas[nome][0]}, requirements.txt pede "
        f"{requisito.specifier}"
        for nome, requisito in _declaradas().items()
        if str(requisito.specifier)
        and not requisito.specifier.contains(travadas[nome][0], prereleases=True)
    ]
    assert fora_da_faixa == [], (
        "a versão travada não satisfaz o que requirements.txt declara: " + "; ".join(fora_da_faixa)
    )


def test_dependencia_declarada_consta_no_lock_como_DIRETA() -> None:
    """Estar no lock não basta: tem de estar ali PORQUE alguém declarou.

    Este teste nasceu de uma inversão que NÃO falhou. Acrescentar `requests~=2.32` a
    `requirements.txt` sem regenerar o lock mantinha o gate acima VERDE — `requests` já
    estava no lock como transitivo de `langchain`/`langfuse`/`langsmith`, então
    `ausentes` saía vazio e a faixa `~=2.32` era satisfeita por acaso pelo 2.34.2 que o
    resolvedor tinha escolhido para OUTRA pessoa.

    O efeito é o do próprio achado F01, em miniatura: a declaração nova nunca passou
    pelo resolvedor, e o que está instalado é coincidência de uma resolução feita para
    outro requisito. No dia em que `langchain` deixar de depender de `requests`, o
    pacote some do lock com a linha ainda em `requirements.txt` — e a imagem passa a
    subir sem uma dependência declarada.

    `pip-compile` escreve `# via -r requirements.txt` só no que resolveu como DIRETO.
    Exigir esse marcador é o que separa "declarei e regenerei" de "declarei e esqueci",
    e é a direção simétrica do teste seguinte.
    """
    travadas = _travadas()
    sem_marcador = [
        nome
        for nome in _declaradas()
        if nome in travadas and "-r requirements.txt" not in travadas[nome][1]
    ]
    assert sem_marcador == [], (
        f"{sem_marcador} estão em requirements.txt mas o lock só os traz como "
        "TRANSITIVOS — a declaração nunca passou pelo resolvedor. Regenere o lock: o "
        "comando reprodutível está no cabeçalho dele."
    )


def test_lock_nao_tem_dependencia_direta_que_ninguem_declarou() -> None:
    """A outra direção: apagar uma linha de `requirements.txt` sem regenerar o lock.

    O pacote continuaria sendo instalado em produção, marcado como direto, sem nenhum
    humano tendo pedido — e sem o comentário que explica por que ele existe. É como o
    `numpy` da emenda F01 entrou: dependência de fato, declaração nenhuma.
    """
    declaradas = _declaradas()
    orfas = [
        nome
        for nome, (_, vias) in _travadas().items()
        if "-r requirements.txt" in vias and nome not in declaradas
    ]
    assert orfas == [], (
        f"{orfas} constam no lock como dependência DIRETA e sumiram de requirements.txt. "
        "Regenere o lock, ou devolva a linha (com o comentário que diz por que ela existe)."
    )


@pytest.mark.skipif(
    not os.getenv(GATE_ARMADO),
    reason=(
        f"{GATE_ARMADO} não setada: este ambiente não foi construído a partir do lock. "
        "O gate está armado no backend/Dockerfile e no job `backend` do CI."
    ),
)
def test_ambiente_instalado_e_exatamente_o_do_lock() -> None:
    """O gate que arquivo-com-arquivo não consegue dar: o que está INSTALADO aqui.

    É o que teria pego o F01 no dia em que o FastAPI pulou de 0.115 para 0.141 sozinho.
    Só o sentido lock → instalado é conferido: `pytest-cov`/`coverage` (só CI, §13) e o
    próprio pip não constam do lock e não são divergência.
    """
    divergentes = []
    for nome, (travada, _) in _travadas().items():
        try:
            instalada = metadata.version(nome)
        except metadata.PackageNotFoundError:
            divergentes.append(f"{nome}: lock pede {travada}, NÃO está instalado")
            continue
        if instalada != travada:
            divergentes.append(f"{nome}: lock pede {travada}, instalado {instalada}")
    assert divergentes == [], (
        "o ambiente saiu do lock — este commit não determina mais o que roda: "
        + "; ".join(divergentes)
        + ". Instale com `pip install -r requirements.lock`."
    )


def test_dockerfile_e_ci_instalam_do_lock_e_mantem_o_gate_armado() -> None:
    """Sem isto o gate acima apodrece: basta apagar uma linha e ele vira skip eterno.

    Um gate que só roda quando alguém lembra de armá-lo é um gate que não existe — e o
    modo de falha é o pior possível, porque a suíte continua VERDE enquanto para de
    olhar (é a forma exata do achado F01).
    """
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    ci = CI.read_text(encoding="utf-8")
    faltas = []
    if "-r requirements.lock" not in dockerfile:
        faltas.append("backend/Dockerfile não instala de requirements.lock")
    if re.search(r"pip install[^\n]*-r requirements\.txt", dockerfile):
        faltas.append("backend/Dockerfile ainda instala de requirements.txt (resolve na data)")
    if GATE_ARMADO not in dockerfile:
        faltas.append(f"backend/Dockerfile não seta {GATE_ARMADO}")
    if "pip install -r requirements.lock" not in ci:
        faltas.append("ci.yml não instala de requirements.lock")
    if GATE_ARMADO not in ci:
        faltas.append(f"ci.yml não seta {GATE_ARMADO}")
    assert faltas == [], "; ".join(faltas)
