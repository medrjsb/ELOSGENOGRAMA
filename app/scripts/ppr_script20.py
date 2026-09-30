"""
ELOS — PPR Script 20: Avaliação de Degradação Estrutural.

Consolida as Degradacoes criadas pelo Script 19, calcula o índice de
degradação (degradações / nós do subgrafo) e classifica a severidade:
  CRITICA  — algum nó ficou isolado (0 relações ATIVAS)
  ALTA     — índice > 0.50
  MEDIA    — índice >= 0.20
  BAIXA    — abaixo disso
ALTA e CRITICA notificam a equipe de referência.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

import structlog

from app.middleware.rbac import Operacao
from app.scripts.ppr_base import FINALIDADE_PPR, AuditLogger, Neo4jClient

log = structlog.get_logger(__name__)

LIMIAR_ALTA = 0.50    # estritamente maior (BUG-TEST-03)
LIMIAR_MEDIA = 0.20


class SeveridadeDegradacao(str, enum.Enum):
    BAIXA   = "BAIXA"
    MEDIA   = "MEDIA"
    ALTA    = "ALTA"
    CRITICA = "CRITICA"


SEVERIDADES_QUE_NOTIFICAM = {SeveridadeDegradacao.ALTA, SeveridadeDegradacao.CRITICA}

CYPHER_DEGRADACOES_PENDENTES = """
MATCH (d:Degradacao)-[:AFETA]->(no)
WHERE d.id IN $degradacao_ids AND d.status = 'PENDENTE'
OPTIONAL MATCH (no)-[ativa:RELACAO {status: 'ATIVA'}]-()
RETURN d.id AS degradacao_id, no.id AS no_id, head(labels(no)) AS no_tipo,
       count(ativa) AS relacoes_restantes
"""

CYPHER_TOTAL_NOS_SUBGRAFO = """
MATCH (saiu:Pessoa {id: $pessoa_saiu_id})-[:RELACAO]-(vizinho)
OPTIONAL MATCH (vizinho)-[:RELACAO]-(segundo)
WHERE segundo.id <> $pessoa_saiu_id
WITH collect(DISTINCT vizinho) + collect(DISTINCT segundo) AS nos
UNWIND nos AS n
RETURN count(DISTINCT n) AS total_nos
"""

CYPHER_RESOLVER_DEGRADACOES = """
MATCH (d:Degradacao)
WHERE d.id IN $degradacao_ids AND d.status = 'PENDENTE'
SET d.status = 'AVALIADA', d.severidade = $severidade,
    d.indice_degradacao = $indice, d.avaliada_em = datetime()
RETURN count(d) AS resolvidas
"""


@dataclass(frozen=True)
class ResultadoScript20:
    pessoa_saiu_id: UUID
    severidade: SeveridadeDegradacao
    indice_degradacao: float
    nos_isolados: int
    degradacoes_avaliadas: int
    total_nos: int


class Script20_AvaliacaoDegradacaoEstrutural:
    def __init__(self, neo4j: Neo4jClient, audit: AuditLogger):
        self.neo4j = neo4j
        self.audit = audit

    @staticmethod
    def _calcular_severidade(nos_isolados: int, indice: float) -> SeveridadeDegradacao:
        if nos_isolados > 0:
            return SeveridadeDegradacao.CRITICA
        if indice > LIMIAR_ALTA:
            return SeveridadeDegradacao.ALTA
        if indice >= LIMIAR_MEDIA:
            return SeveridadeDegradacao.MEDIA
        return SeveridadeDegradacao.BAIXA

    async def executar(
        self,
        pessoa_saiu_id: UUID,
        degradacao_ids: list[str],
        ator_id: UUID,
        ator_papel: Optional[str] = None,
        ip_origem: Optional[str] = None,
    ) -> ResultadoScript20:
        degradacoes = await self.neo4j.run_many(
            CYPHER_DEGRADACOES_PENDENTES, {"degradacao_ids": list(degradacao_ids)}
        )
        if not degradacoes:
            return ResultadoScript20(pessoa_saiu_id, SeveridadeDegradacao.BAIXA, 0.0, 0, 0, 0)

        total = await self.neo4j.run_single(
            CYPHER_TOTAL_NOS_SUBGRAFO, {"pessoa_saiu_id": str(pessoa_saiu_id)}
        )
        # O subgrafo nunca tem menos nós que as degradações encontradas nele.
        total_nos = max((total or {}).get("total_nos", 0), len(degradacoes))

        nos_isolados = sum(1 for d in degradacoes if d["relacoes_restantes"] == 0)
        indice = round(len(degradacoes) / total_nos, 4)
        severidade = self._calcular_severidade(nos_isolados, indice)

        await self.neo4j.run_write(
            CYPHER_RESOLVER_DEGRADACOES,
            {
                "degradacao_ids": [d["degradacao_id"] for d in degradacoes],
                "severidade": severidade.value,
                "indice": indice,
            },
        )

        await self.audit.registrar(
            ator_id=ator_id,
            ator_papel=ator_papel,
            operacao=Operacao.ESCRITA_EVENTO,
            finalidade=FINALIDADE_PPR,
            recurso_id=str(pessoa_saiu_id),
            ip_origem=ip_origem,
            detalhes={
                "script": 20,
                "severidade": severidade.value,
                "indice_degradacao": indice,
                "nos_isolados": nos_isolados,
                "total_nos": total_nos,
            },
        )

        if severidade in SEVERIDADES_QUE_NOTIFICAM:
            from app.tasks import notification_tasks

            notification_tasks.task_notificar_equipe.delay(
                pessoa_saiu_id=str(pessoa_saiu_id),
                severidade=severidade.value,
                indice_degradacao=indice,
                nos_afetados=[d["no_id"] for d in degradacoes],
            )

        log.info("ppr.script20.ok", pessoa_saiu_id=str(pessoa_saiu_id), severidade=severidade.value)
        return ResultadoScript20(
            pessoa_saiu_id, severidade, indice, nos_isolados, len(degradacoes), total_nos
        )
