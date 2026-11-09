import pytest
from app.tools.workspace_tools import validate_workspace_path


def test_workspace_path_rejects_traversal():
    with pytest.raises(ValueError):
        validate_workspace_path("../../etc/passwd")


def test_workspace_path_rejects_absolute():
    with pytest.raises(ValueError):
        validate_workspace_path("/etc/passwd")


def test_workspace_path_allows_claim_relative_file():
    assert validate_workspace_path("tests/test_analysis.py") == "tests/test_analysis.py"
