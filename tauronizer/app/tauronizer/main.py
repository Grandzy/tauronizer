"""FastAPI application exposed through Home Assistant ingress."""

from __future__ import annotations

import asyncio
from contextlib import suppress
import json
import logging
import math
import os
from contextlib import asynccontextmanager
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import APP_NAME, __version__
from .calc import ConsumptionSample, analyze
from .quality import consumption_coverage
from .forecast import dynamic_schedule
from .db import (
    create_tariff,
    delete_analysis,
    delete_tariff,
    duplicate_tariff,
    get_analysis,
    get_tariff,
    get_setting,
    set_setting,
    init_db,
    list_analyses,
    list_tariffs,
    restore_presets,
    save_analysis,
    update_tariff,
    utcnow,
)
from .ha_client import HAClient, HAError
from .models import AnalyzeRequest, TariffCreate, TariffUpdate, SensorSettings, ProsumerSettings
from .export_prices import ExportPriceCache
from .prosumer import ProsumerCalculation, paired_energy
from .sensors import SensorPublisher
from .kompas import KompasCache
from .tariffs import KOMPAS_ZONE_DESCRIPTIONS, PRESET_NOTE, TZ, TariffValidationError, compile_zones

MAX_RANGE_DAYS = 3660


def _configure_logging() -> None:
    level = os.getenv("LOG_LEVEL", "").upper()
    if not level:
        try:
            options = json.loads(Path("/data/options.json").read_text(encoding="utf-8"))
            level = str(options.get("log_level", "info")).upper()
        except (OSError, ValueError):
            level = "INFO"
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


_configure_logging()
_LOGGER = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    app.state.ha = HAClient()
    _LOGGER.info("Tauronizer %s started (supervisor mode: %s)", __version__, app.state.ha.is_supervisor)
    app.state.sensors = SensorPublisher(app.state.ha)
    app.state.kompas = KompasCache(app.state.sensors.wake)
    app.state.sensors.kompas = app.state.kompas
    app.state.export_prices = ExportPriceCache()
    price_task = asyncio.create_task(app.state.export_prices.run()) if os.getenv('EXPORT_PRICES_AUTO_SYNC', '1') != '0' else None
    publisher_task = asyncio.create_task(app.state.sensors.run())
    kompas_task = asyncio.create_task(app.state.kompas.run()) if os.getenv('KOMPAS_AUTO_SYNC', '1') != '0' else None
    try:
        yield
    finally:
        if price_task:
            price_task.cancel()
            with suppress(asyncio.CancelledError):
                await price_task
        await app.state.export_prices.close()
        if kompas_task:
            kompas_task.cancel()
            with suppress(asyncio.CancelledError):
                await kompas_task
        await app.state.kompas.close()
        publisher_task.cancel()
        with suppress(asyncio.CancelledError):
            await publisher_task
        await app.state.sensors.stop()
        await app.state.ha.close()


app = FastAPI(
    title=APP_NAME,
    version=__version__,
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    return response


@app.exception_handler(HAError)
async def _ha_error_handler(_request: Request, exc: HAError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(TariffValidationError)
async def _tariff_error_handler(_request: Request, exc: TariffValidationError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


def _ha(request: Request) -> HAClient:
    return request.app.state.ha


def _validated_config(payload: TariffCreate) -> dict[str, Any]:
    config = payload.config.model_dump(mode="json")
    compiled = compile_zones(config)
    by_id = {zone["id"]: zone for zone in config["zones"]}
    config["zones"] = [by_id[zone.id] for zone in compiled]
    for zone, rule in zip(config["zones"], compiled):
        zone["is_default"] = rule.is_default
        if rule.is_default:
            zone.update(days=list(range(7)), intervals=["00:00-24:00"],
                        months=None, exclude_holidays=False)
    return config


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(
        STATIC_DIR / "index.html",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/favicon.ico")
async def favicon() -> Response:
    return Response(status_code=204)


@app.get("/api/config")
async def config(request: Request) -> dict[str, Any]:
    ha = _ha(request)
    return {
        "app": APP_NAME,
        "version": __version__,
        "timezone": "Europe/Warsaw",
        "mode": "supervisor" if ha.is_supervisor else "standalone",
        "max_range_days": MAX_RANGE_DAYS,
        "disclaimer": PRESET_NOTE,
        "kompas_zone_descriptions": KOMPAS_ZONE_DESCRIPTIONS,
    }


@app.get("/api/entities")
async def entities(request: Request) -> dict[str, Any]:
    ha = _ha(request)
    return {"entities": await ha.get_energy_entities()}


# ---------------------------------------------------------------------------
# Tariffs
# ---------------------------------------------------------------------------


@app.get("/api/tariffs")
async def tariffs() -> dict[str, Any]:
    return {"tariffs": list_tariffs()}


@app.post("/api/tariffs", status_code=201)
async def tariff_create(payload: TariffCreate) -> dict[str, Any]:
    config = _validated_config(payload)
    return create_tariff(payload.name.strip(), payload.description.strip(), config)


@app.post("/api/tariffs/restore-presets")
async def tariff_restore_presets(request: Request) -> dict[str, int]:
    count = restore_presets()
    request.app.state.sensors.wake.set()
    return {"restored": count}


@app.put("/api/tariffs/{tariff_id}")
async def tariff_update(tariff_id: str, payload: TariffUpdate, request: Request) -> dict[str, Any]:
    config = _validated_config(payload)
    updated = update_tariff(
        tariff_id, payload.name.strip(), payload.description.strip(), config
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono taryfy.")
    request.app.state.sensors.wake.set()
    return updated


@app.post("/api/tariffs/{tariff_id}/duplicate", status_code=201)
async def tariff_duplicate(tariff_id: str) -> dict[str, Any]:
    duplicated = duplicate_tariff(tariff_id)
    if duplicated is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono taryfy.")
    return duplicated


@app.delete("/api/tariffs/{tariff_id}")
async def tariff_delete(tariff_id: str, request: Request) -> dict[str, bool]:
    if not delete_tariff(tariff_id):
        raise HTTPException(status_code=404, detail="Nie znaleziono taryfy.")
    request.app.state.sensors.wake.set()
    return {"deleted": True}


@app.get('/api/kompas')
async def kompas_status(request: Request) -> dict[str, Any]:
    return request.app.state.kompas.snapshot()


@app.post('/api/kompas/refresh')
async def kompas_refresh(request: Request) -> dict[str, Any]:
    request.app.state.kompas.wake.set()
    return request.app.state.kompas.snapshot()


@app.get('/api/sensors')
async def sensors_status(request: Request) -> dict[str, Any]:
    return request.app.state.sensors.snapshot()


@app.put('/api/sensors')
async def sensors_settings(payload: SensorSettings, request: Request) -> dict[str, Any]:
    if payload.tariff_id and get_tariff(payload.tariff_id) is None:
        raise HTTPException(status_code=404, detail='Nie znaleziono taryfy.')
    set_setting('sensor_tariff_id', payload.tariff_id or '')
    if payload.price_mode is not None:
        set_setting('sensor_price_mode', payload.price_mode)
    publisher = request.app.state.sensors
    await publisher.refresh()
    publisher.wake.set()
    return publisher.snapshot()


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


@app.get('/api/kompas/schedule')
async def kompas_schedule():
    selected = get_setting('sensor_tariff_id')
    current = get_tariff(selected) if selected else None
    tariff = current if current and current['config'].get('zone_source') == 'pse_kompas' else next(
        (t for t in list_tariffs() if t['config'].get('zone_source') == 'pse_kompas'), None)
    result = dynamic_schedule(tariff)
    result['is_current_tariff'] = bool(current and tariff and current['id'] == tariff['id'])
    return result


@app.get('/api/prosumer')
async def prosumer_settings_get(request: Request):
    saved = get_setting('prosumer_settings')
    settings = ProsumerSettings.model_validate_json(saved) if saved else ProsumerSettings()
    return {'settings': settings.model_dump(), 'prices': request.app.state.export_prices.snapshot()}


@app.put('/api/prosumer')
async def prosumer_settings_put(payload: ProsumerSettings):
    if payload.mode != 'off' and not payload.export_entity_id:
        raise HTTPException(400, 'Wybierz encję eksportu energii do sieci.')
    set_setting('prosumer_settings', payload.model_dump_json())
    return payload.model_dump()


@app.post('/api/prosumer/prices/refresh')
async def prosumer_prices_refresh(request: Request):
    request.app.state.export_prices.wake.set()
    return request.app.state.export_prices.snapshot()


@app.post("/api/analyze")
async def run_analysis(payload: AnalyzeRequest, request: Request) -> dict[str, Any]:
    as_of = datetime.now(TZ).date()
    if payload.end < payload.start:
        raise HTTPException(status_code=400, detail="Data końcowa jest wcześniejsza niż początkowa.")
    if payload.end > as_of:
        raise HTTPException(status_code=400, detail="Zakres nie może kończyć się w przyszłości.")
    days = (payload.end - payload.start).days + 1
    if days > MAX_RANGE_DAYS:
        raise HTTPException(
            status_code=400,
            detail=f"Zbyt długi zakres. Maksimum to {MAX_RANGE_DAYS} dni (około 10 lat).",
        )

    ha = _ha(request)
    entity = await ha.get_entity(payload.entity_id)
    attributes = entity.get("attributes") or {}
    entity_name = attributes.get("friendly_name") or payload.entity_id

    start_local = datetime.combine(payload.start, time(0, 0), tzinfo=TZ)
    end_local = datetime.combine(payload.end + timedelta(days=1), time(0, 0), tzinfo=TZ)
    start_utc = start_local.astimezone(timezone.utc)
    end_utc = end_local.astimezone(timezone.utc)

    samples, unit = await ha.get_statistics(payload.entity_id, start_utc, end_utc)
    in_range = [
        sample for sample in samples if start_utc <= sample.timestamp < end_utc
    ]
    if not in_range:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Brak statystyk długoterminowych dla encji {payload.entity_id} "
                "w wybranym zakresie. Upewnij się, że sensor ma atrybut "
                "state_class: total_increasing i że Home Assistant zbiera dla niego "
                "statystyki. Nowe encje pojawiają się w statystykach po pewnym czasie."
            ),
        )

    warnings: list[str] = []
    if unit.lower() != "kwh":
        warnings.append(f"Statystyki encji są w {unit} — przeliczono je na kWh.")

    negative_count = sum(1 for sample in in_range if sample.kwh < -1e-9)
    if negative_count:
        warnings.append(
            f"Pominięto {negative_count} ujemnych przyrostów (np. reset licznika)."
        )
    clean_by_hour = {}
    for sample in in_range:
        stamp = sample.timestamp.astimezone(timezone.utc)
        if (math.isfinite(sample.kwh) and sample.kwh >= 0
                and not (stamp.minute or stamp.second or stamp.microsecond)):
            clean_by_hour[stamp] = ConsumptionSample(timestamp=stamp, kwh=sample.kwh)
    clean_samples = sorted(clean_by_hour.values(), key=lambda sample: sample.timestamp)
    if not clean_samples:
        raise HTTPException(status_code=400, detail='Brak prawidłowych godzinowych statystyk zużycia w wybranym zakresie.')

    first = clean_samples[0].timestamp
    last = clean_samples[-1].timestamp
    if first - start_utc > timedelta(hours=36):
        warnings.append(
            "Statystyki zaczynają się dopiero od "
            f"{first.astimezone(TZ).strftime('%d.%m.%Y %H:%M')}."
        )
    if end_utc - last > timedelta(hours=48):
        warnings.append(
            "Ostatnie dane w statystykach pochodzą z "
            f"{last.astimezone(TZ).strftime('%d.%m.%Y %H:%M')}."
        )

    all_tariffs = list_tariffs()
    if payload.tariff_ids:
        wanted = set(payload.tariff_ids)
        selected = [tariff for tariff in all_tariffs if tariff["id"] in wanted]
        if not selected:
            raise HTTPException(
                status_code=400,
                detail="Żadna z wybranych taryf nie istnieje. Odśwież listę taryf.",
            )
    else:
        selected = all_tariffs

    if not selected:
        raise HTTPException(
            status_code=400,
            detail="Brak taryf do porównania. Dodaj taryfę lub przywróć presety.",
        )

    current_tariff_id = get_setting("sensor_tariff_id")
    current_tariff = next((t for t in all_tariffs if t["id"] == current_tariff_id), None)
    settings = payload.prosumer
    if settings is None:
        saved = get_setting('prosumer_settings')
        settings = ProsumerSettings.model_validate_json(saved) if saved else ProsumerSettings()
    prosumer_calculation = None
    prosumer_info = None
    if settings.mode != 'off':
        if not settings.export_entity_id or settings.export_entity_id == payload.entity_id:
            raise HTTPException(400, 'Wybierz dwie różne encje: pobór z sieci i eksport do sieci.')
        await ha.get_entity(settings.export_entity_id)
        exports, export_unit = await ha.get_statistics(settings.export_entity_id, start_utc, end_utc)
        exports = [s for s in exports if start_utc <= s.timestamp < end_utc]
        balanced_imports, balanced_exports = paired_energy(in_range, exports)
        if not balanced_imports:
            raise HTTPException(400, 'Brak wspólnych, prawidłowych godzin statystyk poboru i eksportu. Brak eksportu nie oznacza zera.')
        export_quality = consumption_coverage(exports, payload.start, payload.end)
        paired_quality = consumption_coverage(balanced_imports, payload.start, payload.end)
        if settings.mode in ('rcem', 'rce'):
            try:
                await request.app.state.export_prices.ensure(settings.mode, payload.start, payload.end)
            except Exception as exc:
                _LOGGER.warning('Export prices for analysis: %s', exc)
                warnings.append('Nie udało się uzupełnić cen PSE. Użyto lokalnej bazy; taryfy wymagające brakujących cen nie będą policzone.')
        prosumer_calculation = ProsumerCalculation(settings, balanced_imports, balanced_exports, payload.start, payload.end)
        raw_import_kwh = round(sum(s.kwh for s in clean_samples),3)
        clean_samples = balanced_imports
        warnings.append('Symulacja prosumenta: miesięczne rozliczenie, godzinowe bilansowanie poboru i eksportu. Stawki taryfy pozostają stałe w całym okresie; to szacunek, nie odtworzenie faktur historycznych.')
        if payload.start.day != 1 or payload.end != (payload.end.replace(day=28) + timedelta(days=4)).replace(day=1)-timedelta(days=1):
            warnings.append('Zakres obejmuje niepełny miesiąc. Saldo i depozyt tego miesiąca dotyczą tylko wybranego fragmentu.')
        if not settings.opening_balances:
            warnings.append('Nie podano salda początkowego — przyjęto 0. Wynik pomija środki lub opusty zgromadzone przed analizą.')
        if paired_quality['missing_hours']:
            warnings.append(f"Brakuje wspólnych danych dla {paired_quality['missing_hours']} godzin. Pominięto je w obu kierunkach; saldo i koszty są niepełnym szacunkiem.")
        if settings.mode == 'net_metering' and any(not b.zone_id for b in settings.opening_balances):
            warnings.append('Saldo początkowe bez przypisania do strefy potraktowano jako wspólną pulę. Przy wielu strefach wynik jest przybliżony; wybierz strefy salda z faktury dla dokładniejszej symulacji.')
        if settings.mode == 'rce':
            warnings.append('RCE: eksport godzinowy rozdzielono równo na cztery kwadranse. Ujemne ceny zastąpiono zerem. Kwota depozytu jest przybliżona.')
        prosumer_info = dict(settings=settings.model_dump(), export_unit=export_unit,
            export_quality=export_quality, paired_quality=paired_quality,
            export_kwh=round(sum(s.kwh for s in balanced_exports),3),
            raw_import_kwh=raw_import_kwh,
            incomplete=bool(paired_quality['missing_hours']), approximate_rce=settings.mode=='rce')
    result = analyze(selected, clean_samples, payload.start, payload.end, current_tariff=current_tariff,
                     prosumer_calculation=prosumer_calculation)
    if prosumer_info:
        result['prosumer'] = prosumer_info
        result['methodology'] += (' Prosument: ranking i wykres kosztów pokazują kwotę do zapłaty po rozliczeniu. '
            'Saldo końcowe nie jest odejmowane od rachunku i nie jest traktowane jako gotówka. '
            'Depozyt pokrywa tylko energię czynną z akcyzą i VAT, bez dystrybucji i opłat stałych. '
            'Depozyt z eksportu jest dostępny w kolejnym miesiącu; od lutego 2025 mnożnik 1,23. '
            'Najstarsze środki zużywane są najpierw, wygasają po 12 miesiącach od przypisania. '
            'W opustach najpierw rozliczane są te same strefy, potem strefy o najwyższej dystrybucji. '
            'Początkowe saldo kWh jest już po współczynniku opustu. Zwroty depozytu są pokazane osobno jako potencjalne, nie zmniejszają rachunku. '
            'Model miesięczny może różnić się od dawnych cykli rozliczenia 2/6/12 miesięcy; zmiana taryfy w trakcie okresu nie jest symulowana.')
    quality = consumption_coverage(in_range, payload.start, payload.end)
    result['data_quality'] = quality
    if quality['missing_hours']:
        warnings.append(f"Dostępne {str(quality['percent']).replace('.', ',')}% zakończonych godzin: {quality['received_hours']} z {quality['expected_hours']}. "
                        f"Brakuje {quality['missing_hours']} godzin. Koszty mogą być zaniżone, a najtańsza taryfa może się zmienić po uzupełnieniu danych.")
    if quality['invalid_samples']:
        warnings.append(f"Pominięto {quality['invalid_samples']} nieprawidłowych odczytów; nie potwierdzają one kompletności danych.")
    if quality['duplicate_samples']:
        warnings.append('Statystyki zawierają powtórzone godziny; uwzględniono ostatni prawidłowy odczyt dla każdej godziny.')
    result.update(
        {
            "entity_id": payload.entity_id,
            "entity_name": entity_name,
            "unit": unit,
            "warnings": warnings,
            "created_at": utcnow(),
        }
    )
    analysis_id = save_analysis(
        result, entity_id=payload.entity_id, entity_name=entity_name
    )
    result["id"] = analysis_id
    _LOGGER.info(
        "Analysis %s: %s, %s..%s, %.1f kWh, %d tariffs, cheapest=%s",
        analysis_id,
        payload.entity_id,
        payload.start,
        payload.end,
        result["total_kwh"],
        len(result["tariffs"]),
        result.get("cheapest_tariff_name"),
    )
    return result


@app.get("/api/analyses")
async def analyses(limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
    return {"analyses": list_analyses(limit)}


@app.get("/api/analyses/{analysis_id}")
async def analysis_detail(analysis_id: str) -> dict[str, Any]:
    record = get_analysis(analysis_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono analizy.")
    return record


@app.delete("/api/analyses/{analysis_id}")
async def analysis_delete(analysis_id: str) -> dict[str, bool]:
    if not delete_analysis(analysis_id):
        raise HTTPException(status_code=404, detail="Nie znaleziono analizy.")
    return {"deleted": True}
