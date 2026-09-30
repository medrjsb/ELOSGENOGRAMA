"""
ELOS — PPR Script 18: Saída da Rede.

Quando uma pessoa sai da rede (óbito, transferência, abandono, saída voluntária):
  1. confirma que a pessoa existe e está ativa (idempotente se já inativa);
  2. encerra apenas as relações ATIVAS (F-08: LATENTES/ENCERRADAS ficam como estão);
  3. registra o EventoPPR e o audit_log;
  4. dispara o Script 19 para as relações encerradas, se houver.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Optional
from uuid import UUID, uuid4

import structlog

from app.middleware.rbac import Operacao
from app.scripts.ppr_base import FINALIDADE_PPR, AuditLogger, Neo4jClient

log = structlog.get_logger(__name__)


class MotivoSaida(str, enum.Enum):
    OBITO                    = "OBITO"
    TRANSFERENCIA_DEFINITIVA = "TRANSFERENCIA_DEFINITIVA"
    ABANDONO_CONFIRMADO      = "ABANDONO_CONFIRMADO"
    SAIDA_VOLUNTARIA         = "SAIDA_VOLUNTARIA"
    # Alias usado pelos chamadores legados; resolve para TRANSFERENCIA_DEFINITIVA.
    TRANSFERENCIA            = "TRANSFERENCIA_DEFINITIVA"


CYPHER_PESSOA = """
MATCH (p:Pessoa {id: $pessoa_id})
RETURN p.id AS id, coalesce(p.ativo, true) AS ativo
"""

CYPHER_RELACOES_ATIVAS = """
MATCH (p:Pessoa {id: $pessoa_id})-[r:RELACAO {status: 'ATIVA'}]-(alvo)
RETURN r.id AS relacao_id, alvo.id AS alvo_id, head(labels(alvo)) AS alvo_tipo
"""

CYPHER_REGISTRAR_SAIDA = """
MATCH (p:Pessoa {id: $pessoa_id})
SET p.ativo = false, p.motivo_saida = $motivo, p.saiu_em = datetime()
WITH p
OPTIONAL MATCH (p)-[r:RELACAO]-()
WHERE r.id IN $relacoes_ids
SET r.status = 'ENCERRADA', r.encerrada_em = datetime(), r.motivo_encerramento = $motivo
WITH p, count(r) AS encerradas
CREATE (e:EventoPPR {id: $evento_id, script: 18, motivo: $motivo,
                     ator_id: $ator_id, relacoes_encerradas: encerradas, criado_em: datetime()})
CREATE (e)-[:REFERE_A]->(p)
RETURN e.id AS id
"""


@dataclass(frozen=True)
class ResultadoScript18:
    pessoa_id: UUID
    motivo: MotivoSaida
    relacoes_encerradas: int
    evento_ppr_id: Optional[UUID]
    ja_inativa: bool = False


class Script18_SaidaDaRede:
    def __init__(self, neo4j: Neo4jClient, audit: AuditLogger):
        self.neo4j = neo4j
        self.audit = audit

    async def executar(
        self,
        pessoa_id: UUID,
        motivo: MotivoSaida,
        ator_id: UUID,
        ator_papel: Optional[str] = None,
        ip_origem: Optional[str] = None,
    ) -> ResultadoScript18:
        motivo = MotivoSaida(motivo)
        pessoa = await self.neo4j.run_single(CYPHER_PESSOA, {"pessoa_id": str(pessoa_id)})
        if pessoa is None:
            raise ValueError(f"Pessoa {pessoa_id} não encontrada no grafo")

        if not pessoa.get("ativo", True):
            log.info("ppr.script18.ja_inativa", pessoa_id=str(pessoa_id))
            return ResultadoScript18(pessoa_id, motivo, 0, None, ja_inativa=True)

        relacoes = await self.neo4j.run_many(CYPHER_RELACOES_ATIVAS, {"pessoa_id": str(pessoa_id)})
        relacoes_ids = [r["relacao_id"] for r in relacoes]

        evento_id = uuid4()
        await self.neo4j.run_write(
            CYPHER_REGISTRAR_SAIDA,
            {
                "pessoa_id": str(pessoa_id),
                "motivo": motivo.value,
                "relacoes_ids": relacoes_ids,
                "evento_id": str(evento_id),
                "ator_id": str(ator_id),
            },
        )

        await self.audit.registrar(
            ator_id=ator_id,
            ator_papel=ator_papel,
            operacao=Operacao.ESCRITA_EVENTO,
            finalidade=FINALIDADE_PPR,
            recurso_id=str(pessoa_id),
            ip_origem=ip_origem,
            detalhes={
                "script": 18,
                "evento_ppr_id": str(evento_id),
                "motivo": motivo.value,
                "relacoes_encerradas": len(relacoes_ids),
            },
        )

        if relacoes_ids:
            # Import local: evita ciclo scripts ↔ tasks e permite patch no módulo fonte (BUG-06).
            from app.tasks import ppr_tasks

            ppr_tasks.task_ppr_script19.delay(
                pessoa_saiu_id=str(pessoa_id),
                relacoes_encerradas_ids=relacoes_ids,
                motivo_saida=motivo.value,
                ator_id=str(ator_id),
                ator_papel=ator_papel,
                ip_origem=ip_origem,
            )

        log.info("ppr.script18.ok", pessoa_id=str(pessoa_id), encerradas=len(relacoes_ids))
        return ResultadoScript18(pessoa_id, motivo, len(relacoes_ids), evento_id)
