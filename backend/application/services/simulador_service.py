"""Casos de uso do M8 (parte 1) · Simulador / Ensaio Geral (SDD §6, §8-M8) —
orquestram o motor puro via ports (RngPort/ClockPort injetáveis → reprodutível por
seed, M8-A1). ZERO LLM neste caminho: simulação é portão obrigatório (§1.1.2) e o
caminho crítico nunca depende de LLM (§10.6) — o agente `simulate` só NARRA (§7.2).

Entrada (§6): JGC + segmento (waterfall/volume líquido) + priors + tarifas + política.
Saída persistida em `jornada_versao.simulacao` (coluna da migração 0005 — emenda §4.1);
`congelar-previsto` copia para `jornada_versao.previsto` (a régua que o snapshot M8
parte 2 congela como `snapshot.previsto` §4.1). Semáforo §6 (com precedência do aceite
A2): vermelho bloqueia T9/T11 → evento `gate.blocked`.
"""

import uuid
from typing import Any

from application.ports.clock import ClockPort
from application.ports.repositorio_jornada import RepositorioJornada
from application.ports.repositorio_os import RepositorioOs
from application.ports.rng import RngPort
from application.services.persona_service import ServicoPersona
from domain.audiencia.modelos import Segmento
from domain.campanha.erros import EstadoInvalido, NaoEncontrado
from domain.campanha.modelos import OS, EventoDominio
from domain.custo.tarifas import TARIFAS_VIGENTES
from domain.experimento.modelos import Experimento, experimento_travado
from domain.governanca.politicas import POLITICA_PUBLICADA
from domain.intake.completude import valor_do_campo
from domain.jornada.erros import GrafoInvalido
from domain.jornada.modelos import ESTADOS_EDITAVEIS, JornadaVersao
from domain.jornada.validacao import validar_grafo
from domain.simulacao import motor
from domain.simulacao.erros import SegmentoAusente, SimulacaoAusente
from domain.simulacao.priors import PRIORS_DEFAULT

RUNS_DEFAULT = 500  # §6: K=500 runs Monte Carlo
N_PERSONAS_DEFAULT = 10_000  # §6: N=10.000 personas
SEED_DEFAULT = 42


class ServicoSimulador:
    def __init__(
        self,
        repositorio: RepositorioJornada,
        repositorio_os: RepositorioOs,
        relogio: ClockPort,
        rng: RngPort,
        personas: ServicoPersona,
    ) -> None:
        self._repo = repositorio
        self._repo_os = repositorio_os
        self._relogio = relogio
        self._rng = rng
        self._personas = personas

    # ------------------------------------------------- POST /jornadas/{id}/simular
    def simular(
        self,
        tenant_id: str,
        jornada_id: uuid.UUID,
        *,
        seed: int = SEED_DEFAULT,
        runs: int = RUNS_DEFAULT,
        n_personas: int = N_PERSONAS_DEFAULT,
        actor: str,
    ) -> JornadaVersao:
        """Ensaio Geral (§6): valida o grafo, monta as entradas e roda o motor puro.

        Persiste a saída em `jornada_versao.simulacao` e estado → `simulado`;
        semáforo vermelho emite `gate.blocked` (bloqueia T9/T11 — §6).
        """
        jornada, os_ = self._jornada_da_os(tenant_id, jornada_id)
        if jornada.estado not in ESTADOS_EDITAVEIS:
            raise EstadoInvalido(
                f"Jornada em estado {jornada.estado!r} não se re-simula — novo ciclo exige "
                "nova versão (§1.2 non-goals: sem edição ao vivo)."
            )
        experimento = self._repo.experimento_da_os(os_.id)
        resultado = self._rodar(
            os_, jornada.grafo, experimento, seed=seed, runs=runs, n_personas=n_personas
        )
        jornada.simulacao = resultado
        jornada.estado = "simulado"
        self._repo.salvar_jornada(jornada)
        self._evento(
            os_,
            "simulacao.executada",
            {
                "jornada_id": str(jornada.id),
                "versao": jornada.versao,
                "seed": seed,
                "semaforo": resultado["semaforo"],
            },
            actor,
        )
        if resultado["semaforo"] == "vermelho":  # §6: vermelho bloqueia T9/T11
            self._evento(
                os_,
                "gate.blocked",
                {
                    "portao": "simulacao",
                    "jornada_id": str(jornada.id),
                    "motivos": resultado["motivos_semaforo"],
                },
                actor,
            )
        return jornada

    # ------------------------------------- POST /jornadas/{id}/congelar-previsto
    def congelar_previsto(
        self, tenant_id: str, jornada_id: uuid.UUID, *, actor: str
    ) -> JornadaVersao:
        """Congela a simulação corrente como Previsto da versão (§1.1.2: régua do
        pós-disparo); o snapshot (M8 parte 2) herda este bloco como `previsto` §4.1."""
        jornada, os_ = self._jornada_da_os(tenant_id, jornada_id)
        if not jornada.simulacao:
            raise SimulacaoAusente(
                "Não há simulação persistida nesta versão — rode POST /jornadas/{id}/simular "
                "antes de congelar o previsto (§6)."
            )
        jornada.previsto = {
            **jornada.simulacao,
            "congelado_em": self._relogio.agora().isoformat(),
            "congelado_por": actor,
        }
        self._repo.salvar_jornada(jornada)
        self._evento(
            os_,
            "previsto.congelado",
            {"jornada_id": str(jornada.id), "versao": jornada.versao},
            actor,
        )
        return jornada

    # -------------------------------------- pré-simulação do M11 (impacto de proposta)
    def ensaiar_grafo(
        self,
        tenant_id: str,
        os_id: uuid.UUID,
        grafo: dict[str, Any],
        *,
        seed: int = SEED_DEFAULT,
        runs: int = RUNS_DEFAULT,
        n_personas: int = N_PERSONAS_DEFAULT,
    ) -> dict[str, Any]:
        """Ensaio SEM persistência (§8-M11: "impacto pré-simulado via SimuladorService"
        das propostas do optimize) — MESMO pipeline determinístico do Ensaio Geral
        (§6, valida §5.3, portas Rng/Clock); nada é gravado no twin nem no outbox."""
        os_ = self._repo_os.obter_os(tenant_id, os_id)
        if os_ is None:
            raise NaoEncontrado(f"OS {os_id} não encontrada no tenant {tenant_id!r}.")
        experimento = self._repo.experimento_da_os(os_.id)
        return self._rodar(os_, grafo, experimento, seed=seed, runs=runs, n_personas=n_personas)

    # ------------------------------------------------- POST /simulacoes/comparar
    def comparar(self, tenant_id: str, jornada_ids: list[uuid.UUID]) -> dict[str, Any]:
        """Cenários lado a lado (§8-M8): P50s por versão + deltas vs o primeiro
        (baseline). Toda jornada precisa de simulação persistida (409 senão)."""
        cenarios: list[dict[str, Any]] = []
        for jornada_id in jornada_ids:
            jornada, _ = self._jornada_da_os(tenant_id, jornada_id)
            if not jornada.simulacao:
                raise SimulacaoAusente(
                    f"Jornada {jornada_id} (v{jornada.versao}) sem simulação persistida — "
                    "simule antes de comparar cenários."
                )
            cenarios.append(
                {
                    "jornada_id": str(jornada.id),
                    "os_id": str(jornada.os_id),
                    "versao": jornada.versao,
                    "semaforo": jornada.simulacao["semaforo"],
                    "p50": self._p50s(jornada.simulacao),
                    "parametros": jornada.simulacao.get("parametros", {}),
                }
            )
        baseline = cenarios[0]["p50"]
        for cenario in cenarios:
            cenario["delta_vs_baseline"] = {
                metrica: round(valor - baseline[metrica], 4)
                if isinstance(valor, int | float) and isinstance(baseline.get(metrica), int | float)
                else None
                for metrica, valor in cenario["p50"].items()
            }
        return {"baseline": cenarios[0]["jornada_id"], "cenarios": cenarios}

    # ----------------------------------------------------------------- privados
    def _rodar(
        self,
        os_: OS,
        grafo: dict[str, Any],
        experimento: Experimento | None,
        *,
        seed: int,
        runs: int,
        n_personas: int,
    ) -> dict[str, Any]:
        """Pipeline puro do Ensaio (§6): valida §5.3, monta entradas e roda o motor —
        compartilhado por `simular` (persiste) e `ensaiar_grafo` (M11, não persiste)."""
        politica = POLITICA_PUBLICADA["conteudo"]
        erros = validar_grafo(
            grafo,
            experimento_travado=experimento_travado(experimento),
            politica=politica,
        )
        if erros:
            raise GrafoInvalido(erros)
        segmento = self._segmento_recontado(os_.id)
        priors = self._priors_vigentes(os_)
        briefing = os_.briefing or {}
        ticket = _numero(valor_do_campo(briefing, "ticket_medio")) or float(priors["ticket_medio"])
        verba = _numero(valor_do_campo(briefing, "verba"))

        ger = self._rng.gerador(seed)
        personas = self._personas.gerar(
            n=n_personas,
            priors=priors,
            ger=ger,
            volume_abordagem=segmento.volume_abordagem,
        )
        resultado = motor.simular(
            grafo,
            volume_entrada=int(segmento.contagem_liquida or 0),
            personas=personas,
            priors=priors,
            tarifas=TARIFAS_VIGENTES,
            politica=politica,
            ger=ger,
            runs=runs,
            ticket_medio=ticket,
            hora_inicio=float(self._relogio.agora().hour),
            experimento=self._experimento_dict(experimento),
            verba=verba,
        )
        resultado["parametros"] = {
            "seed": seed,
            "runs": runs,
            "n_personas": n_personas,
            "segmento_id": str(segmento.id),
            "ticket_medio": ticket,
            "priors_versao": priors["versao"],
        }
        resultado["executada_em"] = self._relogio.agora().isoformat()
        return resultado

    def _priors_vigentes(self, os_: OS) -> dict[str, Any]:
        """§6: priors da `calibracao_prior` do tipo de campanha — última versão
        PUBLICADA pelo M11 (CalibrateService, backtest obrigatório); sem publicação
        vigente → `PRIORS_DEFAULT` v1 (priors.py), sem tocar o motor."""
        tipo = (os_.briefing or {}).get("tipo_campanha")
        if isinstance(tipo, dict):  # briefing M3: {valor, inferido, ...}
            tipo = tipo.get("valor")
        publicadas = [
            c
            for c in self._repo.listar_calibracoes(
                os_.tenant_id, tipo if isinstance(tipo, str) else None
            )
            if c.publicada_em is not None
        ]
        return publicadas[-1].priors if publicadas else PRIORS_DEFAULT

    @staticmethod
    def _p50s(simulacao: dict[str, Any]) -> dict[str, Any]:
        roas = simulacao.get("roas")
        return {
            "conversoes": simulacao["conversoes"]["p50"],
            "custo": simulacao["custo"]["p50"],
            "receita": simulacao["receita"]["p50"],
            "roas": roas["p50"] if roas else None,
            "lift_pp": simulacao["lift_pp"]["p50"],
        }

    @staticmethod
    def _experimento_dict(experimento: Experimento | None) -> dict[str, Any] | None:
        if experimento is None:
            return None
        return {
            "n_minimo": experimento.n_minimo,
            "mde_pp": experimento.mde_pp,
            "holdout_pct": experimento.holdout_pct,
            "janela_dias": experimento.janela_dias,
        }

    def _jornada_da_os(self, tenant_id: str, jornada_id: uuid.UUID) -> tuple[JornadaVersao, OS]:
        jornada = self._repo.obter_jornada(jornada_id)
        os_ = self._repo_os.obter_os(tenant_id, jornada.os_id) if jornada is not None else None
        if jornada is None or os_ is None:  # escopo de tenant via OS (§4.1)
            raise NaoEncontrado(f"Jornada {jornada_id} não encontrada no tenant {tenant_id!r}.")
        return jornada, os_

    def _segmento_recontado(self, os_id: uuid.UUID) -> Segmento:
        """Último segmento da OS com contagem líquida (§6: entrada inclui segmento)."""
        segmentos = [
            s for s in self._repo.listar_segmentos(os_id) if s.contagem_liquida is not None
        ]
        if not segmentos:
            raise SegmentoAusente(
                "OS sem segmento com contagem líquida — reconte a audiência (M5) antes do "
                "Ensaio Geral (§6: entrada = JGC + segmento + priors + tarifas + política)."
            )
        return segmentos[-1]

    def _evento(self, os_: OS, tipo: str, payload: dict[str, Any], actor: str) -> None:
        self._repo.adicionar_evento(
            EventoDominio(
                tenant_id=os_.tenant_id,
                os_id=os_.id,
                type=tipo,
                payload=payload,
                actor=actor,
                via_ai=False,  # simulador é código determinístico (§10.6) — zero LLM
                created_at=self._relogio.agora(),
            )
        )


def _numero(valor: Any) -> float | None:
    """Coerção tolerante de campo do briefing para número (auditoria MS8).

    O briefing §4.1 guarda `{valor, inferido}` e o valor pode vir humano
    ("R$ 500.000", "R$ 1.234,56") — o simulador precisa do float; não-numérico → None
    (verba ausente não bloqueia o Ensaio; ticket cai nos priors)."""
    if isinstance(valor, dict):
        valor = valor.get("valor")
    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = str(valor).strip().removeprefix("R$").strip()
    if "," in texto:  # pt-BR: "." é milhar, "," é decimal
        texto = texto.replace(".", "").replace(",", ".")
    elif texto.count(".") == 1 and len(texto.rsplit(".", 1)[1]) == 3:
        texto = texto.replace(".", "")  # "500.000" é milhar, não decimal
    elif texto.count(".") > 1:
        texto = texto.replace(".", "")
    try:
        return float(texto)
    except ValueError:
        return None
