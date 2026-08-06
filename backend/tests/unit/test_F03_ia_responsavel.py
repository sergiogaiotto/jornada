"""Emenda F03 · IA Responsável — ENFORCEMENT dos parâmetros (achado 8 do UAT #5).

Todo teste aqui tem a MESMA forma, que é a única que prova governança:

    mesma entrada + política A  →  comportamento A
    mesma entrada + política B  →  comportamento B

Um teste que só verifica que `validar_conteudo` aceita um dicionário não prova nada
sobre governo — foi exatamente o que existia no M12 enquanto os portões liam a
constante. Por isso cada parâmetro do módulo tem, obrigatoriamente, um par A/B abaixo;
parâmetro sem par não entrou no conjunto FECHADO (`teto_tokens` e `rotulo_ia` ficaram
de fora justamente por não terem como ter um).

Puro: nenhum app, nenhum banco, nenhum LLM (§1.3.5) — as regras são código.
"""

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from domain.ia_responsavel import (
    DadoBloqueadoParaLlm,
    DecisaoAutomatizadaNegada,
    ModeloNaoPermitido,
    aplicar_retencao,
    categorias_detectadas,
    exigir_perfil_autorizado,
    exigir_revisao_humana,
    expira_em,
    modo_de_decisao,
    perfis_permitidos,
    politica_ia_seed,
    sanear_para_llm,
    validar_conteudo,
)
from domain.ia_responsavel.modelos import PoliticaIa
from domain.ia_responsavel.retencao import REDIGIDO

RAIZ = Path(__file__).resolve().parents[3]

# CPF com dígitos verificadores VÁLIDOS: o mascarador desempata CPF × celular por DV
# (§10.2), então um número inventado testaria outro caminho que não o pretendido.
CPF_VALIDO = "529.982.247-25"
TEXTO_COM_CPF = f"O cliente {CPF_VALIDO} reclamou da fatura"
TEXTO_COM_EMAIL = "Falar com joao.silva@exemplo.com.br sobre a oferta"


def _politica(**ajustes: object) -> dict:
    """Seed v1 com os ajustes pedidos — o resto fica no default conservador."""
    conteudo = politica_ia_seed()
    for campo, valor in ajustes.items():
        conteudo[campo] = valor
    return conteudo


def _com_acao(categoria: str, acao: str) -> dict:
    """Política igual à v1, mudando UMA categoria de PII — o A/B do parâmetro (a)."""
    conteudo = politica_ia_seed()
    conteudo["dados_llm"]["acoes"][categoria] = acao
    return conteudo


# ===================================================================== (a) dados_llm


def test_a_mesma_entrada_muda_de_destino_quando_a_politica_muda() -> None:
    """O par A/B do parâmetro (a): mascarar deixa seguir, bloquear IMPEDE a chamada.

    Este é o teste que separa governança de teatro. Se ele passar com as duas
    políticas produzindo o mesmo resultado, o parâmetro não governa nada.
    """
    # A — política v1 (cpf: mascarar): o texto segue, com o CPF trocado por marcador.
    saneado = sanear_para_llm(TEXTO_COM_CPF, _com_acao("cpf", "mascarar"))
    assert CPF_VALIDO not in saneado.texto
    assert "[CPF]" in saneado.texto
    assert saneado.categorias == ("cpf",)

    # B — mesma frase, política com cpf: bloquear: a chamada NÃO acontece.
    with pytest.raises(DadoBloqueadoParaLlm) as erro:
        sanear_para_llm(TEXTO_COM_CPF, _com_acao("cpf", "bloquear"))
    assert erro.value.categorias == ("cpf",)
    # A mensagem é lida por quem digitou o texto: precisa dizer que o dado NÃO saiu.
    assert "não foi feita" in erro.value.motivo


def test_a_bloqueio_de_uma_categoria_nao_bloqueia_texto_de_outra() -> None:
    """Bloquear cartão não pode transformar todo e-mail em erro (falso positivo custa
    o produto: o consultor pararia de responder a briefing legítimo)."""
    conteudo = _com_acao("cartao", "bloquear")
    saneado = sanear_para_llm(TEXTO_COM_EMAIL, conteudo)
    assert "[EMAIL]" in saneado.texto
    assert saneado.categorias == ("email",)


def test_a_bloqueio_vence_quando_ha_categoria_mascarada_junto() -> None:
    """Texto com e-mail (mascarar) + CPF (bloquear): bloqueia. O que sairia do
    perímetro é o texto INTEIRO, então basta uma categoria bloqueada."""
    conteudo = _com_acao("cpf", "bloquear")
    with pytest.raises(DadoBloqueadoParaLlm) as erro:
        sanear_para_llm(f"{TEXTO_COM_EMAIL} — CPF {CPF_VALIDO}", conteudo)
    assert erro.value.categorias == ("cpf",)


def test_a_marcador_digitado_pelo_usuario_nao_forja_deteccao() -> None:
    """Detecção é por DELTA de marcadores, não por presença.

    Sem isso, digitar "[CPF]" no briefing dispararia bloqueio (negação de serviço
    trivial) e, pior, o caminho inverso viraria oráculo: dava para descobrir a política
    do tenant testando strings.
    """
    assert categorias_detectadas("o campo [CPF] do formulário está vazio") == ()
    saneado = sanear_para_llm("o campo [CPF] do formulário", _com_acao("cpf", "bloquear"))
    assert saneado.texto == "o campo [CPF] do formulário"


def test_a_politica_corrompida_cai_no_piso_do_c02_em_vez_de_afrouxar() -> None:
    """Conteúdo sem `dados_llm` (linha antiga, JSON truncado) mascara mesmo assim.

    A direção do fallback é a decisão de segurança: falhar mascarando custa um
    marcador a mais; falhar liberando custa PII no prompt do modelo.
    """
    saneado = sanear_para_llm(TEXTO_COM_CPF, {})
    assert CPF_VALIDO not in saneado.texto
    assert "[CPF]" in saneado.texto


# ====================================================================== (b) retencao


def test_b_reter_prompt_governa_o_que_e_gravado_no_ledger() -> None:
    """Par A/B do parâmetro (b): o MESMO payload é gravado inteiro ou redigido."""
    payload = {"os_id": "abc", "instrucoes": "aumentar frequência no fim de semana"}

    # A — v1 (reter_prompt: true): a prova do Art. 20 continua no ledger.
    conteudo_a = politica_ia_seed()
    assert (
        aplicar_retencao(payload, conteudo_a, tipo="input")["instrucoes"] == payload["instrucoes"]
    )

    # B — tenant que abre mão da reconstrução: o texto não é gravado.
    conteudo_b = politica_ia_seed()
    conteudo_b["retencao"]["reter_prompt"] = False
    gravado = aplicar_retencao(payload, conteudo_b, tipo="input")
    assert gravado["instrucoes"] == REDIGIDO
    # A CHAVE sobrevive: a auditoria precisa ver que houve conteúdo suprimido, e não
    # um campo que aparenta nunca ter existido.
    assert "instrucoes" in gravado
    assert gravado["os_id"] == "abc"  # campo que não é texto livre não é tocado


def test_b_retencao_de_input_e_output_sao_independentes() -> None:
    """Desligar prompt não pode arrastar a resposta junto (e vice-versa) — são duas
    decisões legais distintas: uma é dado do titular, outra é decisão sobre ele."""
    conteudo = politica_ia_seed()
    conteudo["retencao"]["reter_prompt"] = False
    entrada = aplicar_retencao({"instrucoes": "x"}, conteudo, tipo="input")
    saida = aplicar_retencao({"resposta": "y"}, conteudo, tipo="output")
    assert entrada["instrucoes"] == REDIGIDO
    assert saida["resposta"] == "y"


def test_b_prazo_do_trace_muda_com_o_parametro() -> None:
    """`dias_trace` governa a janela do trace: mesma linha, política nova, data nova."""
    criada = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)
    conteudo = politica_ia_seed()
    assert expira_em(criada, conteudo).date() == datetime(2026, 9, 5, tzinfo=UTC).date()

    conteudo["retencao"]["dias_trace"] = 7
    assert expira_em(criada, conteudo).date() == datetime(2026, 8, 13, tzinfo=UTC).date()


def test_b_dias_ledger_e_recusado_porque_o_prazo_do_ledger_e_do_m12() -> None:
    """Achado do auditor: `dias_ledger` era um SEGUNDO relógio de retenção, inerte.

    Quem apaga o ledger é o `purge_service` (§10.4), e ele lê `retencao_dias` da
    política do M12 pela `PublicacoesPort` — `tests/acceptance/test_D01_purge.py` prova
    que publicar `retencao_dias: 30` muda o que some. Nada lia `dias_ledger`: o DPO
    publicaria 30, a tela confirmaria, e o purge seguiria em 180. É o achado 8 do UAT #5
    reencenado dentro do módulo criado para acabar com ele.

    Não basta remover do seed — tem de ser REJEITADO, senão volta pela API calado.
    """
    conteudo = politica_ia_seed()
    conteudo["retencao"]["dias_ledger"] = 30
    erros = validar_conteudo(conteudo)
    assert any("dias_ledger" in e and "retencao_dias" in e for e in erros)
    # E o seed não pode reintroduzir o campo pela porta dos fundos.
    assert "dias_ledger" not in politica_ia_seed()["retencao"]


def test_b_bloco_retencao_e_fechado_como_o_conteudo() -> None:
    """Sub-bloco fechado: parâmetro inerte não entra nem um nível abaixo."""
    conteudo = politica_ia_seed()
    conteudo["retencao"]["dias_embedding"] = 90
    assert any("dias_embedding" in e and "FECHADO" in e for e in validar_conteudo(conteudo))


def _sem_reter() -> dict:
    """Política do tenant que desligou a retenção dos dois lados."""
    conteudo = politica_ia_seed()
    conteudo["retencao"]["reter_prompt"] = False
    conteudo["retencao"]["reter_resposta"] = False
    return conteudo


# Payloads REAIS gravados hoje em `invocacao` (§4.1) — copiados dos `_registrar_invocacao`
# de cada serviço. O teste vale porque usa as chaves que os serviços de fato escrevem: uma
# redação testada só contra payload inventado prova que a função redige o que ela mesma
# escolheu redigir, que é precisamente o vício do achado 8.
PAYLOADS_REAIS_DO_LEDGER: tuple[tuple[str, str, dict], ...] = (
    # audiencia_service.py:392 — NENHUMA chave de texto tem nome "de prompt"
    (
        "audiencia.output",
        "output",
        {
            "sql": f"SELECT * FROM clientes WHERE cpf = '{CPF_VALIDO}'",
            "explicacao": [f"filtrei pelo CPF {CPF_VALIDO} do briefing"],
            "evidencias": ["dicionario_dados@v3"],
        },
    ),
    # criativo_service.py:108 — `kv_master` é dicionário ANINHADO derivado do briefing
    (
        "criativo.input",
        "input",
        {
            "kv_master": {"headline": f"Fale com {CPF_VALIDO}", "cta": "ligue já"},
            "instrucoes": "tom informal",
        },
    ),
    # consultor_service.py:438 — `inferencias` é LISTA de dicionários
    (
        "consultor.output",
        "output",
        {
            "resposta": "ok",
            "inferencias": [{"campo": "publico", "valor": f"clientes como {CPF_VALIDO}"}],
        },
    ),
)


@pytest.mark.parametrize(("nome", "tipo", "payload"), PAYLOADS_REAIS_DO_LEDGER)
def test_b_reter_false_nao_deixa_pii_sobrar_em_payload_real(
    nome: str, tipo: str, payload: dict
) -> None:
    """Achado do auditor: a redação tinha a POLARIDADE errada e vazava.

    A versão anterior listava chaves de texto (`instrucoes`, `resposta`...) e retinha
    todo o resto — medido contra estes payloads reais, o CPF sobrevivia nos três: o
    `output` do audiencia não tinha uma chave em comum com a lista, o `kv_master` do
    criativo era dicionário e as `inferencias` do consultor eram lista. Desligar a
    retenção suprimia o campo VISÍVEL e deixava o dado ao lado — a pior falha possível
    para um controle de privacidade, porque a auditoria acredita na supressão.
    """
    gravado = aplicar_retencao(payload, _sem_reter(), tipo=tipo)
    assert CPF_VALIDO not in str(gravado), f"{nome}: PII sobreviveu à redação em {gravado}"


def test_b_redacao_e_deny_by_default_para_chave_nova() -> None:
    """Chave que ninguém previu nasce REDIGIDA, não retida.

    É o mesmo antídoto do conjunto FECHADO de `politica.py`: o serviço que amanhã
    acrescentar `{"anotacao_do_analista": ...}` ao ledger não pode criar um vazamento
    por omissão de quem escreveu esta lista meses antes.
    """
    gravado = aplicar_retencao(
        {"chave_que_ninguem_previu": "texto livre com dado do titular"},
        _sem_reter(),
        tipo="input",
    )
    assert gravado["chave_que_ninguem_previu"] == REDIGIDO


def test_b_redacao_preserva_correlacao_e_metrica() -> None:
    """Redigir não pode cegar a auditoria: id, referência versionada e número ficam.

    Suprimir `os_id`/`evidencias` junto com o texto trocaria um problema por outro —
    a linha viraria impossível de correlacionar, e o Art. 20 pede o oposto disso.
    """
    gravado = aplicar_retencao(
        {
            "os_id": "OS-2026-0457",
            "jornada_base_id": "b1",
            "evidencias": ["dicionario_dados@v3"],
            "descartadas": 2,
            "valido": True,
            "resumo": "texto que sai",
        },
        _sem_reter(),
        tipo="output",
    )
    assert gravado["os_id"] == "OS-2026-0457"
    assert gravado["jornada_base_id"] == "b1"
    assert gravado["evidencias"] == ["dicionario_dados@v3"]
    assert gravado["descartadas"] == 2
    assert gravado["valido"] is True
    assert gravado["resumo"] == REDIGIDO


def test_b_redacao_nao_muta_o_payload_original() -> None:
    """O serviço ainda precisa do texto original para a chamada em curso — redigir a
    estrutura recebida (agora que a função é recursiva) corromperia o prompt."""
    original = {"kv_master": {"headline": "texto"}, "instrucoes": "x"}
    aplicar_retencao(original, _sem_reter(), tipo="input")
    assert original == {"kv_master": {"headline": "texto"}, "instrucoes": "x"}


def test_b_default_retem_porque_o_art20_exige_reconstruir() -> None:
    """Guarda-corpo de doutrina: se alguém "minimizar" o default para não reter, este
    teste morre e obriga a discussão — reconstrução do Art. 20 depende do ledger."""
    conteudo = politica_ia_seed()
    assert conteudo["retencao"]["reter_prompt"] is True
    assert conteudo["retencao"]["reter_resposta"] is True


# ========================================================== (c) decisao_automatizada


def test_c_allowlist_governa_propor_versus_aplicar() -> None:
    """Par A/B do parâmetro (c): a MESMA ação muda de modo conforme a política."""
    # A — v1: allowlist vazia. Tudo propõe (é o comportamento de hoje do `ajustar`).
    conteudo_a = politica_ia_seed()
    assert modo_de_decisao("jornada.ajustar", conteudo_a) == "propor"
    with pytest.raises(DecisaoAutomatizadaNegada) as erro:
        exigir_revisao_humana("jornada.ajustar", conteudo_a)
    assert erro.value.acao == "jornada.ajustar"
    assert "Art. 20" in erro.value.motivo

    # B — DPO autoriza explicitamente: a mesma ação passa a poder aplicar sozinha.
    conteudo_b = _politica(decisao_automatizada={"pode_aplicar_sozinho": ["jornada.ajustar"]})
    assert modo_de_decisao("jornada.ajustar", conteudo_b) == "aplicar"
    exigir_revisao_humana("jornada.ajustar", conteudo_b)  # não levanta


def test_c_autorizar_uma_acao_nao_autoriza_as_vizinhas() -> None:
    """Allowlist é por ação: liberar o twin não pode liberar o otimizador."""
    conteudo = _politica(decisao_automatizada={"pode_aplicar_sozinho": ["jornada.ajustar"]})
    assert modo_de_decisao("otimizacao.propor", conteudo) == "propor"


def test_c_acao_desconhecida_nunca_e_automatizada() -> None:
    """Typo na allowlist falha para o lado SEGURO (segue propondo), e a validação
    recusa a publicação — o DPO descobre na hora, não na auditoria."""
    conteudo = _politica(decisao_automatizada={"pode_aplicar_sozinho": ["jornada.ajusta"]})
    assert modo_de_decisao("jornada.ajusta", conteudo) == "propor"
    assert any("ação desconhecida" in e for e in validar_conteudo(conteudo))


def test_c_conteudo_corrompido_nao_libera_automacao() -> None:
    assert modo_de_decisao("jornada.ajustar", {}) == "propor"
    assert modo_de_decisao("jornada.ajustar", {"decisao_automatizada": {}}) == "propor"


# =========================================================== (f) modelos_permitidos


def test_f_perfil_fora_da_lista_do_agente_e_recusado() -> None:
    """Par A/B do parâmetro (f): o mesmo agente+perfil passa ou é barrado."""
    # A — v1 pina o roster §7.2: engineer é 120b.
    conteudo_a = politica_ia_seed()
    exigir_perfil_autorizado("engineer", "120b", conteudo_a)  # não levanta
    assert perfis_permitidos("engineer", conteudo_a) == ("120b",)

    # B — tenant restringe o engineer ao modelo pequeno.
    conteudo_b = politica_ia_seed()
    conteudo_b["modelos_permitidos"]["engineer"] = ["20b"]
    with pytest.raises(ModeloNaoPermitido) as erro:
        exigir_perfil_autorizado("engineer", "120b", conteudo_b)
    assert erro.value.agente == "engineer"
    assert erro.value.perfil == "120b"


def test_f_typo_no_nome_do_agente_e_recusado_na_publicacao() -> None:
    """Achado do auditor: agente fora do roster §7.2 passava calado na validação.

    O DPO escrevia `enginer: ["20b"]` achando que restringira o engineer. A entrada
    virava letra morta, `perfis_permitidos("engineer", ...)` caía no roster e o 120b
    seguia liberado — restrição publicada, assinada e sem efeito. Mesma classe do typo
    em `ACOES_VIA_AI`, que o módulo já recusava; faltava a simetria aqui.
    """
    conteudo = politica_ia_seed()
    conteudo["modelos_permitidos"]["enginer"] = ["20b"]
    assert any("agente desconhecido" in e and "enginer" in e for e in validar_conteudo(conteudo))
    # A prova de que era inerte: o agente de verdade continua com o roster aberto.
    assert perfis_permitidos("engineer", conteudo) == ("120b",)


def test_f_agente_desconhecido_nao_ganha_modelo_por_omissao() -> None:
    """Agente que não está na política NEM no roster §7.2 não é liberado por silêncio."""
    conteudo = politica_ia_seed()
    assert perfis_permitidos("agente_novo_sem_roster", conteudo) == ()
    with pytest.raises(ModeloNaoPermitido):
        exigir_perfil_autorizado("agente_novo_sem_roster", "20b", conteudo)


# =================================================== conjunto FECHADO e anti-inércia


def test_conjunto_fechado_recusa_parametro_sem_enforcement() -> None:
    """O antídoto do achado 8 aplicado ao próprio módulo.

    `teto_tokens` é o exemplo VIVO: parece responsável, e seria inerte, porque
    `invocacao.tokens` é sempre NULL (`LLMPort.chat` devolve `str` e descarta o
    `usage`). Enquanto a medição não existir, publicar o campo é proibido pela
    validação — não por convenção, por código.
    """
    conteudo = politica_ia_seed()
    conteudo["teto_tokens"] = {"por_os": 100_000}
    erros = validar_conteudo(conteudo)
    assert any("teto_tokens" in e and "conjunto FECHADO" in e for e in erros)


def test_nao_existe_acao_permitir_para_pii() -> None:
    """O piso do C02 não é configurável: nenhuma política pode DESLIGAR o mascaramento.

    Se um dia `permitir` for aceito, este teste morre — e é para morrer barulhento: a
    tela de IA Responsável viraria o maior vetor de vazamento da plataforma.
    """
    conteudo = _com_acao("email", "permitir")
    erros = validar_conteudo(conteudo)
    assert any("permitir" in e for e in erros)
    # E, mais importante que a validação: o caminho de execução continua mascarando.
    assert "[EMAIL]" in sanear_para_llm(TEXTO_COM_EMAIL, conteudo).texto


def test_validacao_acumula_erros_em_vez_de_parar_no_primeiro() -> None:
    """Padrão do parser §7.1 — quem edita é o DPO pela tela, não um dev com stack trace."""
    erros = validar_conteudo({"dados_llm": {"acoes": {"cpf": "permitir"}}, "desconhecido": 1})
    assert len(erros) >= 3  # campos obrigatórios faltando + ação inválida + campo estranho


def test_seed_v1_passa_na_propria_validacao() -> None:
    """Trava de deriva: default e validação não podem divergir (um campo novo no seed
    sem entrada em CAMPOS_CONTEUDO tornaria a v1 impublicável)."""
    assert validar_conteudo(politica_ia_seed()) == []


def test_seed_devolve_estrutura_nova_a_cada_chamada() -> None:
    """É função, não constante: um teste que mexe no default não pode envenenar outro."""
    primeira = politica_ia_seed()
    primeira["retencao"]["dias_trace"] = 1
    assert politica_ia_seed()["retencao"]["dias_trace"] == 30


def test_entidade_nasce_draft_e_guarda_autoria() -> None:
    """Auditabilidade: a linha responde "quem e quando" sem correlacionar log."""
    politica = PoliticaIa(
        id=uuid.uuid4(),
        tenant_id="torre-movel",
        versao=1,
        conteudo=politica_ia_seed(),
        autor_id=uuid.uuid4(),
        autor_nome="DPO da Torre",
        motivo="v1 — espelha o comportamento vigente",
    )
    assert politica.estado == "draft"
    assert politica.publicada is False


# ============================================================ guarda-corpo do achado 8


def test_nenhum_servico_importa_a_seed_direto() -> None:
    """A regra que o achado 8 do UAT #5 cobrou, agora vigiada no CI para ESTE módulo.

    Irmão do `test_achado8_guarda_corpo_politica` (M12): serviço que importa a semente
    lê uma constante compilada, e a tela volta a publicar no vazio. A fonte em runtime
    tem de ser a política PUBLICADA, lida por porta e injetada.
    """
    servicos = RAIZ / "backend" / "application" / "services"
    ofensores = [
        arquivo.name
        for arquivo in servicos.glob("*.py")
        if "politica_ia_seed" in arquivo.read_text(encoding="utf-8")
        or "ia_responsavel.politica import" in arquivo.read_text(encoding="utf-8")
    ]
    assert ofensores == [], (
        f"{ofensores} importam a SEMENTE da política de IA Responsável. "
        "Em runtime a política vem da linha PUBLICADA, injetada por porta (achado 8)."
    )
