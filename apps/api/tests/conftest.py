import pytest

from app.llm.ledger import ledger_disabled


@pytest.fixture(autouse=True)
def _no_llm_ledger():
    """Tests never write LLM usage rows unless a test opts back in explicitly."""
    with ledger_disabled():
        yield
