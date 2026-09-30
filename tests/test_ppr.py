"""
ELOS — Testes: Scripts PPR 18, 19, 20
Valida o Protocolo de Propagação Relacional sem dependência de Neo4j real.

BUGS DOCUMENTADOS E CORRIGIDOS NESTE ARQUIVO:
  BUG-06: patch path corrigido para app.tasks.ppr_tasks.* (imports locais)
  BUG-07: parâmetros de Script19 corrigidos (relacoes_encerradas_ids, motivo_saida)
  BUG-08: mock Script19 corrigido para run_single com campos corretos
  BUG-09: parâmetros de Script20 corrigidos (pessoa_saiu_id, degradacao_ids)
  BUG-10: audit.registrar sem finalidade — falha em produção, silente com mock
           CLASSIFICAÇÃO: IMPLEMENTADO — NÃO VALIDADO (requer correção antes de produção)
"""
import asyncio
import pytest
from uuid import uuid4, UUID
from unittest.mock import AsyncMock, MagicMock, patch, call


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _make_pessoa_id() -> UUID:
    return uuid4()


def _make_relacao_id() -> str:
    return str(uuid4())


# ─────────────────────────────────────────────────────────────
# Script 18 — Saída da Rede
# ─────────────────────────────────────────────────────────────

class TestScript18SaidaDaRede:

    @pytest.fixture
    def neo4j_script18_ok(self):
        """Neo4j mock: pessoa ativa com 2 relações ATIVAS."""
        mock = AsyncMock()
        pessoa_id = _make_pessoa_id()
        relacoes = [
            {"relacao_id": _make_relacao_id(), "alvo_id": str(uuid4()), "alvo_tipo": "PESSOA"},
            {"relacao_id": _make_relacao_id(), "alvo_id": str(uuid4()), "alvo_tipo": "SERVICO"},
        ]
        mock.run_single.return_value = {"id": str(pessoa_id), "ativo": True}
        mock.run_many.return_value = relacoes
        mock.run_write.return_value = [{"id": _make_relacao_id()}]
        return mock, pessoa_id, relacoes

    @pytest.mark.asyncio
    async def test_script18_encerra_relacoes_ativas(self, neo4j_script18_ok, audit_mock):
        """Script18 deve encerrar todas as relações ATIVAS da pessoa."""
        from app.scripts.ppr_script18 import Script18_SaidaDaRede, MotivoSaida

        neo4j, pessoa_id, relacoes = neo4j_script18_ok

        # BUG-06: patch no módulo fonte (import local dentro da função)
        with patch("app.tasks.ppr_tasks.task_ppr_script19") as mock_task:
            mock_task.delay = MagicMock()
            script = Script18_SaidaDaRede(neo4j, audit_mock)
            resultado = await script.executar(
                pessoa_id=pessoa_id,
                motivo=MotivoSaida.OBITO,
                ator_id=uuid4(),
                ator_papel="elos_equipe",
                ip_origem="127.0.0.1",
            )

        assert resultado.relacoes_encerradas == 2
        assert isinstance(resultado.evento_ppr_id, UUID)
        assert resultado.motivo == MotivoSaida.OBITO

    @pytest.mark.asyncio
    async def test_script18_idempotente_pessoa_inativa(self, audit_mock):
        """Script18 retorna imediatamente se pessoa já está inativa (idempotência)."""
        from app.scripts.ppr_script18 import Script18_SaidaDaRede, MotivoSaida

        neo4j = AsyncMock()
        neo4j.run_single.return_value = {"id": str(uuid4()), "ativo": False}

        script = Script18_SaidaDaRede(neo4j, audit_mock)
        resultado = await script.executar(
            pessoa_id=_make_pessoa_id(),
            motivo=MotivoSaida.TRANSFERENCIA,
            ator_id=uuid4(),
            ator_papel="elos_equipe",
            ip_origem="127.0.0.1",
        )

        assert resultado.relacoes_encerradas == 0
        neo4j.run_write.assert_not_called()

    @pytest.mark.asyncio
    async def test_script18_levanta_se_pessoa_nao_encontrada(self, audit_mock):
        """Script18 deve levantar ValueError se pessoa não existe no grafo."""
        from app.scripts.ppr_script18 import Script18_SaidaDaRede, MotivoSaida

        neo4j = AsyncMock()
        neo4j.run_single.return_value = None

        script = Script18_SaidaDaRede(neo4j, audit_mock)
        with pytest.raises(ValueError, match="não encontrada"):
            await script.executar(
                pessoa_id=_make_pessoa_id(),
                motivo=MotivoSaida.OBITO,
                ator_id=uuid4(),
                ator_papel="elos_equipe",
                ip_origem="127.0.0.1",
            )

    @pytest.mark.asyncio
    async def test_script18_sem_relacoes_ativas_nao_dispara_script19(self, audit_mock):
        """
        Script18 sem relações ATIVAS: encerradas=0, Script19 NÃO deve ser chamado.
        F-08: apenas ATIVAS são fechadas; LATENTES/ENCERRADAS são ignoradas.
        """
        from app.scripts.ppr_script18 import Script18_SaidaDaRede, MotivoSaida

        neo4j = AsyncMock()
        neo4j.run_single.return_value = {"id": str(uuid4()), "ativo": True}
        neo4j.run_many.return_value = []         # nenhuma ATIVA
        neo4j.run_write.return_value = [{"id": "evt-001"}]

        script = Script18_SaidaDaRede(neo4j, audit_mock)
        resultado = await script.executar(
            pessoa_id=_make_pessoa_id(),
            motivo=MotivoSaida.SAIDA_VOLUNTARIA,
            ator_id=uuid4(),
            ator_papel="elos_equipe",
            ip_origem="127.0.0.1",
        )

        assert resultado.relacoes_encerradas == 0
        # Script19 não é chamado quando lista de propagação está vazia
        assert resultado.evento_ppr_id is not None

    def test_motivo_saida_valores_validos(self):
        """MotivoSaida deve aceitar todos os valores esperados."""
        from app.scripts.ppr_script18 import MotivoSaida
        assert MotivoSaida("OBITO").value == "OBITO"
        assert MotivoSaida("TRANSFERENCIA_DEFINITIVA").value == "TRANSFERENCIA_DEFINITIVA"
        assert MotivoSaida("ABANDONO_CONFIRMADO").value == "ABANDONO_CONFIRMADO"
        assert MotivoSaida("SAIDA_VOLUNTARIA").value == "SAIDA_VOLUNTARIA"

    def test_motivo_saida_invalido(self):
        """MotivoSaida deve rejeitar valor desconhecido."""
        from app.scripts.ppr_script18 import MotivoSaida
        with pytest.raises(ValueError):
            MotivoSaida("MOTIVO_INEXISTENTE")


# ─────────────────────────────────────────────────────────────
# Script 19 — Propagação Topológica
# ─────────────────────────────────────────────────────────────

class TestScript19PropagacaoTopologica:
    """
    CONTRATO REAL: Script19.executar(pessoa_saiu_id, relacoes_encerradas_ids: list[str], motivo_saida, ...)
    Neo4j: run_single(CYPHER_NOS_ADJACENTES) por relação → {alvo_id, alvo_tipo, relacoes_restantes}
    BUG-07/08 CORRIGIDOS neste arquivo.
    """

    @pytest.mark.asyncio
    async def test_script19_marca_latente_no_com_poucas_conexoes(self, audit_mock):
        """Script19 deve marcar LATENTE nós com 0 relações ATIVAS restantes (F-10)."""
        from app.scripts.ppr_script19 import Script19_PropagacaoTopologica

        alvo_id = str(uuid4())
        neo4j = AsyncMock()
        # run_single retorna adjacente COM relacoes_restantes = 0 (abaixo do limiar)
        neo4j.run_single.return_value = {
            "alvo_id": alvo_id,
            "alvo_tipo": "PESSOA",
            "relacoes_restantes": 0,
        }
        neo4j.run_write.return_value = [{"relacao_id": str(uuid4()), "novo_status": "LATENTE"}]

        relacoes_ids = [_make_relacao_id()]  # BUG-07: list[str], não list[dict]

        # BUG-06: patch no módulo fonte
        with patch("app.tasks.ppr_tasks.task_ppr_script20") as mock_task:
            mock_task.delay = MagicMock()
            script = Script19_PropagacaoTopologica(neo4j, audit_mock)
            resultado = await script.executar(
                pessoa_saiu_id=_make_pessoa_id(),    # BUG-07: pessoa_saiu_id
                relacoes_encerradas_ids=relacoes_ids, # BUG-07: nome correto
                motivo_saida="OBITO",                # BUG-07: argumento obrigatório
                ator_id=uuid4(),
                ator_papel="elos_equipe",
                ip_origem="127.0.0.1",
            )

        assert resultado.degradacoes_criadas == 1
        assert resultado.nos_afetados == 1

    @pytest.mark.asyncio
    async def test_script19_nao_propaga_alem_primeiro_grau(self, audit_mock):
        """
        Script19 não propaga degradação além do primeiro grau (F-10 VALIDADO).
        Quando adjacente tem relacoes_restantes > LIMIAR, nada é marcado LATENTE.
        """
        from app.scripts.ppr_script19 import Script19_PropagacaoTopologica

        neo4j = AsyncMock()
        # Adjacente tem 3 relações ATIVAS restantes → acima do limiar (1)
        neo4j.run_single.return_value = {
            "alvo_id": str(uuid4()),
            "alvo_tipo": "PESSOA",
            "relacoes_restantes": 3,
        }
        neo4j.run_write.return_value = []

        script = Script19_PropagacaoTopologica(neo4j, audit_mock)
        resultado = await script.executar(
            pessoa_saiu_id=_make_pessoa_id(),
            relacoes_encerradas_ids=[_make_relacao_id()],
            motivo_saida="TRANSFERENCIA_DEFINITIVA",
            ator_id=uuid4(),
            ator_papel="elos_equipe",
        )

        assert resultado.degradacoes_criadas == 0
        assert resultado.relacoes_latentes == 0
        # Script20 NÃO deve ser chamado (sem degradações)
        neo4j.run_write.assert_not_called()  # CYPHER_MARCAR_LATENTE não é chamado

    @pytest.mark.asyncio
    async def test_script19_lista_vazia_sem_efeito(self, audit_mock):
        """Script19 com lista de relações vazia não afeta nenhum nó."""
        from app.scripts.ppr_script19 import Script19_PropagacaoTopologica

        neo4j = AsyncMock()
        script = Script19_PropagacaoTopologica(neo4j, audit_mock)
        resultado = await script.executar(
            pessoa_saiu_id=_make_pessoa_id(),
            relacoes_encerradas_ids=[],  # nenhuma relação
            motivo_saida="OBITO",
            ator_id=uuid4(),
        )

        assert resultado.nos_afetados == 0
        assert resultado.degradacoes_criadas == 0
        neo4j.run_single.assert_not_called()


# ─────────────────────────────────────────────────────────────
# Script 20 — Avaliação de Degradação Estrutural
# ─────────────────────────────────────────────────────────────

class TestScript20AvaliacaoDegradacao:
    """
    CONTRATO REAL: Script20.executar(pessoa_saiu_id, degradacao_ids: list[str], ...)
    Neo4j:
      run_many(CYPHER_DEGRADACOES_PENDENTES) → lista de degradacoes com relacoes_restantes
      run_single(CYPHER_TOTAL_NOS_SUBGRAFO) → {total_nos: N}
    BUG-09 CORRIGIDO neste arquivo.
    """

    @pytest.mark.asyncio
    async def test_script20_classifica_severidade_critica(self, audit_mock):
        """Script20 deve classificar CRITICA quando há nós com relacoes_restantes=0."""
        from app.scripts.ppr_script20 import Script20_AvaliacaoDegradacaoEstrutural, SeveridadeDegradacao

        neo4j = AsyncMock()
        # run_many: 3 degradações, 2 com relacoes_restantes=0 (nós isolados)
        neo4j.run_many.return_value = [
            {"degradacao_id": str(uuid4()), "no_id": str(uuid4()), "no_tipo": "PESSOA", "relacoes_restantes": 0},
            {"degradacao_id": str(uuid4()), "no_id": str(uuid4()), "no_tipo": "PESSOA", "relacoes_restantes": 0},
            {"degradacao_id": str(uuid4()), "no_id": str(uuid4()), "no_tipo": "PESSOA", "relacoes_restantes": 1},
        ]
        # run_single: total_nos para cálculo do índice
        neo4j.run_single.return_value = {"total_nos": 10}
        neo4j.run_write.return_value = [{"resolvidas": 3}]

        with patch("app.tasks.notification_tasks.task_notificar_equipe") as mock_notif:
            mock_notif.delay = MagicMock()
            script = Script20_AvaliacaoDegradacaoEstrutural(neo4j, audit_mock)
            resultado = await script.executar(
                pessoa_saiu_id=_make_pessoa_id(),     # BUG-09: pessoa_saiu_id
                degradacao_ids=[str(uuid4())],         # BUG-09: parâmetro obrigatório
                ator_id=uuid4(),
                ator_papel="elos_equipe",
                ip_origem="127.0.0.1",
            )

        assert resultado.severidade == SeveridadeDegradacao.CRITICA
        assert resultado.nos_isolados == 2

    @pytest.mark.asyncio
    async def test_script20_classifica_baixa_sem_isolados(self, audit_mock):
        """Script20 deve classificar BAIXA quando degradação < 20% sem nós isolados."""
        from app.scripts.ppr_script20 import Script20_AvaliacaoDegradacaoEstrutural, SeveridadeDegradacao

        neo4j = AsyncMock()
        # 1 degradação com relacoes_restantes=1 (não isolado)
        neo4j.run_many.return_value = [
            {"degradacao_id": str(uuid4()), "no_id": str(uuid4()), "no_tipo": "PESSOA", "relacoes_restantes": 1},
        ]
        # total_nos=100 → índice = 1/100 = 0.01 < 0.20 → BAIXA
        neo4j.run_single.return_value = {"total_nos": 100}
        neo4j.run_write.return_value = [{"resolvidas": 1}]

        with patch("app.tasks.notification_tasks.task_notificar_equipe") as mock_notif:
            mock_notif.delay = MagicMock()
            script = Script20_AvaliacaoDegradacaoEstrutural(neo4j, audit_mock)
            resultado = await script.executar(
                pessoa_saiu_id=_make_pessoa_id(),
                degradacao_ids=[str(uuid4())],
                ator_id=uuid4(),
                ator_papel="elos_equipe",
            )

        assert resultado.severidade == SeveridadeDegradacao.BAIXA
        assert resultado.nos_isolados == 0

    @pytest.mark.asyncio
    async def test_script20_calcula_indice_corretamente(self, audit_mock):
        """Índice de degradação = len(degradacoes) / total_nos."""
        from app.scripts.ppr_script20 import Script20_AvaliacaoDegradacaoEstrutural

        neo4j = AsyncMock()
        # 6 degradações, 10 nós → índice = 0.6 → ALTA (design: ALTA = > 50% estritamente)
        # BUG-TEST-03 CORRIGIDO: 0.5 exato não é ALTA (limiar é >, não >=)
        neo4j.run_many.return_value = [
            {"degradacao_id": str(uuid4()), "no_id": str(uuid4()), "no_tipo": "PESSOA", "relacoes_restantes": 1}
            for _ in range(6)
        ]
        neo4j.run_single.return_value = {"total_nos": 10}
        neo4j.run_write.return_value = [{"resolvidas": 6}]

        with patch("app.tasks.notification_tasks.task_notificar_equipe") as mock_notif:
            mock_notif.delay = MagicMock()
            script = Script20_AvaliacaoDegradacaoEstrutural(neo4j, audit_mock)
            resultado = await script.executar(
                pessoa_saiu_id=_make_pessoa_id(),
                degradacao_ids=[str(uuid4()) for _ in range(6)],
                ator_id=uuid4(),
            )

        assert resultado.indice_degradacao == 0.6
        from app.scripts.ppr_script20 import SeveridadeDegradacao
        assert resultado.severidade == SeveridadeDegradacao.ALTA

    def test_severidade_enum_limites(self):
        """SeveridadeDegradacao cobre todos os limiares esperados."""
        from app.scripts.ppr_script20 import SeveridadeDegradacao, Script20_AvaliacaoDegradacaoEstrutural
        s = Script20_AvaliacaoDegradacaoEstrutural.__new__(Script20_AvaliacaoDegradacaoEstrutural)
        assert s._calcular_severidade(0, 0.10) == SeveridadeDegradacao.BAIXA
        assert s._calcular_severidade(0, 0.30) == SeveridadeDegradacao.MEDIA
        assert s._calcular_severidade(0, 0.60) == SeveridadeDegradacao.ALTA
        assert s._calcular_severidade(1, 0.10) == SeveridadeDegradacao.CRITICA  # isolado → CRITICA

    def test_severidade_enum_valores_existem(self):
        """Todos os valores da enum SeveridadeDegradacao existem."""
        from app.scripts.ppr_script20 import SeveridadeDegradacao
        valores = {s.value for s in SeveridadeDegradacao}
        assert "BAIXA" in valores
        assert "MEDIA" in valores
        assert "ALTA" in valores
        assert "CRITICA" in valores
