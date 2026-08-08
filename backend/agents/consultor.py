"""Agente consultor (roster §7.2: perfil 120b, etapa pedido/T2) — lado determinístico.

Carrega o SKILL.md canônico (§7.1: front-matter + corpo), monta as mensagens de chat e
interpreta a saída do LLM com guarda-corpos de CÓDIGO:
- só campos obrigatórios do briefing são aceitos como inferência (§1.3.5: nunca
  inventar campo fora do SDD);
- `exige_evidencia: true` → inferência sem evidência é DESCARTADA (§8-M3-A3: toda
  inferência carrega evidências);
- completude/faltantes NUNCA vêm do LLM (domain/intake/completude.py).
PII (§1.3.5/§10.2): o prompt recebe conteúdo do briefing, faltantes e mensagem — jamais
o bloco `solicitante` do pedido. Atenção ao que esta linha NÃO diz: briefing e mensagem
são texto livre do usuário e PODEM conter PII digitada; quem garante que aqui chegam
limpos é o serviço, que mascara na fronteira de entrada (`consultor_service`, §10.2 —
achado 9 do UAT #5: até então este docstring prometia "sem PII" uma garantia que o
código não dava, porque só a `mensagem` era mascarada). Este módulo é puro: não mascara
nada e não deve — mascarar aqui seria o segundo ponto de verdade que o C02 proibiu.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any, cast

from application.ports.llm import PerfilModelo
from domain.agentes import compliance
from domain.atelie.skill_parser import parse_skill_md
from domain.intake.completude import valor_do_campo, valor_presente
from domain.intake.janela import parse_data_iso
from domain.intake.modelos import (
    CAMPO_JANELA_FIM,
    CAMPO_JANELA_INICIO,
    CAMPOS_INFERIVEIS,
    CAMPOS_OBRIGATORIOS,
)

SKILL_PATH = Path(__file__).resolve().parent / "skills" / "consultor.skill.md"


@dataclass(frozen=True)
class Skill:
    """SKILL.md parseado (§7.1): front-matter YAML simples + corpo (prompt de sistema)."""

    nome: str
    versao: str
    camada: str
    modelo_perfil: PerfilModelo
    etapa: str
    exige_evidencia: bool
    corpo: str
    meta: dict[str, str] = field(default_factory=dict)  # front-matter cru restante
    bases_rag: tuple[str, ...] = ()  # bases autorizadas ao retriever (§7.1/§7.4 — A11)


@dataclass(frozen=True)
class Inferencia:
    campo: str
    valor: Any
    evidencias: tuple[str, ...]


@dataclass(frozen=True)
class SaidaConsultor:
    resposta: str
    inferencias: tuple[Inferencia, ...]


@cache
def carregar_skill(caminho: Path = SKILL_PATH) -> Skill:
    """SKILL.md validado pelo parser PLENO do Ateliê (§7.1 — domain/atelie/skill_parser;
    o parser mínimo do M3 foi substituído no M12, como prometido). Cacheado por caminho."""
    parseada = parse_skill_md(caminho.read_text(encoding="utf-8"))
    return Skill(
        nome=parseada.nome,
        versao=parseada.versao,
        camada=parseada.camada,
        modelo_perfil=cast(PerfilModelo, parseada.modelo_perfil),  # validado no parser
        etapa=parseada.etapa,
        exige_evidencia=parseada.exige_evidencia,
        corpo=parseada.corpo,
        meta=parseada.meta,
        bases_rag=parseada.bases_rag,
    )


def montar_mensagens(
    skill: Skill,
    conteudo: dict[str, Any],
    faltantes: list[str],
    mensagem: str,
    precedentes: Sequence[dict[str, str]] = (),
    burla_compliance: Sequence[str] = (),
) -> list[dict[str, str]]:
    """Mensagens OpenAI-style. SEM PII: nunca inclui o `solicitante` do pedido (§1.3.5).

    A2 (UAT real): com `faltantes` vazio (conversa de OS com briefing completo — rota
    de briefing da OS), o contexto DIZ isso ao modelo — consultoria estratégica, sem
    inventar pendência nem repetir pergunta de campo já preenchido.

    `precedentes` (A11 — §7.4): evidências do retriever (bases_rag da skill: campanhas
    históricas/ofertas) no formato citável que a skill já espera — "Precedentes
    citáveis ... são evidência adicional". Vazio → chave fora do contexto (prompt
    idêntico ao pré-A11).

    `burla_compliance` (C01 — UAT #3): marcadores detectados por CÓDIGO
    (domain/agentes/compliance) na mensagem. Presentes, o contexto carrega a diretriz
    inegociável — o modelo recebe o fato pronto em vez da tarefa de decidir se recusa
    (a recusa em si já é carimbada por código na resposta, no serviço). Vazio → chave
    fora do contexto (prompt idêntico ao pré-C01)."""
    resumo = {
        campo: valor_do_campo(conteudo, campo)
        for campo in CAMPOS_OBRIGATORIOS
        if valor_presente(valor_do_campo(conteudo, campo))
    }
    contexto: dict[str, Any] = {
        "campos_obrigatorios": list(CAMPOS_OBRIGATORIOS),
        "conteudo_atual": resumo,
        "faltantes": faltantes,
        "mensagem_do_solicitante": mensagem,
    }
    if precedentes:
        contexto["precedentes"] = list(precedentes)
    if burla_compliance:  # C01: diretriz determinística, não sugestão
        contexto["guarda_compliance"] = {
            "marcadores": list(burla_compliance),
            "instrucao": compliance.DIRETRIZ_PROMPT,
        }
    if not faltantes:
        contexto["briefing_completo"] = True
        contexto["instrucao"] = (
            "briefing completo: atue como consultor ESTRATÉGICO da campanha "
            "(riscos, oportunidades, cadência, canais, próximos passos) sobre o "
            "conteúdo atual; NÃO invente faltantes nem pergunte por campo já "
            "preenchido."
        )
    return [
        {"role": "system", "content": skill.corpo},
        {"role": "user", "content": json.dumps(contexto, ensure_ascii=False)},
    ]


def _extrair_json(texto: str) -> dict[str, Any] | None:
    try:
        dados = json.loads(texto)
        return dados if isinstance(dados, dict) else None
    except ValueError:
        inicio, fim = texto.find("{"), texto.rfind("}")
        if 0 <= inicio < fim:
            try:
                dados = json.loads(texto[inicio : fim + 1])
                return dados if isinstance(dados, dict) else None
            except ValueError:
                return None
    return None


def interpretar_saida(texto: str, *, exige_evidencia: bool = True) -> SaidaConsultor:
    """Saída do LLM → SaidaConsultor com guarda-corpos determinísticos (docstring do módulo).

    JSON malformado → degrada para resposta textual sem inferências (nada é inventado).
    """
    dados = _extrair_json(texto)
    if dados is None:
        return SaidaConsultor(resposta=texto.strip(), inferencias=())
    resposta = str(dados.get("resposta") or "").strip() or texto.strip()
    inferencias: list[Inferencia] = []
    brutas = dados.get("inferencias")
    for bruta in brutas if isinstance(brutas, list) else []:
        if not isinstance(bruta, dict):
            continue
        campo, valor = bruta.get("campo"), bruta.get("valor")
        # J04: a whitelist é CAMPOS_INFERIVEIS (obrigatórios + janela estruturada
        # opcional) — campo fora dela continua descartado, como sempre (§1.3.5).
        if campo not in CAMPOS_INFERIVEIS or not valor_presente(valor):
            continue  # nunca campo fora do contrato; valor vazio não infere nada
        # J04 (auditoria da onda 6): a janela estruturada é ISO YYYY-MM-DD ou NÃO ENTRA.
        # Descartar aqui, na fronteira, distingue "não declarei" de "declarei em formato
        # BR e a regra ficou inerte em silêncio" — o 120b tende a emitir '01/07/2026'
        # em pt-BR, e um valor presente-mas-inválido enganaria o usuário (chip
        # "confirmado" na tela, regra do §5.3 morta). Melhor não gravar do que gravar
        # um limite que não governa.
        if campo in (CAMPO_JANELA_INICIO, CAMPO_JANELA_FIM) and parse_data_iso(valor) is None:
            continue
        cruas = bruta.get("evidencias")
        evidencias = tuple(
            str(e).strip() for e in (cruas if isinstance(cruas, list) else []) if str(e).strip()
        )
        if exige_evidencia and not evidencias:
            continue  # A3: toda inferência carrega evidências (precedentes)
        inferencias.append(Inferencia(campo=campo, valor=valor, evidencias=evidencias))
    return SaidaConsultor(resposta=resposta, inferencias=tuple(inferencias))
