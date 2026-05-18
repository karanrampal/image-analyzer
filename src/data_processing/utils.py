"""Utility functions"""

import logging
import string
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def load_sql_template(file_path: str | Path, params: dict[str, Any]) -> str:
    """Load a SQL file and substitute variables using string.Template.

    Args:
        file_path: Path to the SQL file.
        params: Dictionary of parameters to substitute.

    Returns:
        The formatted SQL query.
    """
    path = Path(file_path)
    if not path.exists():
        root_path = Path(__file__).resolve().parent / file_path
        if root_path.exists():
            path = root_path
        else:
            raise FileNotFoundError(f"SQL file not found: {file_path}")

    with path.open(encoding="utf-8") as f:
        template = string.Template(f.read())

    return template.substitute(params)
