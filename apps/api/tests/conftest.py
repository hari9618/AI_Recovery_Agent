import os

# Point the app at the test database BEFORE any app module reads settings.
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://postgres@127.0.0.1:5433/revenue_recovery_test"
)
os.environ["ENVIRONMENT"] = "test"

import pytest  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.llm.ledger import ledger_disabled  # noqa: E402

# Tests must never call real external services, even if the developer's .env contains keys.
_settings = get_settings()
_settings.groq_api_key = None
_settings.langfuse_public_key = None
_settings.langfuse_secret_key = None


@pytest.fixture(autouse=True)
def _no_llm_ledger(request):
    """Tests never write LLM usage rows unless marked `ledger`."""
    if request.node.get_closest_marker("ledger"):
        yield
        return
    with ledger_disabled():
        yield
