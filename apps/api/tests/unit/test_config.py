import pytest

from app.core.config import Settings, normalise_database_url


def test_hosted_database_urls_are_normalised_for_asyncpg():
    neon = "postgresql://u:p%40ss@ep-x.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
    assert (
        normalise_database_url(neon)
        == "postgresql+asyncpg://u:p%40ss@ep-x.ap-southeast-1.aws.neon.tech/neondb?ssl=require"
    )
    assert normalise_database_url("postgres://u@h:5432/db").startswith("postgresql+asyncpg://u@h:5432/db")
    local = "postgresql+asyncpg://postgres@127.0.0.1:5433/revenue_recovery"
    assert normalise_database_url(local) == local


def test_production_refuses_the_public_default_token():
    with pytest.raises(ValueError, match="DEMO_API_TOKEN"):
        Settings(environment="production", demo_api_token="dev-demo-token-change-me")
    with pytest.raises(ValueError, match="DEMO_API_TOKEN"):
        Settings(environment="production", demo_api_token="  ")
    assert Settings(environment="production", demo_api_token="a-private-random-token").environment == "production"
    assert Settings(environment="development").demo_api_token.get_secret_value() == "dev-demo-token-change-me"
