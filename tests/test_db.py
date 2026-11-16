from contextlib import closing

from finance_analytics.db import connect, migrate
from finance_analytics.db.migrate import available_migrations, current_version


def test_migrations_apply_once_and_are_idempotent(tmp_path):
    with closing(connect(tmp_path / "test.db")) as conn:
        applied = migrate(conn)
        assert applied == [name for _, name, _ in available_migrations()]
        assert current_version(conn) == len(applied)
        assert migrate(conn) == []

        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert {"source_files", "accounts"} <= tables


def test_accounts_reject_unknown_kind_and_wrapper(tmp_path):
    with closing(connect(tmp_path / "test.db")) as conn:
        migrate(conn)
        conn.execute(
            "INSERT INTO accounts (id, alias, institution, kind, currency, tax_wrapper) "
            "VALUES ('xtb-ike', 'IKE', 'xtb', 'broker', 'PLN', 'IKE')"
        )
        for kind, wrapper in (("savings", None), ("broker", "PPK")):
            try:
                conn.execute(
                    "INSERT INTO accounts (id, alias, institution, kind, currency, tax_wrapper) "
                    "VALUES ('bad', 'x', 'x', ?, 'PLN', ?)",
                    (kind, wrapper),
                )
            except Exception as exc:  # sqlite3.IntegrityError
                assert "CHECK" in str(exc)
            else:
                raise AssertionError(f"accepted kind={kind} wrapper={wrapper}")
