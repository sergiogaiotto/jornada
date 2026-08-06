"""PublicacoesIaPort + RepositorioPoliticaIa — de onde a política de IA Responsável
VEM em runtime (§2.1, §10.2).

Porta irmã de `ports/publicacoes.py`. Existe separada por um motivo de escopo, não de
estilo: `PublicacoesPort` é o contrato do que o GO CONGELA em `os.frozen` (§8-M4-A2) —
skills, política do M12, tarifário. A política de IA Responsável **não é congelada por
OS**, por decisão registrada em `domain/ia_responsavel/modelos.py`: ela governa o
tratamento de dado pessoal, e um titular não tem menos direito porque a OS é antiga.
Enfiá-la no mesmo Protocol convidaria o próximo a congelá-la junto com o resto.

## O que esta porta impede (achado 8 do UAT #5)

A onda 3 entregou quatro parâmetros com enforcement provado por inversão e **ninguém
importando o módulo**: quatro funções puras que nada chamava. Esta porta é o começo do
conserto — é por ela, e só por ela, que a política publicada chega ao runtime. A regra
que o CI vigia (`test_nenhum_servico_importa_a_seed_direto`) é a outra metade: serviço
que importa `politica_ia_seed` lê constante compilada, e a tela do DPO volta a publicar
no vazio.

## ORIGEM é obrigatória, e aqui ela é MAIS crítica que no M12

`politica_ia_publicada` devolve sempre `origem`. Diferente do M12, a política de IA
Responsável **não é semeada em banco** (ver `adapters/publicacoes.py`): tenant novo não
tem linha nenhuma, e o default conservador vem do domínio. Sem `origem` a resposta
`{"versao": 1, ...}` seria indistinguível de "o DPO deste tenant publicou a v1" — e a
diferença é exatamente a pergunta que uma auditoria faz: *alguém decidiu isto, ou é o
que veio de fábrica?* `ORIGEM_SEED` responde "de fábrica, ninguém assinou"; a tela
mostra isso em letras grandes e o serviço não precisa adivinhar.
"""

import uuid
from typing import Any, Protocol

from application.ports.publicacoes import ORIGEM_PUBLICADA, ORIGEM_SEED
from domain.campanha.modelos import EventoDominio
from domain.ia_responsavel.modelos import PoliticaIa

__all__ = [
    "ORIGEM_PUBLICADA",
    "ORIGEM_SEED",
    "PublicacoesIaPort",
    "RepositorioPoliticaIa",
    "politica_ia_vigente",
]


class RepositorioPoliticaIa(Protocol):
    """Persistência de `politica_ia` (§4.1 — migração 0016) + outbox.

    `adicionar_evento` entra no MESMO Protocol de propósito: publicar política de IA é
    ato auditável (§2.3), e separar as duas portas permitiria montar o serviço com
    persistência e sem trilha — gravar a política sem registrar quem a publicou é o
    modo de falhar que este módulo inteiro existe para impedir.
    """

    def adicionar_politica_ia(self, politica: PoliticaIa) -> None: ...

    def obter_politica_ia(self, tenant_id: str, politica_id: uuid.UUID) -> PoliticaIa | None: ...

    def listar_politicas_ia(self, tenant_id: str) -> list[PoliticaIa]:
        """Todas as versões do tenant, ordem crescente de `versao` (histórico da tela)."""
        ...

    def politica_ia_publicada_atual(self, tenant_id: str | None = None) -> PoliticaIa | None:
        """Maior `versao` PUBLICADA do tenant; `None` = tenant nunca publicou.

        `None` NÃO é erro nem vazio: é o caso normal do primeiro boot, e quem traduz
        isso em "vale o default conservador, origem=seed" é o adapter — nunca o
        serviço, que não pode conhecer a semente (achado 8).
        """
        ...

    def adicionar_evento(self, evento: EventoDominio) -> None: ...


class PublicacoesIaPort(Protocol):
    def politica_ia_publicada(self, tenant_id: str | None = None) -> dict[str, Any]:
        """`{versao, estado, conteudo, origem, ...}` da política de IA que GOVERNA agora.

        Nunca devolve `None` e nunca levanta: sem linha publicada existe governo mesmo
        assim, e ele é o default conservador do domínio com `origem=ORIGEM_SEED`. Um
        `None` aqui obrigaria cada chamador a inventar o que fazer sem política — e
        "sem política" na prática viraria "sem restrição", que é o pior default
        possível para um controle de privacidade.
        """
        ...

    def politica_ia_default(self) -> dict[str, Any]:
        """O default conservador, SEMPRE — mesmo quando o tenant já publicou.

        Existe para a tela poder mostrar ao DPO, lado a lado, "o que está valendo" e "o
        que vem de fábrica", e para o formulário de publicação nascer preenchido com o
        conservador em vez de vazio. Sem este método o serviço precisaria importar a
        semente do domínio para renderizar o formulário — e seria o achado 8 entrando
        pela porta dos fundos, com a desculpa de que "é só para a UI".
        """
        ...


def politica_ia_vigente(
    publicacoes: PublicacoesIaPort, tenant_id: str | None = None
) -> dict[str, Any]:
    """`conteudo` da política de IA vigente — o que os serviços passam ao domínio.

    Espelha `politica_vigente` do M12: UM lugar traduz "publicação" em "conteúdo que
    governa", para que nenhum serviço volte a ter fonte própria de política.
    """
    return dict(publicacoes.politica_ia_publicada(tenant_id).get("conteudo") or {})
