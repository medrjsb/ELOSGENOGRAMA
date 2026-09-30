# ELOS — Cartografia Relacional 3D

Genograma + ecomapa + teoria Bowen + linha do tempo em 3D, como aplicação web single-file.

| Caminho | Conteúdo |
|---|---|
| `elos_v19.html` | Versão atual (deploy no Netlify por drag-and-drop). Corresponde ao upload `elos_v19-2`. |
| `historico/` | Versões anteriores: v15–v18, `elos_v19-0` (v19 original) e `elos_v19-1`. |
| `app/` | Backend Python: `core/config.py`, `middleware/rbac.py`, `services/fhir_mapper.py`. |
| `tests/` | Testes pytest (`conftest.py` com os atores RBAC). |
| `docs/` | Contexto do projeto e capturas de tela. |

## Testes

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt pytest pytest-asyncio
pytest
```

`tests/test_ppr.py` depende de `app/scripts/ppr_script18|19|20.py`, `app/tasks/ppr_tasks.py`
e da fixture `audit_mock`, que ainda não estão no repositório.
