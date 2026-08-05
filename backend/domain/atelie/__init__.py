"""Contexto Ateliê (M12 · T16, SDD §8-M12) — mesh de agentes como PRODUTO da plataforma.

Entidades espelham o DDL §4.1 (`agente`, `skill_versao`, `harness_case`, `harness_run`
— todas na migração 0001_core; nenhuma migração nova nesta fatia): parser do SKILL.md
canônico (§7.1) com validação de campos, ciclo de vida draft→em_revisao→publicada e
harness como PORTÃO de publicação (score ≥ 90 por dimensão do judge — §7.1).
Sem I/O (§2.1): LLM/judge ficam em agents/harness; persistência atrás de porta.
"""
