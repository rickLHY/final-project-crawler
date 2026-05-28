"""
THSR Crawler — fetch schedules, stop times and ticket prices from TDX API
and write into the PostgreSQL database.

Usage:
    python main.py                   # crawl today + next CRAWL_DAYS days
    python main.py --date 2026-06-01 # crawl a specific date only
    python main.py --prices-only     # only update ticket prices
    python main.py --general         # use GeneralTimetable (date-independent)

TDX registration: https://tdx.transportdata.tw
"""

import argparse
import os
import sys
from datetime import date, timedelta

from dotenv import load_dotenv

load_dotenv()

from crawler.tdx_client import TDXClient
from crawler.db_writer import DBWriter
from crawler.parser import (
    TDX_STATION_ID_TO_NAME,
    parse_daily_timetable,
    parse_general_timetable,
    parse_od_fares,
)


def get_env(key: str, required: bool = True) -> str:
    value = os.getenv(key, "")
    if required and not value:
        print(f"[ERROR] Missing environment variable: {key}")
        print(f"        Copy .env.example → .env and fill in your credentials.")
        sys.exit(1)
    return value


def build_station_map(db: DBWriter) -> dict[str, int]:
    """Build {tdx_station_id: db_station_id} from the DB's stations table."""
    name_to_id = db.get_all_stations()
    mapping: dict[str, int] = {}
    for tdx_id, zh_name in TDX_STATION_ID_TO_NAME.items():
        if zh_name in name_to_id:
            mapping[tdx_id] = name_to_id[zh_name]
        else:
            print(f"  [WARN] Station not found in DB: {zh_name} (TDX ID {tdx_id})")
    return mapping


# ── Prices ─────────────────────────────────────────────────────────────────────

def crawl_prices(tdx: TDXClient, db: DBWriter, station_map: dict[str, int]):
    print("[*] Fetching OD fares from TDX …")
    try:
        raw = tdx.get_od_fares()
        fares = parse_od_fares(raw)
    except Exception as exc:
        print(f"  [WARN] TDX OD fare fetch failed: {exc}")
        print("  [WARN] Skipping price update.")
        return

    inserted = skipped = 0
    for fare in fares:
        start_id = station_map.get(fare["start_tdx_id"])
        end_id   = station_map.get(fare["end_tdx_id"])
        if not start_id or not end_id:
            skipped += 1
            continue
        db.upsert_ticket_price(start_id, end_id, False, fare["standard"])
        db.upsert_ticket_price(start_id, end_id, True,  fare["business"])
        # Also insert reverse direction
        db.upsert_ticket_price(end_id, start_id, False, fare["standard"])
        db.upsert_ticket_price(end_id, start_id, True,  fare["business"])
        inserted += 2

    db.commit()
    print(f"  -> Upserted {inserted} price records ({skipped} skipped — unknown station).")


# ── Schedules ──────────────────────────────────────────────────────────────────

def crawl_date(
    tdx: TDXClient,
    db: DBWriter,
    station_map: dict[str, int],
    target_date: date,
):
    date_str = target_date.strftime("%Y-%m-%d")
    print(f"[*] Fetching timetable for {date_str} …")
    try:
        raw = tdx.get_timetable(date_str)
        trains = parse_daily_timetable(raw)
    except Exception as exc:
        print(f"  [ERROR] Failed to fetch timetable: {exc}")
        return

    print(f"  -> {len(trains)} trains returned from TDX.")

    saved = 0
    for train in trains:
        train_no   = train["train_no"]
        train_type = train["train_type"]

        # Only keep trains that stop at at least 2 of our stations
        valid_stops = [
            s for s in train["stops"]
            if s["tdx_station_id"] in station_map
        ]
        if len(valid_stops) < 2:
            continue

        db.upsert_train(train_no, train_type)
        schedule_id = db.upsert_schedule(train_no, target_date)
        db.delete_stop_times(schedule_id)

        for stop in valid_stops:
            db.insert_stop_time(
                schedule_id,
                station_map[stop["tdx_station_id"]],
                stop["arrival"],
                stop["departure"],
            )
        saved += 1

    db.commit()
    print(f"  -> Saved {saved} train schedules for {date_str}.")


def crawl_general(tdx: TDXClient, db: DBWriter, station_map: dict[str, int], target_date: date):
    print("[*] Fetching GeneralTimetable (date-independent) …")
    try:
        raw = tdx.get_general_timetable()
        trains = parse_general_timetable(raw)
    except Exception as exc:
        print(f"  [ERROR] Failed to fetch general timetable: {exc}")
        return

    print(f"  -> {len(trains)} trains returned from TDX.")
    saved = 0
    for train in trains:
        valid_stops = [
            s for s in train["stops"]
            if s["tdx_station_id"] in station_map
        ]
        if len(valid_stops) < 2:
            continue

        db.upsert_train(train["train_no"], train["train_type"])
        schedule_id = db.upsert_schedule(train["train_no"], target_date)
        db.delete_stop_times(schedule_id)

        for stop in valid_stops:
            db.insert_stop_time(
                schedule_id,
                station_map[stop["tdx_station_id"]],
                stop["arrival"],
                stop["departure"],
            )
        saved += 1

    db.commit()
    print(f"  -> Saved {saved} schedules (as date {target_date}).")


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="THSR TDX crawler")
    parser.add_argument("--date",        help="Specific date to crawl (YYYY-MM-DD)")
    parser.add_argument("--prices-only", action="store_true", help="Only update ticket prices")
    parser.add_argument("--general",     action="store_true", help="Use GeneralTimetable instead of DailyTimetable")
    args = parser.parse_args()

    client_id     = get_env("TDX_CLIENT_ID")
    client_secret = get_env("TDX_CLIENT_SECRET")
    database_url  = get_env("DATABASE_URL")
    crawl_days    = int(os.getenv("CRAWL_DAYS", "7"))

    tdx = TDXClient(client_id, client_secret)
    db  = DBWriter(database_url)

    try:
        station_map = build_station_map(db)
        print(f"[*] Station map loaded: {len(station_map)} stations matched.")

        if not args.prices_only:
            if args.general:
                target = date.fromisoformat(args.date) if args.date else date.today()
                crawl_general(tdx, db, station_map, target)
            elif args.date:
                crawl_date(tdx, db, station_map, date.fromisoformat(args.date))
            else:
                for i in range(crawl_days):
                    crawl_date(tdx, db, station_map, date.today() + timedelta(days=i))

        crawl_prices(tdx, db, station_map)

    except Exception as exc:
        db.rollback()
        print(f"[FATAL] {exc}")
        raise
    finally:
        db.close()

    print("\n[✓] Crawl complete.")


if __name__ == "__main__":
    main()
