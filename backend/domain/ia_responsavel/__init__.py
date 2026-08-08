"""Contexto de domínio `ia_responsavel` — as parametrizações de IA que GOVERNAM.

Nasce do achado 8 do UAT #5 (docs/UAT5-2026-08-06-cacada.md), que encontrou uma tela de
Políticas publicando versão no banco enquanto todos os portões liam uma constante
compilada. A conclusão do achado é a regra deste pacote:

    **Parametrização que não muda comportamento é pior que nenhuma: vira teatro
    auditável.**

Por isso o pacote é só REGRA PURA (zero I/O, zero LLM, testável sem app) e cada função
exportada é um ENFORCEMENT: recebe o `conteudo` da política PUBLICADA — lido por porta e
INJETADO pelo serviço, nunca importado como constante — e ou muda o resultado, ou
levanta erro de domínio.

Cinco parâmetros governam (o quinto entrou na onda 6):

| campo | módulo | o que muda quando o DPO mexe |
|---|---|---|
| `dados_llm` | `dados.py` | PII de categoria `bloquear` impede a chamada ao modelo |
| `retencao` | `retencao.py` | prompt/resposta deixam de ser gravados; prazo do purge |
| `decisao_automatizada` | `decisao.py` | ação sai de "IA propõe" para "IA aplica" |
| `modelos_permitidos` | `modelos_llm.py` | perfil fora da lista não é chamado |
| `teto_tokens` | `teto.py` | gasto medido do dia no teto → 429 antes de custar (J02) |

Seguem FORA, por decisão registrada em `politica.py`: `teto_custo` (exige tarifa
R$/token que não existe no domínio) e `rotulo_ia` (o enforcement é a UI de ~10 telas).
Voltam junto do teste que provar que mudam comportamento — a mesma régua que este
módulo aplica ao resto da plataforma.
"""

from domain.ia_responsavel.dados import Saneamento, categorias_detectadas, sanear_para_llm
from domain.ia_responsavel.decisao import (
    exigir_revisao_humana,
    modo_de_decisao,
    pode_aplicar_sozinho,
)
from domain.ia_responsavel.erros import (
    DadoBloqueadoParaLlm,
    DecisaoAutomatizadaNegada,
    ModeloNaoPermitido,
    PoliticaIaInvalida,
)
from domain.ia_responsavel.modelos import ESTADOS, PoliticaIa
from domain.ia_responsavel.modelos_llm import (
    exigir_perfil_autorizado,
    perfil_autorizado,
    perfis_permitidos,
)
from domain.ia_responsavel.politica import (
    ACOES_DADO,
    ACOES_VIA_AI,
    CAMPOS_CONTEUDO,
    CATEGORIAS_PII,
    DETECCAO_DA_CATEGORIA,
    NATUREZA_CONTEXTO,
    NATUREZA_FORMA,
    NATUREZAS,
    PERFIL_DO_ROSTER,
    PERFIS_MODELO,
    Deteccao,
    LimiteDeteccao,
    politica_ia_seed,
    validar_conteudo,
)
from domain.ia_responsavel.retencao import (
    aplicar_retencao,
    deve_reter_prompt,
    deve_reter_resposta,
    dias_retencao,
    expira_em,
)

__all__ = [
    "ACOES_DADO",
    "ACOES_VIA_AI",
    "CAMPOS_CONTEUDO",
    "CATEGORIAS_PII",
    "DETECCAO_DA_CATEGORIA",
    "ESTADOS",
    "NATUREZAS",
    "NATUREZA_CONTEXTO",
    "NATUREZA_FORMA",
    "PERFIL_DO_ROSTER",
    "PERFIS_MODELO",
    "DadoBloqueadoParaLlm",
    "DecisaoAutomatizadaNegada",
    "Deteccao",
    "LimiteDeteccao",
    "ModeloNaoPermitido",
    "PoliticaIa",
    "PoliticaIaInvalida",
    "Saneamento",
    "aplicar_retencao",
    "categorias_detectadas",
    "deve_reter_prompt",
    "deve_reter_resposta",
    "dias_retencao",
    "exigir_perfil_autorizado",
    "exigir_revisao_humana",
    "expira_em",
    "modo_de_decisao",
    "perfil_autorizado",
    "perfis_permitidos",
    "pode_aplicar_sozinho",
    "politica_ia_seed",
    "sanear_para_llm",
    "validar_conteudo",
]
