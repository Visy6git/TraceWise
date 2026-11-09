import pytest
from app.services.sandbox_client import SandboxClient, SandboxUnavailable


def test_sandbox_fails_closed_when_disabled():
    client = SandboxClient(backend="disabled", required=True)
    with pytest.raises(SandboxUnavailable):
        client.execute("run-1", "claim-1", "analysis.py", {})
