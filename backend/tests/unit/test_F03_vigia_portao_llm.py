"""VIGIA de CI: nenhuma chamada ao LLM sem autorização de modelo e saneamento ANTES.

Este arquivo existe por causa da atribuição que a auditoria fez do buraco do Ateliê. O
`atelie_service` não foi uma regressão de nenhuma onda: ele é vão herdado do M12 — um
único commit no arquivo, nascido antes de haver portão. O que as ondas erraram foi não
ter vigia capaz de pegá-lo. Enquanto o guarda-corpo só sabia dizer "o arquivo menciona
`portao_ia`?", o Ateliê podia chamar o hub três vezes sem conferir nada, e o próximo
serviço podia nascer igual — em silêncio, com a suíte verde.

## Por que AST, e não `grep` nem contagem de ocorrências

O guarda-corpo anterior (em `tests/acceptance/test_F03_ia_responsavel_enforcement.py`)
contava `_llm.chat(` menos `portao.autorizar_modelo(` por arquivo. Contagem casada
empata com pelo menos três furos reais, e todos passam numa revisão distraída:

1. **ordem** — autorizar DEPOIS do `chat` conta igual. O dado já saiu; a recusa vira
   um 409 emitido depois do vazamento, que é pior que não ter recusa, porque a tela
   informa que a política funcionou.
2. **par trocado** — autorizar `skill.modelo_perfil` e chamar com o literal `"20b"`
   fecha a conta e manda o dado a um modelo que ninguém conferiu. É EXATAMENTE a
   divergência declarada do `criativo_service`, e a contagem não a via: quem a
   encontrou foi um comentário no serviço, não um teste.
3. **função errada** — autorizar num método e chamar em outro fecha a conta do arquivo
   inteiro enquanto o call site segue nu.

Por isso o vigia lê a ÁRVORE: para cada `chat`, dentro da função que o contém, tem de
existir (a) uma `autorizar_modelo` ANTERIOR cujo segundo argumento seja a MESMA
expressão passada em `perfil=`, e (b) algum `sanear*` do portão ANTES da chamada.

## O que este vigia deliberadamente NÃO prova

Ele não prova que o texto saneado é o texto que foi ao prompt — isso é indecidível
estaticamente, e um serviço determinado consegue satisfazê-lo saneando uma string que
joga fora. Essa metade é dos testes POR ROTA (`test_F03_ia_responsavel_enforcement.py`),
que publicam a política e cobram o efeito colateral. O vigia cobre a outra metade, que
é a que os testes por rota nunca cobrem: o call site que ninguém lembrou de escrever
teste, no serviço que ainda não existe.

E ele é conservador de propósito em um ponto: `portao.sanear(...)` escrito DENTRO dos
argumentos do próprio `chat` é acusado, embora Python o avalie antes da chamada. O vigia
compara linhas, e a primeira vítima da regra foi o `_executar_lado` desta mesma onda. A
troca é deliberada — o custo é uma linha a mais no serviço, e o ganho é que saneamento
some do meio de uma expressão aninhada, onde nem revisor nem teste o distinguem de
saneamento nenhum. Falso positivo que se corrige escrevendo mais claro; nunca falso
negativo.

## A lista de exceções é DECLARADA, e comparada nos dois sentidos

Exceção some quando a dívida é paga (senão a lista vira desculpa permanente) e exceção
nova obriga alguém a escrever por que aquele call site pode ficar de fora. Hoje ela tem
UMA entrada, herdada e já documentada em prosa no próprio serviço.
"""

import ast
from dataclasses import dataclass
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
SERVICOS = BACKEND / "application" / "services"

# Métodos do `PortaoIa` que contam como saneamento de entrada (§10.2 · parâmetro (a)).
# Prefixo e não lista fechada: `sanear_estrutura` nasceu nesta onda e um `sanear_*` novo
# não pode fazer o vigia parar de reconhecer saneamento no dia em que for criado.
PREFIXO_SANEAMENTO = "sanear"
AUTORIZACAO = "autorizar_modelo"

# Uma `def` ou `async def`. Alias porque a união escrita por extenso estoura a linha nas
# três assinaturas abaixo, e trocá-la por `Any` faria o vigia abrir mão da checagem de
# tipo que ele próprio existe para cobrar dos outros.
Funcao = ast.FunctionDef | ast.AsyncFunctionDef

# ---------------------------------------------------------------- exceções DECLARADAS
#
# Chave = (arquivo, função que contém o `chat`). Por FUNÇÃO e não por LINHA de propósito:
# número de linha envelhece no primeiro `black` e a exceção passaria a apontar para outro
# código — uma isenção que se move sozinha é pior que nenhuma.
EXCECOES_DECLARADAS: dict[tuple[str, str], str] = {
    ("criativo_service.py", "_avisos_compliance"): (
        "Warn de linguagem do M6: único `chat` da plataforma com perfil LITERAL "
        "(`'20b'`) atribuído ao agente `content`, cujo roster §7.2 declara 120b. "
        "Chamar `autorizar_modelo('content', '20b')` recusaria a geração de criativo "
        "sob a política DEFAULT, e o default não pode mudar numa fiação. A correção é "
        "do ROSTER (entrada própria de 20b, como o `guard` já tem), não do call site — "
        "está declarada em prosa na docstring de `_avisos_compliance` e registrada como "
        "EMENDA SUGERIDA. O saneamento também falta aqui: os textos julgados vêm do "
        "`kv_master` e das células, que já passaram pelo portão em `gerar`."
    ),
}


@dataclass(frozen=True)
class Achado:
    """Um call site de LLM que o vigia considera desprotegido."""

    arquivo: str
    funcao: str
    linha: int
    motivos: tuple[str, ...]

    def __str__(self) -> str:
        return f"{self.arquivo}:{self.linha} em {self.funcao}() — " + "; ".join(self.motivos)


def _atributo(chamada: ast.Call) -> str:
    """Nome do método chamado (`portao.sanear(...)` → `sanear`); vazio se não for método."""
    return chamada.func.attr if isinstance(chamada.func, ast.Attribute) else ""


def _perfil(chamada: ast.Call) -> str | None:
    """Expressão passada em `perfil=`, como texto — `None` quando o argumento não existe.

    Comparar EXPRESSÕES (via `ast.unparse`) e não valores é o ponto: o vigia não sabe
    nem precisa saber quanto vale `skill.modelo_perfil` em runtime; ele sabe que o que
    foi conferido tem de ser literalmente o que foi chamado.
    """
    for kw in chamada.keywords:
        if kw.arg == "perfil":
            return ast.unparse(kw.value)
    return None


def _chamadas_por_funcao(arvore: ast.AST) -> dict[Funcao, list[ast.Call]]:
    """Toda `Call` atribuída à função MAIS INTERNA que a contém.

    Atribuição pela função interna, e não por `ast.walk` a partir da externa, porque o
    contrário deixaria uma autorização do método externo "cobrir" um `chat` escondido
    numa função aninhada — um empate de contagem com outro nome.
    """
    mapa: dict[Funcao, list[ast.Call]] = {}

    def visitar(no: ast.AST, funcao: Funcao | None) -> None:
        for filho in ast.iter_child_nodes(no):
            interna = filho if isinstance(filho, Funcao) else funcao
            if isinstance(filho, ast.Call) and funcao is not None:
                mapa.setdefault(funcao, []).append(filho)
            visitar(filho, interna)

    visitar(arvore, None)
    return mapa


def analisar(arquivo: str, codigo: str) -> list[Achado]:
    """Call sites de `chat` sem autorização/saneamento anteriores, na mesma função.

    Função pública (sem `_`) porque é ela que os testes de INVERSÃO exercitam sobre
    fontes sintéticas: um vigia cuja lógica só roda sobre o repositório real não tem
    como provar que enxerga a infração que promete pegar.
    """
    achados: list[Achado] = []
    for funcao, chamadas in _chamadas_por_funcao(ast.parse(codigo)).items():
        chats = [c for c in chamadas if _atributo(c) == "chat"]
        if not chats:
            continue
        autorizacoes = [c for c in chamadas if _atributo(c) == AUTORIZACAO]
        saneamentos = [c for c in chamadas if _atributo(c).startswith(PREFIXO_SANEAMENTO)]
        for chat in chats:
            motivos: list[str] = []
            perfil = _perfil(chat)
            autorizados = {
                ast.unparse(a.args[1])
                for a in autorizacoes
                if len(a.args) >= 2 and a.lineno <= chat.lineno
            }
            if perfil is None:
                # Sem `perfil=` a chamada cai no default do `LLMPort` — modelo escolhido
                # por omissão é exatamente o que o parâmetro (f) não consegue governar.
                motivos.append(
                    "chamada sem `perfil=` explícito (default do LLMPort escapa da política)"
                )
            elif perfil not in autorizados:
                motivos.append(
                    f"perfil {perfil!r} não foi conferido antes "
                    f"(autorizados nesta função, antes da linha: {sorted(autorizados) or 'nenhum'})"
                )
            if not any(s.lineno <= chat.lineno for s in saneamentos):
                motivos.append("nenhum `portao.sanear*` antes da chamada")
            if motivos:
                achados.append(Achado(arquivo, funcao.name, chat.lineno, tuple(motivos)))
    return achados


def referencias_indiretas(arquivo: str, codigo: str) -> list[str]:
    """`chat` alcançado por um caminho que a análise de CALL SITE não consegue ver.

    Achado da auditoria desta frente, e ele é de outra natureza que os sete de cima. O
    vigia identifica a chamada pelo NOME do método (`no.func.attr == "chat"`); duas
    escritas legítimas de Python fazem esse nome sumir da posição em que ele olha:

        chamar = self._llm.chat          # alias: o `Call` tem `func=Name`, não Attribute
        chamar([pedido], perfil="120b")

        getattr(self._llm, "chat")(...)  # o nome vira string

    A diferença para o limite que a docstring do módulo já declara ("um serviço
    determinado consegue satisfazê-lo saneando uma string que joga fora") é que ali a
    chamada continua VISÍVEL e o vigia continua cobrando o par; aqui a chamada
    desaparece do relatório inteiro, e com ela some a própria pergunta. Some em
    silêncio: o alias não é sabotagem, é o que alguém escreve para não repetir
    `self._llm.chat` dentro de um laço — e a suíte fica verde.

    Por isso a regra é sobre a FORMA de alcançar `chat`, e não sobre quem chama: em
    `application/services/` o método só pode aparecer como chamada direta de atributo.
    Devolve strings (e não `Achado`) porque não há call site para apontar — é
    exatamente esse o problema.
    """
    arvore = ast.parse(codigo)
    # Todo `Attribute` que ocupa a posição de FUNÇÃO de uma chamada; qualquer outro uso
    # de `.chat` é o método virando VALOR, que é o alias.
    em_posicao_de_chamada = {
        id(no.func)
        for no in ast.walk(arvore)
        if isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute)
    }
    achados: list[str] = []
    for no in ast.walk(arvore):
        if isinstance(no, ast.Attribute) and no.attr == "chat":
            if id(no) not in em_posicao_de_chamada:
                achados.append(f"{arquivo}:{no.lineno} — `.chat` referenciado como VALOR (alias)")
        elif (
            isinstance(no, ast.Call)
            and isinstance(no.func, ast.Name)
            and no.func.id == "getattr"
            and len(no.args) >= 2
            and isinstance(no.args[1], ast.Constant)
            and no.args[1].value == "chat"
        ):
            achados.append(f"{arquivo}:{no.lineno} — `getattr(..., 'chat')` esconde o call site")
    return achados


def _achados_do_repositorio() -> list[Achado]:
    return [
        achado
        for caminho in sorted(SERVICOS.glob("*.py"))
        for achado in analisar(caminho.name, caminho.read_text(encoding="utf-8"))
    ]


# =============================================================== o vigia propriamente
def test_todo_chat_confere_o_perfil_e_saneia_antes_de_chamar() -> None:
    """Nenhum call site desprotegido além dos DECLARADOS — comparado nos dois sentidos."""
    achados = {(a.arquivo, a.funcao): a for a in _achados_do_repositorio()}

    novos = sorted(str(a) for chave, a in achados.items() if chave not in EXCECOES_DECLARADAS)
    assert not novos, (
        "chamada ao LLM sem autorização de modelo e/ou saneamento antes (§10.2, §7.2):\n"
        + "\n".join(f"  - {linha}" for linha in novos)
        + "\n\nO conserto é sempre o mesmo e cabe em duas linhas, imediatamente antes do "
        "`chat`: `portao.autorizar_modelo(<agente>, <o MESMO perfil que vai em perfil=>)` "
        "e `portao.sanear(...)`/`sanear_estrutura(...)` no texto que entra no prompt "
        "(`portao = portao_ia.de(self._publicacoes_ia, tenant_id)`). Se este call site "
        "REALMENTE não puder ser fiado, declare-o em `EXCECOES_DECLARADAS` com o motivo "
        "por escrito — uma isenção que ninguém precisou justificar é como o Ateliê passou "
        "três versões chamando o hub sem política."
    )

    quitadas = sorted(
        f"{arquivo}::{funcao}"
        for arquivo, funcao in EXCECOES_DECLARADAS
        if (arquivo, funcao) not in achados
    )
    assert not quitadas, (
        f"exceções que não correspondem mais a um call site desprotegido: {quitadas}. "
        "Remova-as de `EXCECOES_DECLARADAS` — dívida declarada que não encolhe deixa de "
        "ser dívida e vira desculpa."
    )


def test_nenhum_chat_e_alcancado_por_alias_ou_getattr() -> None:
    """Protege o VIGIA, não o estilo: um `chat` invisível não tem par para cobrar.

    O teste acima cuida do `chat` que mora fora da pasta varrida; este cuida do `chat`
    que mora DENTRO dela e mesmo assim some do relatório, porque o nome do método deixou
    de estar onde a análise de call site olha. Os dois fecham a mesma porta por fora e
    por dentro.
    """
    fugitivos = [
        achado
        for caminho in sorted(SERVICOS.glob("*.py"))
        for achado in referencias_indiretas(caminho.name, caminho.read_text(encoding="utf-8"))
    ]
    assert not fugitivos, (
        "`chat` alcançado por alias ou `getattr` em `application/services/`:\n"
        + "\n".join(f"  - {linha}" for linha in fugitivos)
        + "\n\nEscreva a chamada direta (`self._llm.chat(..., perfil=...)`) para que o "
        "vigia possa cobrar dela a autorização de modelo e o saneamento. Um call site "
        "que o vigia não enumera não é um call site protegido — é um call site que "
        "ninguém está olhando."
    )


def test_nenhum_chat_ao_llm_mora_fora_de_application_services() -> None:
    """O vigia varre `application/services/`; um `chat` fora dali fugiria dele inteiro.

    Não é hipótese: o caminho mais curto para um endpoint novo falar com o modelo é
    chamar o hub direto da rota, e nesse caso não há serviço nenhum para o vigia ler. A
    regra de arquitetura (§2.1 — caso de uso mora em `application/`) passa a ter um
    teste, e ele existe para proteger o vigia, não o estilo.
    """
    permitidos = (BACKEND / "adapters" / "llm", BACKEND / "tests", SERVICOS)
    fugitivos = [
        f"{caminho.relative_to(BACKEND)}"
        for caminho in BACKEND.rglob("*.py")
        if not any(pasta in caminho.parents or pasta == caminho.parent for pasta in permitidos)
        and "__pycache__" not in caminho.parts
        and ".chat(" in caminho.read_text(encoding="utf-8")
    ]
    assert not fugitivos, (
        f"`.chat(` fora de `application/services/`: {fugitivos}. O portão de IA "
        "Responsável é fiado nos serviços e o vigia de CI só varre essa pasta — uma "
        "chamada ao hub em rota, adapter de domínio ou script nasce sem política e sem "
        "vigia. Mova o caso de uso para `application/services/` (§2.1)."
    )


# ======================================================= INVERSÃO: o vigia enxerga?
#
# Um guarda-corpo que nunca falhou é indistinguível de um guarda-corpo quebrado. Cada
# fonte abaixo é uma das formas de furo que a CONTAGEM anterior deixava passar, escrita
# em Python de verdade e analisada pela MESMA função que roda sobre o repositório.

CORRETO = """
class Servico:
    def gerar(self, tenant_id):
        portao = portao_ia.de(self._publicacoes_ia, tenant_id)
        pedido = portao.sanear(self._pedido)
        portao.autorizar_modelo(skill.nome, skill.modelo_perfil)
        return self._llm.chat([pedido], perfil=skill.modelo_perfil)
"""


def test_inversao_a_forma_correta_nao_e_acusada() -> None:
    """Contraprova primeiro: um vigia que acusa tudo passaria em todos os testes abaixo."""
    assert analisar("ok.py", CORRETO) == []


def test_inversao_chat_sem_autorizacao_nenhuma() -> None:
    """O furo do Ateliê antes desta onda: sanea, mas ninguém confere o modelo."""
    fonte = CORRETO.replace(
        "        portao.autorizar_modelo(skill.nome, skill.modelo_perfil)\n", ""
    )
    (achado,) = analisar("furo.py", fonte)
    assert "não foi conferido antes" in achado.motivos[0]


def test_inversao_autorizacao_depois_da_chamada() -> None:
    """Ordem: autorizar DEPOIS do `chat` fecha a contagem e não impede nada.

    O dado já saiu do perímetro quando a recusa acontece — e a tela informa ao usuário
    que a política funcionou, que é a pior combinação possível para uma auditoria.
    """
    fonte = """
class Servico:
    def gerar(self, tenant_id):
        portao = portao_ia.de(self._publicacoes_ia, tenant_id)
        pedido = portao.sanear(self._pedido)
        texto = self._llm.chat([pedido], perfil=skill.modelo_perfil)
        portao.autorizar_modelo(skill.nome, skill.modelo_perfil)
        return texto
"""
    (achado,) = analisar("furo.py", fonte)
    assert "não foi conferido antes" in achado.motivos[0]


def test_inversao_perfil_conferido_diferente_do_perfil_chamado() -> None:
    """O par trocado — a divergência do `criativo_service`, que a contagem empatava."""
    fonte = CORRETO.replace("perfil=skill.modelo_perfil)", 'perfil="20b")')
    (achado,) = analisar("furo.py", fonte)
    assert "'20b'" in achado.motivos[0] and "skill.modelo_perfil" in achado.motivos[0]


def test_inversao_chat_sem_saneamento() -> None:
    """Perfil conferido e texto cru: o modelo autorizado recebe o CPF do titular."""
    fonte = CORRETO.replace(
        "        pedido = portao.sanear(self._pedido)\n", "        pedido = self._pedido\n"
    )
    (achado,) = analisar("furo.py", fonte)
    assert achado.motivos == ("nenhum `portao.sanear*` antes da chamada",)


def test_inversao_autorizacao_em_outro_metodo_nao_cobre_o_call_site() -> None:
    """Autorizar num método e chamar em outro fecha a conta do ARQUIVO e não protege nada."""
    fonte = """
class Servico:
    def preparar(self, portao):
        portao.autorizar_modelo(skill.nome, skill.modelo_perfil)
        portao.sanear(self._pedido)

    def gerar(self):
        return self._llm.chat([self._pedido], perfil=skill.modelo_perfil)
"""
    achados = analisar("furo.py", fonte)
    assert [a.funcao for a in achados] == ["gerar"]
    assert len(achados[0].motivos) == 2  # sem autorização E sem saneamento


def test_inversao_o_alias_de_metodo_some_do_relatorio_de_call_sites() -> None:
    """A contraprova do achado: `analisar` NÃO vê o alias, e é por isso que há o outro teste.

    Os dois asserts juntos são o ponto. O primeiro mostra o buraco (o call site sumiu do
    relatório: zero achados, e nenhuma autorização foi conferida); o segundo mostra o
    guarda-corpo que passou a cobri-lo. Provar só o segundo deixaria a impressão de que
    `analisar` já dava conta.
    """
    fonte = """
class Servico:
    def gerar(self, tenant_id):
        chamar = self._llm.chat
        return chamar([self._pedido], perfil="120b")
"""
    assert analisar("furo.py", fonte) == [], "se passar a acusar, este teste virou obsoleto"
    (indireta,) = referencias_indiretas("furo.py", fonte)
    assert "alias" in indireta


def test_inversao_getattr_esconde_o_call_site() -> None:
    """`getattr(self._llm, "chat")` — o nome do método vira string e sai da AST."""
    fonte = """
class Servico:
    def gerar(self, tenant_id):
        return getattr(self._llm, "chat")([self._pedido], perfil="120b")
"""
    assert analisar("furo.py", fonte) == []
    (indireta,) = referencias_indiretas("furo.py", fonte)
    assert "getattr" in indireta


def test_inversao_a_chamada_direta_nao_e_confundida_com_alias() -> None:
    """Contraprova: a forma CORRETA não pode disparar o guarda-corpo novo."""
    assert referencias_indiretas("ok.py", CORRETO) == []


def test_inversao_perfil_implicito_nao_passa() -> None:
    """Sem `perfil=` a chamada herda o default do `LLMPort` — modelo por omissão.

    É o furo mais barato de todos: o call site fica MAIS curto que o correto, então
    ninguém estranha em revisão, e a política de modelos perde a chamada inteira.
    """
    fonte = CORRETO.replace(", perfil=skill.modelo_perfil)", ")")
    (achado,) = analisar("furo.py", fonte)
    assert achado.motivos[0].startswith("chamada sem `perfil=`")
