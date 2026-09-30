"""
ELOS — Tarefas do PPR: encadeiam Script 18 → 19 → 20 fora da requisição HTTP.
"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from app.tasks._runtime import dependencia, executar_async, tarefa


@tarefa("elos.ppr.script19")
def task_ppr_script19(
    pessoa_saiu_id: str,
    relacoes_encerradas_ids: list[str],
    motivo_saida: str,
    ator_id: str,
    ator_papel: Optional[str] = None,
    ip_origem: Optional[str] = None,
):
    from app.scripts.ppr_script19 import Script19_PropagacaoTopologica

    script = Script19_PropagacaoTopologica(dependencia("neo4j"), dependencia("audit"))
    resultado = executar_async(
        script.executar(
            pessoa_saiu_id=UUID(pessoa_saiu_id),
            relacoes_encerradas_ids=relacoes_encerradas_ids,
            motivo_saida=motivo_saida,
            ator_id=UUID(ator_id),
            ator_papel=ator_papel,
            ip_origem=ip_origem,
        )
    )
    return {"degradacoes_criadas": resultado.degradacoes_criadas, "nos_afetados": resultado.nos_afetados}


@tarefa("elos.ppr.script20")
def task_ppr_script20(
    pessoa_saiu_id: str,
    degradacao_ids: list[str],
    ator_id: str,
    ator_papel: Optional[str] = None,
    ip_origem: Optional[str] = None,
):
    from app.scripts.ppr_script20 import Script20_AvaliacaoDegradacaoEstrutural

    script = Script20_AvaliacaoDegradacaoEstrutural(dependencia("neo4j"), dependencia("audit"))
    resultado = executar_async(
        script.executar(
            pessoa_saiu_id=UUID(pessoa_saiu_id),
            degradacao_ids=degradacao_ids,
            ator_id=UUID(ator_id),
            ator_papel=ator_papel,
            ip_origem=ip_origem,
        )
    )
    return {"severidade": resultado.severidade.value, "indice_degradacao": resultado.indice_degradacao}
