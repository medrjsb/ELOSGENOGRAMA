"""
ELOS — Infraestrutura mínima das tarefas assíncronas.

Em produção as tarefas rodam no Celery (broker em settings.celery_broker_url).
Sem Celery instalado (desenvolvimento, testes), `tarefa` devolve um objeto com
a mesma interface `.delay(**kwargs)` que executa a função na hora.

O worker injeta as dependências uma vez na inicialização:
    configurar_dependencias(neo4j_factory=..., audit_factory=...)
"""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

_deps: dict[str, Callable[[], Any]] = {}


def configurar_dependencias(**fabricas: Callable[[], Any]) -> None:
    _deps.update(fabricas)


def dependencia(nome: str) -> Any:
    try:
        return _deps[nome]()
    except KeyError:
        raise RuntimeError(
            f"Dependência '{nome}' não configurada; chame configurar_dependencias() no boot do worker"
        ) from None


def executar_async(coro: Awaitable[Any]) -> Any:
    """Roda uma corrotina a partir de código síncrono (corpo de tarefa Celery)."""
    return asyncio.run(coro)


try:
    from celery import shared_task as _shared_task

    def tarefa(nome: str):
        return _shared_task(name=nome, acks_late=True, max_retries=3)

except ImportError:  # pragma: no cover - caminho sem Celery

    class _TarefaLocal:
        def __init__(self, fn: Callable[..., Any], nome: str):
            self.fn = fn
            self.name = nome

        def __call__(self, *args: Any, **kwargs: Any) -> Any:
            return self.fn(*args, **kwargs)

        def delay(self, **kwargs: Any) -> Any:
            return self.fn(**kwargs)

    def tarefa(nome: str):
        return lambda fn: _TarefaLocal(fn, nome)
