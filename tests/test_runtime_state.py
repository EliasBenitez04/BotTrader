from app.services.runtime_state import RuntimeStateService


class FakeRow:
    def __init__(self, key: str, value: str):
        self.key = key
        self.value = value


class FakeSession:
    def __init__(self):
        self.rows = {}

    def get(self, _, key):
        return self.rows.get(key)

    def add(self, row):
        self.rows[row.key] = row

    def delete(self, row):
        self.rows.pop(row.key, None)

    def flush(self):
        return None


def test_live_halt_round_trip() -> None:
    session = FakeSession()
    service = RuntimeStateService(session)
    payload = service.halt_live(
        reason="unknown execution",
        symbol="BTCUSDT",
        context={"order": "abc"},
    )

    assert service.live_halt()["reason"] == "unknown execution"
    assert payload["symbol"] == "BTCUSDT"

    service.clear_live_halt()
    assert service.live_halt() is None
