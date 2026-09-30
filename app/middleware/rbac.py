"""
ELOS — Middleware RBAC (7 etapas)
Implementa a cadeia de autorização definida no doc 06_LGPD-Arquitetural

Etapas:
  1. Parse JWT → verificar assinatura RS256 (Supabase)
  2. Carregar perfil do ator → papel RBAC
  3. Verificar permissão da operação → matriz RBAC
  4. Verificar consentimento do paciente → finalidade do acesso
  5. Verificar escopo territorial → municipio/UF
  6. Registrar tentativa de acesso no audit_log
  7. Executar operação → retornar resposta
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Optional
from uuid import UUID

import structlog
from jose import JWTError, jwt

log = structlog.get_logger(__name__)


# ── Papéis ────────────────────────────────────────────────────────────────────

class Papel(str, enum.Enum):
    EQUIPE           = "elos_equipe"
    UBS              = "elos_ubs"
    CAPS_REFERENCIA  = "elos_caps_referencia"
    PESQUISA         = "elos_pesquisa"
    ADMIN            = "elos_admin"


# ── Operações ─────────────────────────────────────────────────────────────────

class Operacao(str, enum.Enum):
    LEITURA_PERFIL        = "LEITURA_PERFIL"
    LEITURA_GRAFO         = "LEITURA_GRAFO"
    ESCRITA_EVENTO        = "ESCRITA_EVENTO"
    ESCRITA_RELACAO       = "ESCRITA_RELACAO"
    REVOGACAO_CONSENTIMENTO = "REVOGACAO_CONSENTIMENTO"
    EXPORTACAO_PESQUISA   = "EXPORTACAO_PESQUISA"
    GESTAO_USUARIOS       = "GESTAO_USUARIOS"
    LEITURA_AUDITORIA     = "LEITURA_AUDITORIA"
    ENCAMINHAMENTO_RAPS   = "ENCAMINHAMENTO_RAPS"
    INTEGRACAO_RNDS       = "INTEGRACAO_RNDS"
    INTEGRACAO_ESUS       = "INTEGRACAO_ESUS"
    ANONIMIZACAO          = "ANONIMIZACAO"


# ── Finalidades ((:CONSENTIMENTO)) ────────────────────────────────────────────

class Finalidade(str, enum.Enum):
    CUIDADO           = "CUIDADO"
    PESQUISA          = "PESQUISA"
    RNDS              = "RNDS"
    COMPARTILHAMENTO  = "COMPARTILHAMENTO"


# ── Matriz RBAC: papel → conjunto de operações permitidas ─────────────────────
# Fonte: Tabela Seção G do doc 06_LGPD-Arquitetural

MATRIZ_RBAC: dict[Papel, set[Operacao]] = {
    Papel.EQUIPE: {
        Operacao.LEITURA_PERFIL,
        Operacao.LEITURA_GRAFO,
        Operacao.ESCRITA_EVENTO,
        Operacao.ESCRITA_RELACAO,
        Operacao.REVOGACAO_CONSENTIMENTO,   # Apenas com presença do paciente
        Operacao.ENCAMINHAMENTO_RAPS,
    },
    Papel.UBS: {
        Operacao.LEITURA_PERFIL,
        Operacao.LEITURA_GRAFO,
        Operacao.ESCRITA_EVENTO,
        Operacao.ESCRITA_RELACAO,
        Operacao.ENCAMINHAMENTO_RAPS,
        Operacao.INTEGRACAO_ESUS,
    },
    Papel.CAPS_REFERENCIA: {
        Operacao.LEITURA_PERFIL,
        Operacao.LEITURA_GRAFO,
        Operacao.ESCRITA_EVENTO,            # Apenas parecer CAPS
        Operacao.ENCAMINHAMENTO_RAPS,
    },
    Papel.PESQUISA: {
        Operacao.LEITURA_GRAFO,             # Apenas dados anonimizados
        Operacao.EXPORTACAO_PESQUISA,
    },
    Papel.ADMIN: {op for op in Operacao},  # Full access
}

# Operações que requerem consentimento ativo do paciente (finalidade CUIDADO)
# BUG-11 CORRIGIDO: EXPORTACAO_PESQUISA adicionado — pesquisador requer consentimento para exportação
OPERACOES_QUE_EXIGEM_CONSENTIMENTO: set[Operacao] = {
    Operacao.LEITURA_PERFIL,
    Operacao.LEITURA_GRAFO,
    Operacao.ESCRITA_EVENTO,
    Operacao.ESCRITA_RELACAO,
    Operacao.INTEGRACAO_RNDS,
    Operacao.EXPORTACAO_PESQUISA,
}

# Operações restritas ao escopo territorial do ator
OPERACOES_COM_ESCOPO_TERRITORIAL: set[Operacao] = {
    Operacao.LEITURA_PERFIL,
    Operacao.LEITURA_GRAFO,
    Operacao.ESCRITA_EVENTO,
    Operacao.ESCRITA_RELACAO,
}


# ── Contexto do ator autenticado ──────────────────────────────────────────────

@dataclass
class RBACContext:
    user_id: UUID
    papel: Papel
    municipio_id: Optional[str] = None
    ubs_id: Optional[str] = None
    token_raw: str = field(repr=False, default="")

    def pode(self, operacao: Operacao) -> bool:
        """Etapa 3: verificar permissão na matriz RBAC."""
        return operacao in MATRIZ_RBAC.get(self.papel, set())

    def exige_consentimento(self, operacao: Operacao) -> bool:
        return operacao in OPERACOES_QUE_EXIGEM_CONSENTIMENTO

    def tem_escopo_territorial(self, operacao: Operacao) -> bool:
        return operacao in OPERACOES_COM_ESCOPO_TERRITORIAL

    def is_pesquisa(self) -> bool:
        return self.papel == Papel.PESQUISA

    def is_admin(self) -> bool:
        return self.papel == Papel.ADMIN


# ── Verificação RBAC principal ────────────────────────────────────────────────

class RBACViolation(Exception):
    """Levantada quando uma etapa RBAC falha."""
    def __init__(self, etapa: int, motivo: str):
        self.etapa = etapa
        self.motivo = motivo
        super().__init__(f"RBAC etapa {etapa}: {motivo}")


def verificar_rbac(
    actor: RBACContext,
    operacao: Operacao,
    *,
    consentimento_ativo: bool = True,
    paciente_municipio_id: Optional[str] = None,
) -> None:
    """
    Executa etapas 3, 4 e 5 da cadeia RBAC.
    Levanta RBACViolation se qualquer etapa falhar.
    """
    # Etapa 3: matriz RBAC
    if not actor.pode(operacao):
        raise RBACViolation(
            3,
            f"Papel '{actor.papel.value}' não tem permissão para '{operacao.value}'",
        )

    # Etapa 4: consentimento do paciente (Admin bypassa — auditoria cobre o acesso)
    # BUG-12 CORRIGIDO: Admin não é bloqueado por ausência de consentimento
    if not actor.is_admin() and actor.exige_consentimento(operacao) and not consentimento_ativo:
        raise RBACViolation(
            4,
            f"Operação '{operacao.value}' requer consentimento ativo do paciente (finalidade CUIDADO)",
        )

    # Etapa 5: escopo territorial (PESQUISA ignora — vê anonimizado)
    if (
        actor.tem_escopo_territorial(operacao)
        and not actor.is_admin()
        and not actor.is_pesquisa()
        and paciente_municipio_id
        and actor.municipio_id
        and actor.municipio_id != paciente_municipio_id
    ):
        raise RBACViolation(
            5,
            f"Acesso territorial negado: ator em '{actor.municipio_id}', "
            f"paciente em '{paciente_municipio_id}'",
        )


# ── Decode JWT ────────────────────────────────────────────────────────────────

def decode_jwt(token: str, secret: str) -> dict:
    """
    Etapa 1: Decodifica e valida o JWT RS256 do Supabase.
    Lança ValueError se o token for inválido ou expirado.
    """
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],   # Supabase usa HS256 com JWT_SECRET
            options={"verify_aud": False},
        )
        return payload
    except JWTError as exc:
        raise ValueError(str(exc)) from exc
