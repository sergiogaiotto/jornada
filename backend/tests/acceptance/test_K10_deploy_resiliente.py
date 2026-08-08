"""Aceite K10 · O deploy não reprova por oscilação de rede — e continua reprovando por defeito.

Em 2026-08-08, o deploy do `6833b01` falhou com
`ssh: connect to host vps.falagaiotto.com.br port 22: Connection timed out` **depois** dos
três gates verdes, com a VPS viva (HTTP 200 no `:8050`) e a porta 22 respondendo de fora
do runner. O passo fazia UMA tentativa e saía 255.

O risco não é o rerun manual — é o que vem depois dele. A nota que o próprio `deploy.sh`
carrega ao lado do `esperar_api` diz em voz alta: *controle que reprova por corrida acaba
comentado*. Na terceira vez que um deploy verde reprova por rede, alguém afrouxa a
checagem, e aí o guarda-corpo que existe para pegar deploy-fantasma vira decoração.

**A distinção que torna o retry seguro, e que este arquivo prende:** `ssh` devolve **255**
quando o SSH falha (conexão/auth) e o **código do comando remoto** quando ele chega a
rodar. Só o 255 é retentado. Um `docker compose up` que falha sai com o código dele e
reprova de primeira — retry cego aí mascararia deploy quebrado como instabilidade, que é
exatamente o oposto do que se quer.

**Este teste EXECUTA o laço, não faz grep nele.** O bloco é extraído do `ci.yml` e rodado
com um `ssh` falso e um `sleep` falso, um cenário por caso. Um guarda-corpo por string
("tem a palavra retry no arquivo") passaria com o laço logicamente quebrado — e o laço
ESTEVE quebrado na primeira versão: usava `if deploy_remoto; then ... fi; CODIGO=$?`, e
com `set -e` o `$?` depois de um `if` cujo `then` não executou vale 0 (POSIX), então
nenhuma falha seria reconhecida como 255 e o retry nunca aconteceria. Só executando se vê.
"""

import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[3]
CI_YML = RAIZ / ".github" / "workflows" / "ci.yml"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None, reason="precisa de bash (o gate roda no container)"
)


def _laco_de_retry() -> str:
    """Extrai do `ci.yml` o laço de tentativas, desindentado para rodar em bash."""
    texto = CI_YML.read_text(encoding="utf-8")
    bloco = re.search(r'ESPERAS="[^"]*".*?^ +done', texto, re.S | re.M)
    assert bloco, "o laço de retry sumiu do passo de deploy do ci.yml"
    return textwrap.dedent(bloco.group(0))


def _rodar(codigos: list[int]) -> subprocess.CompletedProcess[str]:
    """Roda o laço real com um `ssh` que devolve `codigos` em sequência."""
    roteiro = "\n".join(
        [
            "set -e",
            f"CODIGOS=({' '.join(str(c) for c in codigos)}); I=0",
            # o último código se repete: cobre "a rede nunca voltou"
            "deploy_remoto() { C=${CODIGOS[$I]:-${CODIGOS[-1]}}; I=$((I+1)); return $C; }",
            'sleep() { echo "DORMIU $1"; }',  # o teste não pode esperar 40s de verdade
            _laco_de_retry(),
        ]
    )
    return subprocess.run(["bash", "-c", roteiro], capture_output=True, text=True)


def test_K10_falha_de_conexao_e_retentada_e_o_deploy_conclui() -> None:
    """Uma queda de rede não pode custar um deploy que já passou nos três gates."""
    resultado = _rodar([255, 0])
    assert resultado.returncode == 0, resultado.stdout + resultado.stderr
    assert "tentativa 2" in resultado.stdout, resultado.stdout
    assert "DORMIU 10" in resultado.stdout, "o retry precisa de backoff, não pode ser imediato"


def test_K10_falha_do_comando_remoto_NAO_e_retentada() -> None:
    """O coração do desenho: retry cego mascararia deploy quebrado.

    Um `docker compose up --build` que falha (imagem quebrada, disco cheio, migração
    reprovada) devolve o código DELE, não 255. Retentar isso três vezes transformaria um
    defeito reprodutível num relatório de "instabilidade" — e o deploy seguinte seria
    tentado com o mesmo defeito.
    """
    for codigo in (1, 2, 17, 125):
        resultado = _rodar([codigo, 0, 0])  # o 0 seguinte SÓ passaria se houvesse retry
        assert resultado.returncode == codigo, (
            f"exit {codigo} do comando remoto virou {resultado.returncode} — "
            f"o laço retentou o que não devia: {resultado.stdout}"
        )
        assert "falha de DEPLOY" in resultado.stdout, resultado.stdout
        assert "DORMIU" not in resultado.stdout, "não pode haver espera antes de reprovar"


def test_K10_rede_que_nunca_volta_reprova_o_deploy() -> None:
    """Resiliência não é complacência: esgotadas as tentativas, o job REPROVA.

    E a mensagem tem de dizer que nada foi alterado no servidor — é a diferença entre
    "o deploy não aconteceu" e "o deploy aconteceu pela metade", que muda o que o
    operador faz em seguida.
    """
    resultado = _rodar([255])
    assert resultado.returncode == 1, resultado.stdout
    assert "falha de CONEXÃO" in resultado.stdout
    assert "nada foi alterado no servidor" in resultado.stdout
    assert resultado.stdout.count("DORMIU") == 2, (
        f"esperava 3 tentativas (2 esperas), veio: {resultado.stdout}"
    )


def test_K10_o_caminho_feliz_nao_espera_nada() -> None:
    """Deploy normal não pode ficar mais lento por causa do retry."""
    resultado = _rodar([0])
    assert resultado.returncode == 0
    assert "tentativa 1" in resultado.stdout
    assert "DORMIU" not in resultado.stdout


def test_K10_a_conexao_tem_timeout_explicito() -> None:
    """Sem `ConnectTimeout`, cada tentativa herda o timeout de TCP do sistema.

    O incidente de 2026-08-08 levou 2min14s para UMA tentativa. Com três tentativas e o
    default, o passo gastaria ~7 min só para descobrir que a rede está fora — e o retry
    viraria, ele próprio, um motivo para alguém removê-lo.
    """
    passo = CI_YML.read_text(encoding="utf-8")
    assert "-o ConnectTimeout=" in passo, "cada tentativa herdaria o timeout de TCP do SO"
    assert "-o BatchMode=yes" in passo, "sem BatchMode, um prompt interativo pendura o job"
