"""PublicacoesPort — o que está PUBLICADO agora: skills (§7.1), política vigente
(§4.1 `policy_versao`) e tarifário do taxímetro (§8-M7-A2).

Porta = Protocol (§2.1). O GO grava em `os.frozen` (§4.1):
{agent_versions, policy_version, tarifario_id, slas}. O adapter (`adapters/publicacoes`)
lê o BANCO do Ateliê/plataforma e cai no seed §11.4 quando ainda não há linha publicada
— trocá-lo não toca serviço nem domínio.

**Esta porta é a ÚNICA fonte da política em runtime** (achado 8 do UAT #5). Antes, seis
serviços importavam `POLITICA_SEED` (então `POLITICA_PUBLICADA`) direto do domínio: a
tela de Políticas publicava versão no banco e não governava nada — holdout, alçadas e
frequency cap continuavam vindo da constante compilada. Por isso os métodos são
TENANT-AWARE: a política que governa uma OS é a do tenant DELA (§3), e
`politica_versionada` existe para o artefato assinado citar a MESMA versão que o GO
congelou (§8-M4-A2/§8-M12-A2), não a publicada de hoje.

**O número da versão sozinho é AMBÍGUO** — por isso `ORIGEM_SEED`/`ORIGEM_PUBLICADA`.
Tenant sem linha em `policy_versao` (só `default_tenant` é semeado, §11.4) tem a
política regida pelo SEED, e o GO congelaria `policy_version=1` vindo dele; quando esse
tenant publica a PRIMEIRA política pela T16, a versão nasce `max(existentes)+1 = 1` — o
MESMO número, conteúdo diferente. Sem registrar a ORIGEM, o pacote assinado buscaria a
v1 do banco e carimbaria um conteúdo que nunca governou aquela OS: o achado 8 de volta,
agora por colisão de numeração em vez de constante compilada.
"""

from decimal import Decimal
from typing import Any, Protocol

# Origem da política que governa/governou uma OS — vai para `os.frozen.policy_origem`.
ORIGEM_SEED = "seed"  # §11.4 compilado: o tenant não tem linha publicada
ORIGEM_PUBLICADA = "policy_versao"  # linha real de `policy_versao` (§4.1) do tenant


class PublicacoesPort(Protocol):
    def versoes_agentes(self) -> dict[str, str]:
        """{nome_do_agente: versão publicada atual} (skills §7.1)."""
        ...

    def politica_publicada(self, tenant_id: str | None = None) -> dict[str, Any]:
        """Política publicada ATUAL do tenant — {versao, conteudo, origem} (§4.1).

        `tenant_id=None` = dev single-tenant (§3); sem linha publicada, o adapter
        devolve o seed §11.4 (mesmos valores da seed `semear_politicas`) com
        `origem=ORIGEM_SEED` — é essa origem que o GO congela junto da versão, porque
        o número sozinho não distingue "v1 do seed" de "v1 que o tenant publicou".
        """
        ...

    def politica_versionada(
        self, versao: int, tenant_id: str | None = None, *, origem: str | None = None
    ) -> dict[str, Any] | None:
        """Política de uma versão ESPECÍFICA (a congelada no GO §8-M4-A2) ou None.

        Serve à consistência do artefato assinado: o snapshot (§8-M8) precisa assinar
        a versão que a OS congelou, não a que foi publicada depois — OS em voo segue
        na versão congelada (§8-M12-A2), e é o relatório de drift que denuncia o
        desencontro.

        `origem` é a que o GO gravou em `os.frozen.policy_origem`: com `ORIGEM_SEED` a
        busca NÃO pode cair no banco (a v1 de lá é outra política com o mesmo número).
        `None` = OS congelada antes deste campo existir — mantém o comportamento
        anterior (banco, depois seed), que é o único disponível para ela.
        """
        ...

    def tarifario_id(self) -> str:
        """Identificador do tarifário vigente (frozen.tarifario_id §4.1)."""
        ...

    def tarifas_vigentes(self) -> dict[str, Decimal]:
        """{canal: custo_unit} do tarifário vigente (`tarifa_canal` §4.1; seed §11.4)."""
        ...


def politica_vigente(publicacoes: PublicacoesPort, tenant_id: str | None = None) -> dict[str, Any]:
    """`conteudo` (§4.1) da política publicada do tenant — o que os serviços consultam.

    Helper de uma linha para que NENHUM serviço volte a ter uma fonte própria de
    política: um único lugar traduz `politica_publicada()` em conteúdo governante.
    """
    return dict(publicacoes.politica_publicada(tenant_id).get("conteudo") or {})
