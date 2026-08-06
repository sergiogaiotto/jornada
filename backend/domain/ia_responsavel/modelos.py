"""Entidade `politica_ia` — política de IA Responsável versionada (sem I/O).

Mesma doutrina do `policy_versao` do M12 (§4.1): conteúdo em JSON, versão sequencial
por tenant, ciclo draft→publicada, e a publicada ATUAL é a que governa. Duas diferenças
deliberadas em relação ao M12, ambas cobradas pelo achado 8 do UAT #5:

1. **Autoria explícita.** `policy_versao` não guarda quem publicou; a rastreabilidade
   depende do evento no outbox. Para um artefato de IA Responsável isso é pouco: a
   pergunta "quem autorizou a IA a decidir sozinha, e quando?" precisa ser respondida
   pela própria linha, não por correlação de logs. Daí `autor_id`/`autor_nome`
   gravados na CRIAÇÃO e `publicado_por_id`/`publicado_por_nome` na PUBLICAÇÃO —
   separados de propósito, porque criar draft e publicar são atos diferentes e a
   segregação de funções (§10.5) exige poder distingui-los.
2. **Sem congelamento por OS.** A política do M12 é congelada em `os.frozen` no GO
   (§8-M4-A2) porque governa o CONTEÚDO da campanha em voo. Esta governa o TRATAMENTO
   DE DADOS PESSOAIS, e um titular não tem menos direito porque a OS é antiga: aperto
   de privacidade vale para todo mundo imediatamente. Congelar seria criar OSs em voo
   legalmente defasadas — o oposto do que o módulo existe para fazer.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

ESTADOS: tuple[str, ...] = ("draft", "publicada")


@dataclass
class PoliticaIa:
    """Linha de `politica_ia` — versão da política de IA Responsável de um tenant.

    `conteudo` = conjunto FECHADO validado em `politica.validar_conteudo`
    ({dados_llm, retencao, decisao_automatizada, modelos_permitidos}).
    """

    id: uuid.UUID
    tenant_id: str
    versao: int
    conteudo: dict[str, Any] = field(default_factory=dict)
    estado: str = "draft"  # ESTADOS
    autor_id: uuid.UUID | None = None
    autor_nome: str | None = None
    criada_em: datetime | None = None
    publicada_em: datetime | None = None
    publicado_por_id: uuid.UUID | None = None
    publicado_por_nome: str | None = None
    # Motivo declarado da mudança. Obrigatório na criação do draft pela API: uma
    # política de privacidade que muda sem justificativa escrita é exatamente o que
    # uma auditoria pede para ver e não encontra.
    motivo: str | None = None

    @property
    def publicada(self) -> bool:
        return self.estado == "publicada"
