"""
ELOS — Notificação da equipe de referência após degradação ALTA ou CRITICA.

O canal de entrega (push, e-mail, painel) é injetado como dependência
"notificador", com o método async `enviar_alerta_degradacao(**payload)`.
"""
from __future__ import annotations

import structlog

from app.tasks._runtime import dependencia, executar_async, tarefa

log = structlog.get_logger(__name__)


@tarefa("elos.notificacao.equipe")
def task_notificar_equipe(
    pessoa_saiu_id: str,
    severidade: str,
    indice_degradacao: float,
    nos_afetados: list[str],
):
    # Só IDs pseudonimizados trafegam aqui; nenhum dado pessoal vai para o broker (LGPD).
    notificador = dependencia("notificador")
    executar_async(
        notificador.enviar_alerta_degradacao(
            pessoa_saiu_id=pessoa_saiu_id,
            severidade=severidade,
            indice_degradacao=indice_degradacao,
            nos_afetados=nos_afetados,
        )
    )
    log.info("ppr.notificacao.enviada", severidade=severidade, afetados=len(nos_afetados))
