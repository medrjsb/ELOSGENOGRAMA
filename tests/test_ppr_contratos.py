"""
ELOS — Contratos entre os scripts PPR que test_ppr.py não cobre:
encadeamento 18 → 19 → 20, notificação e finalidade no audit (BUG-10).
"""
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.middleware.rbac import Finalidade


@pytest.mark.asyncio
async def test_script18_dispara_script19_com_relacoes_encerradas(audit_mock):
    from app.scripts.ppr_script18 import MotivoSaida, Script18_SaidaDaRede

    neo4j = AsyncMock()
    neo4j.run_single.return_value = {"id": "p1", "ativo": True}
    neo4j.run_many.return_value = [{"relacao_id": "r1", "alvo_id": "a1", "alvo_tipo": "PESSOA"}]

    with patch("app.tasks.ppr_tasks.task_ppr_script19") as task:
        await Script18_SaidaDaRede(neo4j, audit_mock).executar(
            pessoa_id=uuid4(), motivo=MotivoSaida.OBITO, ator_id=uuid4()
        )

    task.delay.assert_called_once()
    assert task.delay.call_args.kwargs["relacoes_encerradas_ids"] == ["r1"]
    assert task.delay.call_args.kwargs["motivo_saida"] == "OBITO"


@pytest.mark.asyncio
async def test_script18_audit_recebe_finalidade(audit_mock):
    from app.scripts.ppr_script18 import MotivoSaida, Script18_SaidaDaRede

    neo4j = AsyncMock()
    neo4j.run_single.return_value = {"id": "p1", "ativo": True}
    neo4j.run_many.return_value = []

    await Script18_SaidaDaRede(neo4j, audit_mock).executar(
        pessoa_id=uuid4(), motivo=MotivoSaida.SAIDA_VOLUNTARIA, ator_id=uuid4()
    )

    assert audit_mock.registrar.call_args.kwargs["finalidade"] == Finalidade.CUIDADO


def test_motivo_transferencia_e_alias_da_definitiva():
    from app.scripts.ppr_script18 import MotivoSaida

    assert MotivoSaida.TRANSFERENCIA is MotivoSaida.TRANSFERENCIA_DEFINITIVA


@pytest.mark.asyncio
async def test_script19_avalia_cada_no_uma_vez(audit_mock):
    from app.scripts.ppr_script19 import Script19_PropagacaoTopologica

    neo4j = AsyncMock()
    # Duas relações encerradas levam ao mesmo nó adjacente.
    neo4j.run_single.return_value = {"alvo_id": "a1", "alvo_tipo": "PESSOA", "relacoes_restantes": 0}
    neo4j.run_write.return_value = []

    with patch("app.tasks.ppr_tasks.task_ppr_script20"):
        resultado = await Script19_PropagacaoTopologica(neo4j, audit_mock).executar(
            pessoa_saiu_id=uuid4(),
            relacoes_encerradas_ids=["r1", "r2"],
            motivo_saida="OBITO",
            ator_id=uuid4(),
        )

    assert resultado.degradacoes_criadas == 1
    assert neo4j.run_write.call_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("restantes,total,notifica", [(0, 10, True), (1, 100, False)])
async def test_script20_notifica_so_alta_ou_critica(audit_mock, restantes, total, notifica):
    from app.scripts.ppr_script20 import Script20_AvaliacaoDegradacaoEstrutural

    neo4j = AsyncMock()
    neo4j.run_many.return_value = [
        {"degradacao_id": "d1", "no_id": "n1", "no_tipo": "PESSOA", "relacoes_restantes": restantes}
    ]
    neo4j.run_single.return_value = {"total_nos": total}

    with patch("app.tasks.notification_tasks.task_notificar_equipe") as task:
        task.delay = MagicMock()
        await Script20_AvaliacaoDegradacaoEstrutural(neo4j, audit_mock).executar(
            pessoa_saiu_id=uuid4(), degradacao_ids=["d1"], ator_id=uuid4()
        )

    assert task.delay.called is notifica


@pytest.mark.asyncio
async def test_script20_sem_degradacoes_pendentes(audit_mock):
    from app.scripts.ppr_script20 import Script20_AvaliacaoDegradacaoEstrutural, SeveridadeDegradacao

    neo4j = AsyncMock()
    neo4j.run_many.return_value = []

    resultado = await Script20_AvaliacaoDegradacaoEstrutural(neo4j, audit_mock).executar(
        pessoa_saiu_id=uuid4(), degradacao_ids=["d1"], ator_id=uuid4()
    )

    assert resultado.severidade == SeveridadeDegradacao.BAIXA
    neo4j.run_write.assert_not_called()


def test_tarefas_sem_dependencia_configurada_falham_claramente():
    from app.tasks._runtime import dependencia

    with pytest.raises(RuntimeError, match="não configurada"):
        dependencia("inexistente")
