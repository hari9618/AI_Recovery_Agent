from app.core.config import normalise_database_url


def test_hosted_database_urls_are_normalised_for_asyncpg():
    neon = "postgresql://u:p%40ss@ep-x.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
    assert (
        normalise_database_url(neon)
        == "postgresql+asyncpg://u:p%40ss@ep-x.ap-southeast-1.aws.neon.tech/neondb?ssl=require"
    )
    assert normalise_database_url("postgres://u@h:5432/db").startswith("postgresql+asyncpg://u@h:5432/db")
    local = "postgresql+asyncpg://postgres@127.0.0.1:5433/revenue_recovery"
    assert normalise_database_url(local) == local
