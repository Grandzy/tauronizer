"""Never contact production PSE during tests; HTTP responses are mocked explicitly."""
import pytest

@pytest.fixture(autouse=True)
def disable_live_kompas(monkeypatch):
    monkeypatch.setenv('KOMPAS_AUTO_SYNC', '0')
