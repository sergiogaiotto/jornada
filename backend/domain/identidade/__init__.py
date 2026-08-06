"""Contexto Identidade (emenda G01) — usuários locais com senha e sessões revogáveis.

Este pacote é PURO: modelos, política de senha e primitiva de hash, sem I/O e sem
FastAPI. Quem persiste é `RepositorioIdentidade` (§2.1); quem orquestra é
`application/services/identidade_service.py`; quem expõe é `api/v1/autenticacao.py`.
"""
