"""
ELOS — Testes: RBAC 7-etapas
Valida a matriz de permissões e as restrições territoriais/consentimento.
"""
import pytest
from uuid import uuid4

from app.middleware.rbac import (
    Papel,
    Operacao,
    RBACContext,
    RBACViolation,
    MATRIZ_RBAC,
    verificar_rbac,
)


# ─────────────────────────────────────────────────────────────
# 1. Matriz básica de permissões por papel
# ─────────────────────────────────────────────────────────────

class TestMatrizRBAC:
    """Verifica que cada papel tem exatamente as operações esperadas."""

    def _ctx(self, papel: Papel) -> RBACContext:
        return RBACContext(
            user_id=uuid4(),
            papel=papel,
            municipio_id="PE260000",
            ubs_id="ubs-001",
            token_raw="mock",
        )

    # elos_equipe: pode ler perfil, grafo, escrever evento e relação
    def test_equipe_pode_leitura_perfil(self):
        assert self._ctx(Papel.EQUIPE).pode(Operacao.LEITURA_PERFIL)

    def test_equipe_pode_escrita_evento(self):
        assert self._ctx(Papel.EQUIPE).pode(Operacao.ESCRITA_EVENTO)

    def test_equipe_pode_escrita_relacao(self):
        assert self._ctx(Papel.EQUIPE).pode(Operacao.ESCRITA_RELACAO)

    def test_equipe_nao_pode_exportacao_pesquisa(self):
        assert not self._ctx(Papel.EQUIPE).pode(Operacao.EXPORTACAO_PESQUISA)

    def test_equipe_nao_pode_gestao_usuarios(self):
        assert not self._ctx(Papel.EQUIPE).pode(Operacao.GESTAO_USUARIOS)

    # elos_pesquisa: pode exportar, não pode escrever eventos clínicos
    def test_pesquisa_pode_exportacao(self):
        assert self._ctx(Papel.PESQUISA).pode(Operacao.EXPORTACAO_PESQUISA)

    def test_pesquisa_nao_pode_leitura_perfil(self):
        """PESQUISA acessa apenas dados anonimizados via LEITURA_GRAFO — não LEITURA_PERFIL nominativa.
        BUG-TEST-01 CORRIGIDO: teste anterior assumia permissão que o design não prevê.
        """
        assert not self._ctx(Papel.PESQUISA).pode(Operacao.LEITURA_PERFIL)

    def test_pesquisa_nao_pode_escrita_evento(self):
        assert not self._ctx(Papel.PESQUISA).pode(Operacao.ESCRITA_EVENTO)

    def test_pesquisa_nao_pode_revogacao_consentimento(self):
        assert not self._ctx(Papel.PESQUISA).pode(Operacao.REVOGACAO_CONSENTIMENTO)

    # elos_admin: pode tudo
    def test_admin_pode_tudo(self):
        for op in Operacao:
            assert self._ctx(Papel.ADMIN).pode(op), f"Admin deveria poder: {op}"

    # elos_ubs: pode leitura + eventos, não pode anonimizar
    def test_ubs_pode_leitura_perfil(self):
        assert self._ctx(Papel.UBS).pode(Operacao.LEITURA_PERFIL)

    def test_ubs_nao_pode_anonimizacao(self):
        assert not self._ctx(Papel.UBS).pode(Operacao.ANONIMIZACAO)

    # elos_caps_referencia: pode encaminhamento RAPS
    def test_caps_pode_encaminhamento_raps(self):
        assert self._ctx(Papel.CAPS_REFERENCIA).pode(Operacao.ENCAMINHAMENTO_RAPS)

    def test_caps_nao_pode_gestao_usuarios(self):
        assert not self._ctx(Papel.CAPS_REFERENCIA).pode(Operacao.GESTAO_USUARIOS)


# ─────────────────────────────────────────────────────────────
# 2. Etapa 3: verificar_rbac levanta RBACViolation corretamente
# ─────────────────────────────────────────────────────────────

class TestVerificarRBACEtapa3:

    def test_equipe_leitura_perfil_ok(self, actor_equipe):
        # Não deve levantar exceção
        verificar_rbac(actor_equipe, Operacao.LEITURA_PERFIL)

    def test_equipe_exportacao_pesquisa_proibida(self, actor_equipe):
        with pytest.raises(RBACViolation):
            verificar_rbac(actor_equipe, Operacao.EXPORTACAO_PESQUISA)

    def test_pesquisa_escrita_evento_proibida(self, actor_pesquisa):
        with pytest.raises(RBACViolation):
            verificar_rbac(actor_pesquisa, Operacao.ESCRITA_EVENTO)

    def test_admin_anonimizacao_ok(self, actor_admin):
        verificar_rbac(actor_admin, Operacao.ANONIMIZACAO)


# ─────────────────────────────────────────────────────────────
# 3. Etapa 4: consentimento obrigatório
# ─────────────────────────────────────────────────────────────

class TestConsentimento:

    def test_equipe_bloqueada_sem_consentimento(self, actor_equipe):
        """Profissional não acessa perfil sem consentimento ativo."""
        with pytest.raises(RBACViolation):
            verificar_rbac(
                actor_equipe,
                Operacao.LEITURA_PERFIL,
                consentimento_ativo=False,
            )

    def test_admin_passa_sem_consentimento(self, actor_admin):
        """Admin não é bloqueado por ausência de consentimento."""
        # Não deve levantar exceção
        verificar_rbac(
            actor_admin,
            Operacao.LEITURA_PERFIL,
            consentimento_ativo=False,
        )

    def test_pesquisa_requer_consentimento_pesquisa(self, actor_pesquisa):
        """Pesquisador requer consentimento para exportação."""
        with pytest.raises(RBACViolation):
            verificar_rbac(
                actor_pesquisa,
                Operacao.EXPORTACAO_PESQUISA,
                consentimento_ativo=False,
            )

    def test_equipe_ok_com_consentimento(self, actor_equipe):
        """Profissional acessa perfil com consentimento ativo."""
        verificar_rbac(
            actor_equipe,
            Operacao.LEITURA_PERFIL,
            consentimento_ativo=True,
        )


# ─────────────────────────────────────────────────────────────
# 4. Etapa 5: escopo territorial
# ─────────────────────────────────────────────────────────────

class TestEscopoTerritorial:

    def test_equipe_nao_acessa_fora_do_municipio(self, actor_equipe):
        """Equipe só acessa pacientes do seu município."""
        with pytest.raises(RBACViolation):
            verificar_rbac(
                actor_equipe,
                Operacao.LEITURA_PERFIL,
                consentimento_ativo=True,
                paciente_municipio_id="SP000000",  # outro município
            )

    def test_equipe_acessa_mesmo_municipio(self, actor_equipe):
        """Equipe acessa pacientes do próprio município."""
        verificar_rbac(
            actor_equipe,
            Operacao.LEITURA_PERFIL,
            consentimento_ativo=True,
            paciente_municipio_id="PE260000",  # mesmo município
        )

    def test_admin_acessa_qualquer_municipio(self, actor_admin):
        """Admin não tem restrição territorial."""
        verificar_rbac(
            actor_admin,
            Operacao.LEITURA_PERFIL,
            consentimento_ativo=False,
            paciente_municipio_id="AM000000",
        )

    def test_pesquisa_sem_restricao_territorial(self, actor_pesquisa):
        """Pesquisador não tem restrição territorial — LEITURA_GRAFO anonimizada é global.
        BUG-TEST-02 CORRIGIDO: teste anterior usava LEITURA_PERFIL (não permitida a PESQUISA).
        Usa LEITURA_GRAFO que é a operação correta para o papel PESQUISA.
        """
        # LEITURA_GRAFO com consentimento ativo, paciente em outro estado → sem restrição territorial
        verificar_rbac(
            actor_pesquisa,
            Operacao.LEITURA_GRAFO,
            consentimento_ativo=True,
            paciente_municipio_id="RJ000000",
        )


# ─────────────────────────────────────────────────────────────
# 5. Integridade da matriz: sem lacunas
# ─────────────────────────────────────────────────────────────

class TestIntegridadeMatriz:

    def test_todos_papeis_mapeados(self):
        """Todos os valores de Papel têm entrada na MATRIZ_RBAC."""
        for papel in Papel:
            assert papel in MATRIZ_RBAC, f"Papel sem entrada na matriz: {papel}"

    def test_todos_papeis_tem_permissoes(self):
        """Nenhum papel tem conjunto de permissões vazio."""
        for papel, ops in MATRIZ_RBAC.items():
            assert len(ops) > 0, f"Papel sem permissões: {papel}"

    def test_operacoes_sao_tipo_correto(self):
        """Todas as permissões na matriz são instâncias de Operacao."""
        for papel, ops in MATRIZ_RBAC.items():
            for op in ops:
                assert isinstance(op, Operacao), f"Permissão inválida: {op} em {papel}"
