"""Unit tests for the data_processing utils module."""

from pathlib import Path

import pytest

from data_processing.utils import load_sql_template


class TestLoadSqlTemplate:
    """Tests for the load_sql_template function."""

    def test_substitutes_params(self, tmp_path: Path) -> None:
        """Test that placeholders in the SQL file are replaced with supplied values."""
        sql_file = tmp_path / "query.sql"
        sql_file.write_text("SELECT * FROM $table WHERE id = '$id'")
        result = load_sql_template(sql_file, {"table": "my_table", "id": "42"})
        assert result == "SELECT * FROM my_table WHERE id = '42'"

    def test_accepts_path_object(self, tmp_path: Path) -> None:
        """Test that a pathlib.Path is accepted as file_path."""
        sql_file = tmp_path / "query.sql"
        sql_file.write_text("SELECT $col FROM t")
        result = load_sql_template(sql_file, {"col": "name"})
        assert result == "SELECT name FROM t"

    def test_accepts_string_path(self, tmp_path: Path) -> None:
        """Test that a plain string path is accepted as file_path."""
        sql_file = tmp_path / "query.sql"
        sql_file.write_text("SELECT $col FROM t")
        result = load_sql_template(str(sql_file), {"col": "id"})
        assert result == "SELECT id FROM t"

    def test_no_placeholders(self, tmp_path: Path) -> None:
        """Test that a template with no placeholders is returned unchanged."""
        sql_file = tmp_path / "query.sql"
        sql_file.write_text("SELECT 1")
        result = load_sql_template(sql_file, {})
        assert result == "SELECT 1"

    def test_multiple_placeholders(self, tmp_path: Path) -> None:
        """Test substitution of multiple distinct placeholders."""
        sql_file = tmp_path / "query.sql"
        sql_file.write_text("SELECT $col FROM $dataset.$table LIMIT $limit")
        result = load_sql_template(
            sql_file, {"col": "id", "dataset": "ds", "table": "t", "limit": "10"}
        )
        assert result == "SELECT id FROM ds.t LIMIT 10"

    def test_repeated_placeholder(self, tmp_path: Path) -> None:
        """Test that the same placeholder appearing multiple times is substituted everywhere."""
        sql_file = tmp_path / "query.sql"
        sql_file.write_text("SELECT $col, $col FROM t")
        result = load_sql_template(sql_file, {"col": "name"})
        assert result == "SELECT name, name FROM t"

    def test_file_not_found_raises(self, tmp_path: Path) -> None:
        """Test that a missing SQL file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_sql_template(tmp_path / "nonexistent.sql", {})

    def test_missing_placeholder_raises(self, tmp_path: Path) -> None:
        """Test that a placeholder with no matching param key raises KeyError."""
        sql_file = tmp_path / "query.sql"
        sql_file.write_text("SELECT $col FROM t")
        with pytest.raises(KeyError):
            load_sql_template(sql_file, {})

    def test_extra_params_ignored(self, tmp_path: Path) -> None:
        """Test that extra keys in params that have no placeholder do not raise."""
        sql_file = tmp_path / "query.sql"
        sql_file.write_text("SELECT $col FROM t")
        result = load_sql_template(sql_file, {"col": "id", "unused": "value"})
        assert result == "SELECT id FROM t"

    def test_preserves_whitespace_and_newlines(self, tmp_path: Path) -> None:
        """Test that whitespace and newlines in the SQL file are preserved."""
        sql = "SELECT\n  $col\nFROM\n  $table\n"
        sql_file = tmp_path / "query.sql"
        sql_file.write_text(sql)
        result = load_sql_template(sql_file, {"col": "id", "table": "t"})
        assert result == "SELECT\n  id\nFROM\n  t\n"
