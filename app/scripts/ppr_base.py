"""
ELOS — Contratos compartilhados do Protocolo de Propagação Relacional (PPR).

Os scripts 18, 19 e 20 dependem só destas interfaces, o que permite testá-los
com mocks sem Neo4j nem PostgreSQL reais.
"""
from __future__ import annotations

from typing import Any, Optional, Protocol
from uuid import UUID

from app.middleware.rbac import Finalidade, Operacao


class Neo4jClient(Protocol):
    async def run_single(self, query: str, params: dict[str, Any]) -> Optional[dict[str, Any]]: ...
    async def run_many(self, query: str, params: dict[str, Any]) -> list[dict[str, Any]]: ...
    async def run_write(self, query: str, params: dict[str, Any]) -> list[dict[str, Any]]: ...


class AuditLogger(Protocol):
    async def registrar(
        self,
        *,
        ator_id: UUID,
        ator_papel: Optional[str],
        operacao: Operacao,
        finalidade: Finalidade,
        recurso_id: str,
        ip_origem: Optional[str],
        detalhes: dict[str, Any],
    ) -> None: ...


# Finalidade de todo o PPR: manutenção do grafo de cuidado do paciente.
# BUG-10 CORRIGIDO: registrar() sempre recebe finalidade explícita.
FINALIDADE_PPR = Finalidade.CUIDADO
