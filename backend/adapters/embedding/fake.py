"""Adapter FAKE do EmbeddingPort — ÚNICO adapter de embeddings permitido em teste
(§1.3.5). Também cobre o fallback dev sem hub; nenhuma rede.

DETERMINÍSTICO entre processos/plataformas: bag-of-words com hashing estável
(blake2s do token → bucket do vetor) + normalização L2. Textos que compartilham
tokens ficam próximos em cosseno — suficiente para os testes de retrieve exercitarem
ranking de verdade (a consulta "consumo_pct" aproxima o chunk que cita a coluna).
"""

import hashlib
import math
import re

from application.ports.embedding import EmbeddingIndisponivel

_TOKEN = re.compile(r"[a-z0-9_]+")


def vetor_deterministico(texto: str, dim: int) -> list[float]:
    """Bag-of-words → vetor L2-normalizado; hashing estável (nunca `hash()` builtin,
    que é aleatório por processo). Peso = comprimento do token (IDF grosseiro:
    `consumo_pct` discrimina, stopwords curtas "e/de/com" quase não pesam)."""
    vetor = [0.0] * dim
    for token in _TOKEN.findall(texto.lower()):
        bucket = int.from_bytes(hashlib.blake2s(token.encode("utf-8")).digest()[:8], "big") % dim
        vetor[bucket] += float(len(token))
    norma = math.sqrt(sum(v * v for v in vetor))
    return [v / norma for v in vetor] if norma else vetor


class EmbeddingFake:
    """Implementa EmbeddingPort; determinístico, com ledger de chamadas (como LLMFake).

    `dim` default 1024 = EMBED_DIM do DDL §4.1 (drop-in no Postgres real dos testes
    de integração); unit tests podem reduzir para inspecionar vetores pequenos.
    """

    def __init__(self, *, dim: int = 1024, disponivel: bool = True) -> None:
        self._dim = dim
        self._disponivel = disponivel
        self.chamadas: list[list[str]] = []

    def disponivel(self) -> bool:
        return self._disponivel

    def embed(self, textos: list[str]) -> list[list[float]]:
        if not self._disponivel:
            raise EmbeddingIndisponivel("EmbeddingFake configurado como indisponível (§10.6).")
        self.chamadas.append(list(textos))
        return [vetor_deterministico(texto, self._dim) for texto in textos]
