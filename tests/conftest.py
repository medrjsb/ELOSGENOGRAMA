"""
ELOS — Fixtures compartilhadas dos testes.

Reconstruído a partir do uso em test_rbac.py (o conftest original não foi versionado).
Os atores de equipe usam o mesmo município dos testes territoriais (PE260000).
"""
from uuid import uuid4

import pytest

from app.middleware.rbac import Papel, RBACContext


def _actor(papel: Papel, municipio_id: str | None = "PE260000") -> RBACContext:
    return RBACContext(
        user_id=uuid4(),
        papel=papel,
        municipio_id=municipio_id,
        ubs_id="ubs-001",
        token_raw="mock",
    )


@pytest.fixture
def actor_equipe() -> RBACContext:
    return _actor(Papel.EQUIPE)


@pytest.fixture
def actor_pesquisa() -> RBACContext:
    return _actor(Papel.PESQUISA, municipio_id=None)


@pytest.fixture
def actor_admin() -> RBACContext:
    return _actor(Papel.ADMIN, municipio_id=None)
