"""F04 · a tela do DPO declara a NATUREZA do detector e onde ele PARA (§10.2).

## O achado, um nível mais fundo

A onda 3c fechou o achado 8 no eixo do EFEITO: cada parâmetro da tela de IA Responsável
tem um teste que prova que mexer nele muda comportamento. `nome: bloquear` passa nesse
critério — o enforcement existe, a chamada morre.

Falta o eixo da CONFIANÇA. `mascarar.py` detecta por duas naturezas diferentes:

* por FORMA (`cpf`, `cnpj`, `email`, `telefone`, `cartao`, `documento`, `cep`, `rg`) — o
  formato basta, e onde é ambíguo há dígito verificador ou Luhn para confirmar;
* por CONTEXTO (`nome`, `endereco`, `data_nascimento`) — não têm forma; o sinal é como o
  dado aparece escrito, e os buracos são conhecidos e nomeados.

A tela mostrava as onze na mesma linha, com o mesmo seletor, com a mesma firmeza. O DPO
assina `nome: bloquear` acreditando ter fechado a porta, e "Maria Aparecida da Silva
Santos" solto numa frase continua saindo para o modelo. Parametrização honesta no efeito
e desonesta na confiança continua sendo teatro auditável — pior, porque agora tem
assinatura embaixo.

## O que estes testes amarram

Os limites são texto, e texto mente sozinho com o tempo. Por isso cada um viaja com um
`exemplo` EXECUTÁVEL e este arquivo roda o detector real sobre ele, nas DUAS direções:

* o `exemplo` de cada limite tem de sair INTACTO — se alguém fechar o buraco em
  `mascarar.py`, o teste quebra e obriga a APAGAR o aviso da tela. Limite já resolvido
  que segue sendo exibido é mentira na direção contrária, e assusta o DPO para o lado
  errado;
* o `detecta` de cada categoria tem de sair com o MARCADOR certo — se alguém quebrar a
  detecção, o teste quebra antes de a tela prometer o que o detector não faz mais.

E a trava de vocabulário: categoria nova sem natureza declarada (ou de contexto sem
limites) não compila conceitualmente — o CI para. É a mesma régua de `politica.py`
aplicada ao próprio texto que a tela mostra.
"""

import re
from pathlib import Path

from application.services.ia_responsavel_service import _vocabulario
from domain.ia_responsavel.dados import MARCADOR_DA_CATEGORIA
from domain.ia_responsavel.politica import (
    CATEGORIAS_PII,
    DETECCAO_DA_CATEGORIA,
    NATUREZA_CONTEXTO,
    NATUREZAS,
)
from domain.privacidade.mascarar import mascarar_pii, mascarar_pii_em_campo

RAIZ = Path(__file__).resolve().parents[3]
TELA = RAIZ / "frontend" / "src" / "pages" / "IaResponsavel.tsx"


def _mascarar(exemplo: str, chave: str) -> str:
    """O caminho REAL do dado: pela chave do formulário quando o limite é de chave."""
    return mascarar_pii_em_campo(chave, exemplo) if chave else mascarar_pii(exemplo)


# ============================================ (I) trava de vocabulário: nada entra mudo


def test_toda_categoria_publicavel_declara_a_natureza_da_deteccao() -> None:
    """Categoria nova sem natureza é uma linha a mais na tela com confiança desconhecida.

    O DPO não tem como saber se o seletor que ele acabou de mexer vale para sempre ou
    às vezes — e "às vezes" é a informação que decide se ele pode assinar.
    """
    sem_natureza = [c for c in CATEGORIAS_PII if c not in DETECCAO_DA_CATEGORIA]
    assert sem_natureza == [], (
        f"{sem_natureza} são publicáveis e não declaram natureza de detecção. "
        "Declare em `DETECCAO_DA_CATEGORIA` (politica.py), com exemplo executável."
    )
    orfas = [c for c in DETECCAO_DA_CATEGORIA if c not in CATEGORIAS_PII]
    assert orfas == [], f"{orfas} declaram natureza e não são publicáveis (§10.2)"


def test_natureza_declarada_e_uma_das_duas_conhecidas() -> None:
    invalidas = {
        categoria: deteccao.natureza
        for categoria, deteccao in DETECCAO_DA_CATEGORIA.items()
        if deteccao.natureza not in NATUREZAS
    }
    assert invalidas == {}, f"natureza fora de {NATUREZAS}: {invalidas}"


def test_categoria_de_contexto_e_obrigada_a_declarar_os_limites() -> None:
    """Detecção por contexto TEM buraco por construção: declarar zero é a promessa que
    esta frente existe para desfazer. Se um dia um detector de contexto ficar completo,
    ele deixou de ser de contexto — é o `NATUREZA_FORMA` que muda, não a lista vazia."""
    mudas = [
        categoria
        for categoria, deteccao in DETECCAO_DA_CATEGORIA.items()
        if deteccao.natureza == NATUREZA_CONTEXTO and not deteccao.limites
    ]
    assert mudas == [], (
        f"{mudas} detectam por CONTEXTO e não declaram um limite sequer. "
        "Cobertura parcial sem os buracos nomeados é o achado 8 na confiança do detector."
    )


def test_todo_limite_tem_texto_para_o_DPO_e_exemplo_executavel() -> None:
    """Texto sem exemplo não é verificável e apodrece; exemplo sem texto não é legível."""
    quebrados = [
        f"{categoria}: {limite}"
        for categoria, deteccao in DETECCAO_DA_CATEGORIA.items()
        for limite in deteccao.limites
        if not limite.texto.strip() or not limite.exemplo.strip()
    ]
    assert quebrados == [], quebrados


# ================================ (II) as duas pontas: o texto da tela contra o detector


def test_todo_exemplo_de_limite_REALMENTE_vaza_hoje() -> None:
    """A ponta que impede o aviso de virar mentira quando o buraco for fechado.

    Se `mascarar.py` passar a pegar um destes casos, este teste quebra — e é isso que se
    quer: o CI obriga a apagar da tela um limite que não existe mais. Aviso desatualizado
    faz o DPO desconfiar de uma proteção que ele já tem, que é o erro simétrico do que
    esta frente conserta.
    """
    fechados = [
        f"{categoria}: {limite.chave or 'texto livre'} → {limite.exemplo!r}"
        for categoria, deteccao in DETECCAO_DA_CATEGORIA.items()
        for limite in deteccao.limites
        if _mascarar(limite.exemplo, limite.chave) != limite.exemplo
    ]
    assert fechados == [], (
        "estes limites NÃO vazam mais — o detector melhorou e a tela do DPO ficou "
        f"desatualizada. Remova-os de `DETECCAO_DA_CATEGORIA`: {fechados}"
    )


def test_todo_exemplo_de_deteccao_REALMENTE_e_mascarado_hoje() -> None:
    """A ponta simétrica: o exemplo que a tela mostra como "detectado hoje" tem de ser.

    E com o marcador CERTO — `mascarar_pii` alterar o texto não basta, porque um exemplo
    de `endereco` que saísse como `[TELEFONE]` provaria detecção da categoria errada e a
    tela seguiria dizendo que endereço é reconhecido.
    """
    falhos = []
    for categoria, deteccao in DETECCAO_DA_CATEGORIA.items():
        saida = mascarar_pii(deteccao.detecta)
        marcador = MARCADOR_DA_CATEGORIA[categoria]
        if marcador not in saida:
            falhos.append(f"{categoria}: {deteccao.detecta!r} → {saida!r} (esperado {marcador})")
    assert falhos == [], "a tela promete detectar e o detector não detecta mais: " + "; ".join(
        falhos
    )


# ============================================== (III) o backend SERVE isso para a tela


def test_vocabulario_entrega_natureza_e_limites_de_toda_categoria() -> None:
    """O front não redigita nada disto — e é o que o mantém vivo (§10.2).

    Os limites moram junto do detector e mudam com ele; servidos, a tela acompanha
    sozinha. Copiados para o React, envelhecem na primeira mexida em `mascarar.py`.
    """
    categorias = {c["chave"]: c for c in _vocabulario()["categorias_pii"]}
    assert set(categorias) == set(CATEGORIAS_PII)
    for chave, servida in categorias.items():
        deteccao = DETECCAO_DA_CATEGORIA[chave]
        assert servida["natureza"] == deteccao.natureza
        assert servida["natureza_rotulo"].strip(), f"{chave} sem rótulo de natureza"
        assert servida["natureza_texto"].strip(), f"{chave} sem explicação da natureza"
        assert servida["exemplo_detectado"] == deteccao.detecta
        assert [limite["texto"] for limite in servida["limites"]] == [
            limite.texto for limite in deteccao.limites
        ]
        assert servida["rotulo"] != chave or chave not in CATEGORIAS_PII, (
            f"{chave} chega à tela com a chave técnica no lugar do rótulo"
        )


def test_efeito_de_categoria_de_contexto_nao_promete_cobertura_total() -> None:
    """ "CPF detectado INTERROMPE a chamada" e "Nome detectado INTERROMPE a chamada" são a
    mesma frase sobre confianças diferentes. A ressalva vem na MESMA frase, não numa nota
    de rodapé — o cartão de efeito é o que o DPO lê antes de decidir."""
    from application.services.ia_responsavel_service import efeitos_em_portugues
    from domain.ia_responsavel import politica_ia_seed

    conteudo = politica_ia_seed()
    conteudo["dados_llm"]["acoes"]["nome"] = "bloquear"
    conteudo["dados_llm"]["acoes"]["cpf"] = "bloquear"
    itens = {
        item["chave"]: item["efeito"]
        for bloco in efeitos_em_portugues(conteudo)
        if bloco["parametro"] == "dados_llm"
        for item in bloco["itens"]
    }
    assert "INTERROMPE" in itens["cpf"] and "CONTEXTO" not in itens["cpf"]
    assert "INTERROMPE" in itens["nome"] and "CONTEXTO" in itens["nome"]


# ==================================================== (IV) a tela mostra, e não redigita


def _tela_sem_comentarios() -> str:
    """O contrato é o código: comentário CITA o achado, JSX é o que o DPO enxerga."""
    return re.sub(r"/\*.*?\*/", "", TELA.read_text(encoding="utf-8"), flags=re.DOTALL)


def test_a_tela_renderiza_a_natureza_e_os_limites_servidos() -> None:
    """B03/F04: o que o usuário lê é contrato. Se o campo chega e ninguém o desenha, o
    backend fica honesto e a tela continua mentindo — que é o estado de antes.

    Procura-se a forma de ACESSO (`categoria.natureza_texto`), nunca o nome nu do campo.
    A primeira versão deste teste buscava `"natureza_texto"` e a inversão não falhou: o
    nome também aparece na declaração `interface CategoriaPii`, três linhas de tipo que
    existem mesmo quando nada é renderizado. O teste passava olhando para o TypeScript e
    não para o JSX — a mesma forma do achado F01, um aceite verde por estar mirando no
    lugar errado. Só o `categoria.` na frente prova que o valor servido é LIDO.
    """
    corpo = _tela_sem_comentarios()
    ausentes = [
        campo
        for campo in (
            "categoria.natureza_rotulo",
            "categoria.natureza_texto",
            "categoria.exemplo_detectado",
            "categoria.limites",
            "limite.texto",
            "limite.exemplo",
        )
        if campo not in corpo
    ]
    assert ausentes == [], f"a tela não desenha {ausentes} — o DPO não vê os limites"


def test_a_tela_nao_carrega_copia_dos_limites() -> None:
    """Se um limite estiver escrito no React, ele sobrevive à correção do detector.

    O modo de falha é silencioso e conhecido: `mascarar.py` melhora, o backend para de
    declarar o buraco, e a tela continua exibindo o texto antigo porque ele mora nela.
    """
    corpo = _tela_sem_comentarios()
    copiados = [
        f"{categoria}: {trecho!r}"
        for categoria, deteccao in DETECCAO_DA_CATEGORIA.items()
        for limite in deteccao.limites
        for trecho in (limite.texto, limite.exemplo)
        if trecho in corpo
    ]
    assert copiados == [], (
        "texto de limite HARDCODED na tela — ele tem de vir do `vocabulario` do "
        f"backend, onde mora junto do detector: {copiados}"
    )
