"""Home Assistant client: REST for entities, WebSocket for statistics."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import httpx
import websockets
from websockets.exceptions import ConnectionClosed

from .calc import ConsumptionSample

_LOGGER = logging.getLogger(__name__)

ENERGY_UNITS = {
    "wh": 0.001,
    "kwh": 1.0,
    "mwh": 1000.0,
    "gwh": 1_000_000.0,
    "gj": 277.7777777778,
    "mj": 0.2777777778,
    "kj": 0.0002777777778,
    "j": 2.7777777778e-7,
}

STATS_TIMEOUT = 120


class HAError(RuntimeError):
    """A user-facing Home Assistant communication problem."""


class HAClient:
    def __init__(self) -> None:
        supervisor_token = os.getenv("SUPERVISOR_TOKEN") or os.getenv("HASSIO_TOKEN")
        self.is_supervisor = bool(supervisor_token)
        self.token = supervisor_token or os.getenv("HA_TOKEN", "")

        ha_url = os.getenv("HA_URL", "").strip().rstrip("/")
        if ha_url:
            if ha_url.endswith("/api"):
                ha_url = ha_url[:-4].rstrip("/")
            self.base_url = ha_url
        elif self.is_supervisor:
            self.base_url = "http://supervisor/core"
        else:
            self.base_url = "http://homeassistant:8123"

        self.rest_url = f"{self.base_url}/api"
        if self.base_url.startswith("https://"):
            self.ws_url = "wss://" + self.base_url[len("https://") :] + "/websocket"
        else:
            self.ws_url = "ws://" + self.base_url.split("://", 1)[-1] + "/websocket"

        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, read=60.0),
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self._ws: Any = None
        self._ws_lock = asyncio.Lock()
        self._message_id = 0
        self._states_cache: tuple[float, list[dict[str, Any]]] | None = None

    # -- lifecycle ---------------------------------------------------------

    async def close(self) -> None:
        await self._close_ws()
        await self._http.aclose()

    async def _close_ws(self) -> None:
        connection = self._ws
        self._ws = None
        if connection is not None:
            try:
                await connection.close()
            except Exception:  # pragma: no cover - best effort cleanup
                pass

    # -- REST --------------------------------------------------------------

    async def _rest_get(self, path: str) -> Any:
        if not self.token:
            raise HAError(
                "Brak tokenu Home Assistant. W aplikacji HA token Supervisora "
                "jest dodawany automatycznie — sprawdź uprawnienia aplikacji."
            )
        try:
            response = await self._http.get(f"{self.rest_url}{path}")
        except httpx.HTTPError as exc:
            raise HAError(f"Nie można połączyć się z Home Assistant: {exc}") from exc
        if response.status_code >= 400:
            raise HAError(
                f"Home Assistant zwrócił błąd {response.status_code}: "
                f"{response.text[:300]}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise HAError("Home Assistant zwrócił nieprawidłową odpowiedź JSON.") from exc

    async def get_states(self, *, force: bool = False) -> list[dict[str, Any]]:
        now = time.monotonic()
        if not force and self._states_cache and now - self._states_cache[0] < 30:
            return self._states_cache[1]
        states = await self._rest_get("/states")
        if not isinstance(states, list):
            raise HAError("Nieoczekiwany format listy encji z Home Assistant.")
        self._states_cache = (now, states)
        return states

    async def get_entity(self, entity_id: str) -> dict[str, Any]:
        states = await self.get_states()
        for state in states:
            if state.get("entity_id") == entity_id:
                return state
        states = await self.get_states(force=True)
        for state in states:
            if state.get("entity_id") == entity_id:
                return state
        raise HAError(
            f"Nie znaleziono encji {entity_id}. Sprawdź, czy istnieje w Home Assistant."
        )

    async def get_energy_entities(self) -> list[dict[str, Any]]:
        states = await self.get_states()
        entities: list[dict[str, Any]] = []
        for state in states:
            entity_id = state.get("entity_id", "")
            if not entity_id.startswith("sensor."):
                continue
            attributes = state.get("attributes") or {}
            unit = str(attributes.get("unit_of_measurement") or "").lower()
            device_class = attributes.get("device_class")
            state_class = attributes.get("state_class")
            if unit not in ENERGY_UNITS:
                continue
            if device_class != "energy" and state_class not in ("total", "total_increasing"):
                continue
            entities.append(
                {
                    "entity_id": entity_id,
                    "name": attributes.get("friendly_name") or entity_id,
                    "unit": attributes.get("unit_of_measurement"),
                    "state_class": state_class,
                    "device_class": device_class,
                    "state": state.get("state"),
                    "available": state.get("state") not in (None, "unavailable", "unknown"),
                }
            )
        entities.sort(key=lambda item: (item["name"].casefold(), item["entity_id"]))
        return entities

    # -- WebSocket ---------------------------------------------------------

    async def _ensure_ws(self) -> None:
        if not self.token:
            raise HAError(
                "Brak tokenu Home Assistant. W aplikacji HA token Supervisora "
                "jest dodawany automatycznie — sprawdź uprawnienia aplikacji."
            )
        if self._ws is not None:
            return
        try:
            self._ws = await websockets.connect(
                self.ws_url,
                max_size=64 * 1024 * 1024,
                open_timeout=20,
                ping_interval=20,
                ping_timeout=20,
            )
            hello = json.loads(await asyncio.wait_for(self._ws.recv(), 20))
            if hello.get("type") != "auth_required":
                raise HAError(
                    "Home Assistant nie poprosił o uwierzytelnienie. "
                    "Sprawdź konfigurację połączenia."
                )
            await self._ws.send(
                json.dumps({"type": "auth", "access_token": self.token})
            )
            reply = json.loads(await asyncio.wait_for(self._ws.recv(), 20))
        except HAError:
            await self._close_ws()
            raise
        except (OSError, TimeoutError, ConnectionClosed, ValueError) as exc:
            await self._close_ws()
            raise HAError(
                f"Nie można otworzyć połączenia WebSocket z Home Assistant: {exc}"
            ) from exc

        if reply.get("type") != "auth_ok":
            await self._close_ws()
            raise HAError(
                "Home Assistant odrzucił token (WebSocket). "
                "Upewnij się, że aplikacja ma dostęp do API Home Assistant."
            )

    async def _ws_call(self, payload: dict[str, Any], timeout: float = 60) -> Any:
        async with self._ws_lock:
            last_error: Exception | None = None
            for attempt in (1, 2):
                try:
                    await self._ensure_ws()
                    self._message_id += 1
                    message_id = self._message_id
                    await self._ws.send(json.dumps({**payload, "id": message_id}))
                    while True:
                        raw = await asyncio.wait_for(self._ws.recv(), timeout)
                        data = json.loads(raw)
                        if data.get("id") != message_id:
                            continue
                        if not data.get("success", False):
                            error = data.get("error") or {}
                            raise HAError(
                                f"Home Assistant odrzucił zapytanie: "
                                f"{error.get('code', 'error')} — "
                                f"{error.get('message', 'nieznany błąd')}"
                            )
                        return data.get("result")
                except HAError:
                    raise
                except (OSError, TimeoutError, ConnectionClosed, ValueError) as exc:
                    last_error = exc
                    await self._close_ws()
                    if attempt == 1:
                        _LOGGER.warning("WebSocket dropped, reconnecting: %s", exc)
                        continue
            raise HAError(
                "Utracono połączenie z Home Assistant podczas pobierania statystyk. "
                f"Szczegóły: {last_error}"
            )

    async def get_statistics_metadata(self, entity_id: str) -> dict[str, Any]:
        result = await self._ws_call(
            {
                "type": "recorder/get_statistics_metadata",
                "statistic_ids": [entity_id],
            }
        )
        if isinstance(result, list):
            for item in result:
                if item.get("statistic_id") == entity_id:
                    return item
        elif isinstance(result, dict):
            item = result.get(entity_id)
            if isinstance(item, dict):
                return item
        return {}

    @staticmethod
    def _parse_start(value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
                    timezone.utc
                )
            except ValueError:
                return None
        if isinstance(value, (int, float)):
            seconds = value / 1000 if value > 100_000_000_000 else value
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        return None

    async def get_statistics(
        self,
        entity_id: str,
        start: datetime,
        end: datetime,
    ) -> tuple[list[ConsumptionSample], str]:
        """Fetch hourly long-term statistics converted to kWh."""

        result = await self._ws_call(
            {
                "type": "recorder/statistics_during_period",
                "start_time": start.astimezone(timezone.utc).isoformat(),
                "end_time": end.astimezone(timezone.utc).isoformat(),
                "statistic_ids": [entity_id],
                "period": "hour",
                "types": ["change"],
            },
            timeout=STATS_TIMEOUT,
        )

        rows: list[dict[str, Any]] = []
        if isinstance(result, dict):
            raw_rows = result.get(entity_id)
            if isinstance(raw_rows, list):
                rows = raw_rows
        elif isinstance(result, list):
            rows = [row for row in result if isinstance(row, dict)]

        unit = ""
        try:
            metadata = await self.get_statistics_metadata(entity_id)
            unit = str(metadata.get("unit_of_measurement") or "")
        except HAError as exc:
            _LOGGER.debug("No statistics metadata for %s: %s", entity_id, exc)

        if not unit:
            entity = await self.get_entity(entity_id)
            unit = str((entity.get("attributes") or {}).get("unit_of_measurement") or "kWh")

        factor = ENERGY_UNITS.get(unit.lower(), 1.0)
        samples: list[ConsumptionSample] = []
        for row in rows:
            timestamp = self._parse_start(row.get("start"))
            change = row.get("change")
            if timestamp is None or change is None:
                continue
            try:
                kwh = float(change) * factor
            except (TypeError, ValueError):
                continue
            samples.append(ConsumptionSample(timestamp=timestamp, kwh=kwh))

        samples.sort(key=lambda sample: sample.timestamp)
        return samples, unit

    async def publish_mqtt(self, topic: str, payload: str, *, retain: bool) -> None:
        """Use HA's configured broker through the documented mqtt.publish action."""
        if not self.token:
            raise HAError('Brak połączenia z Home Assistant do publikacji MQTT.')
        try:
            response = await self._http.post(
                f'{self.rest_url}/services/mqtt/publish',
                json={'topic': topic, 'payload': payload, 'qos': 1, 'retain': retain},
                timeout=10.0,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise HAError('Nie udało się opublikować MQTT przez Home Assistant.') from exc
