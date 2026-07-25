from pathlib import Path

from outreach.db import split_statements


def test_split_statements_ignores_semicolons_in_comments() -> None:
    script = """
    -- keys override the defaults; an empty object means use the defaults
    CREATE TABLE a (id INT);
    CREATE TABLE b (id INT);
    """
    assert split_statements(script) == ["CREATE TABLE a (id INT)", "CREATE TABLE b (id INT)"]


def test_split_statements_drops_comment_only_lines() -> None:
    assert split_statements("-- just a comment\n") == []


def test_real_schema_yields_only_ddl() -> None:
    script = (Path(__file__).resolve().parent.parent / "sql" / "schema.sql").read_text(encoding="utf-8")
    statements = split_statements(script)
    assert statements
    assert all(statement.upper().startswith("CREATE") for statement in statements)
