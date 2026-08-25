from vsm.backends.dburl import resolve_db_url


def test_unpooled_url_wins():
    """The pooled URL is PgBouncer in transaction mode and does not support
    prepared statements — a failure that surfaces as a confusing runtime error
    rather than at connect time. Prefer the unpooled one."""
    got = resolve_db_url({
        "POSTGRES_URL": "postgres://pooled/db",
        "POSTGRES_URL_NON_POOLING": "postgres://direct/db",
    })
    assert "direct" in got


def test_the_postgres_scheme_alias_is_rewritten():
    """Every provider's dashboard emits `postgres://`. Drivers want
    `postgresql://`. Rewriting it here removes the trap rather than documenting
    it."""
    assert resolve_db_url({"DATABASE_URL": "postgres://h/db"}).startswith("postgresql://")


def test_no_database_configured_returns_none_not_a_tmp_sqlite_path():
    """The parent fell back to `sqlite:////tmp/...` here and lost a real
    visitor's consent record: /tmp on a serverless host belongs to one
    invocation, so the write succeeded and the container holding it was
    destroyed. Returning None makes the caller decide, loudly."""
    assert resolve_db_url({}) is None


def test_every_recognised_variable_name():
    for name in ("POSTGRES_URL_NON_POOLING", "POSTGRES_URL", "DATABASE_URL"):
        assert resolve_db_url({name: "postgres://h/db"}) is not None
