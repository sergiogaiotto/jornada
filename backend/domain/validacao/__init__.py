"""Contexto de domínio `validacao` — validação campo-a-campo & War Room (SDD §8-M4).

Puro: nenhuma importação de adapters, nenhum I/O; relógio sempre injetado (§2.1).
Checagens contra fonte (contagem/schema/frescor) são CÓDIGO determinístico — LLM
jamais participa do veredito (§1.1.3: compliance é código, nunca LLM).
"""
