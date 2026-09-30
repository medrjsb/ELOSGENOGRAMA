"""
ELOS — PPR Script 19: Propagação Topológica.

Para cada relação encerrada pelo Script 18, avalia o nó do outro lado.
Se ele ficou com LIMIAR_RELACOES_RESTANTES relações ATIVAS ou menos, suas
relações restantes passam a LATENTE e uma Degradacao é criada para ele.
A propagação para no primeiro grau (F-10): os vizinhos desse nó não são avaliados.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
from uuid import UUID, uuid4

import structlog

from app.middleware.rbac import Operacao
from app.scripts.ppr_base import FINALIDADE_PPR, AuditLogger, Neo4jClient

log = structlog.get_logger(__name__)

# Um nó com até 1 relação ATIVA restante é considerado em risco de isolamento.
LIMIAR_RELACOES_RESTANTES = 1

CYPHER_NOS_ADJACENTES = """
MATCH (saiu:Pessoa {id: $pessoa_saiu_id})-[r:RELACAO {id: $relacao_id}]-(alvo)
OPTIONAL MATCH (alvo)-[ativa:RELACAO {status: 'ATIVA'}]-()
RETURN alvo.id AS alvo_id, head(labels(alvo)) AS alvo_tipo, count(ativa) AS relacoes_restantes
"""

CYPHER_MARCAR_LATENTE = """
MATCH (alvo {id: $alvo_id})-[r:RELACAO {status: 'ATIVA'}]-()
SET r.status = 'LATENTE', r.latente_desde = datetime()
WITH alvo, collect(r.id) AS latentes
CREATE (d:Degradacao {id: $degradacao_id, status: 'PENDENTE', origem_pessoa_id: $pessoa_saiu_id,
                      motivo_saida: $motivo_saida, criada_em: datetime()})
CREATE (d)-[:AFETA]->(alvo)
WITH latentes
UNWIND latentes AS relacao_id
RETURN relacao_id, 'LATENTE' AS novo_status
"""


@dataclass
class ResultadoScript19:
    pessoa_saiu_id: UUID
    nos_afetados: int = 0
    degradacoes_criadas: int = 0
    relacoes_latentes: int = 0
    degradacao_ids: list[str] = field(default_factory=list)


class Script19_PropagacaoTopologica:
    def __init__(self, neo4j: Neo4jClient, audit: AuditLogger):
        self.neo4j = neo4j
        self.audit = audit

    async def executar(
        self,
        pessoa_saiu_id: UUID,
        relacoes_encerradas_ids: list[str],
        motivo_saida: str,
        ator_id: UUID,
        ator_papel: Optional[str] = None,
        ip_origem: Optional[str] = None,
    ) -> ResultadoScript19:
        resultado = ResultadoScript19(pessoa_saiu_id=pessoa_saiu_id)
        avaliados: set[str] = set()

        for relacao_id in relacoes_encerradas_ids:
            adj = await self.neo4j.run_single(
                CYPHER_NOS_ADJACENTES,
                {"pessoa_saiu_id": str(pessoa_saiu_id), "relacao_id": relacao_id},
            )
            if adj is None or adj["alvo_id"] in avaliados:
                continue
            avaliados.add(adj["alvo_id"])

            if adj["relacoes_restantes"] > LIMIAR_RELACOES_RESTANTES:
                continue

            degradacao_id = str(uuid4())
            latentes = await self.neo4j.run_write(
                CYPHER_MARCAR_LATENTE,
                {
                    "alvo_id": adj["alvo_id"],
                    "degradacao_id": degradacao_id,
                    "pessoa_saiu_id": str(pessoa_saiu_id),
                    "motivo_saida": motivo_saida,
                },
            )
            resultado.nos_afetados += 1
            resultado.degradacoes_criadas += 1
            resultado.relacoes_latentes += len(latentes)
            resultado.degradacao_ids.append(degradacao_id)

        if not resultado.degradacao_ids:
            return resultado

        await self.audit.registrar(
            ator_id=ator_id,
            ator_papel=ator_papel,
            operacao=Operacao.ESCRITA_RELACAO,
            finalidade=FINALIDADE_PPR,
            recurso_id=str(pessoa_saiu_id),
            ip_origem=ip_origem,
            detalhes={
                "script": 19,
                "motivo_saida": motivo_saida,
                "nos_afetados": resultado.nos_afetados,
                "relacoes_latentes": resultado.relacoes_latentes,
                "degradacao_ids": resultado.degradacao_ids,
            },
        )

        from app.tasks import ppr_tasks

        ppr_tasks.task_ppr_script20.delay(
            pessoa_saiu_id=str(pessoa_saiu_id),
            degradacao_ids=resultado.degradacao_ids,
            ator_id=str(ator_id),
            ator_papel=ator_papel,
            ip_origem=ip_origem,
        )

        log.info("ppr.script19.ok", pessoa_saiu_id=str(pessoa_saiu_id), afetados=resultado.nos_afetados)
        return resultado
