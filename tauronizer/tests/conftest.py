"""Never contact production energy feeds during tests; HTTP responses are mocked explicitly."""
import pytest

@pytest.fixture(autouse=True)
def disable_live_kompas(monkeypatch):
    monkeypatch.setenv('KOMPAS_AUTO_SYNC', '0')

    monkeypatch.setenv('EXPORT_PRICES_AUTO_SYNC', '0')

    monkeypatch.setenv('PURCHASE_PRICES_AUTO_SYNC', '0')

    # No operator network requests from analysis endpoints either.
    import httpx
    from tauronizer.purchase_prices import PurchasePriceCache
    original = PurchasePriceCache.__init__
    def offline(self, *args, **kwargs):
        original(self, *args, **kwargs)
        self.http = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(503)))
    monkeypatch.setattr(PurchasePriceCache, '__init__', offline)
