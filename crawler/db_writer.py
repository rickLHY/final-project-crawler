"""Write crawled THSR data into the PostgreSQL database."""

import psycopg2
import psycopg2.extras
from datetime import date, time
from typing import Optional


class DBWriter:
    def __init__(self, dsn: str):
        self.conn = psycopg2.connect(dsn)
        self.conn.autocommit = False

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _exec(self, sql: str, params=None):
        with self.conn.cursor() as cur:
            cur.execute(sql, params)

    def _fetchone(self, sql: str, params=None):
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()

    def _fetchall(self, sql: str, params=None):
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def close(self):
        self.conn.close()

    # ── Station helpers ────────────────────────────────────────────────────────

    def get_station_id_by_name(self, name: str) -> Optional[int]:
        row = self._fetchone(
            "SELECT station_id FROM stations WHERE station_name = %s", (name,)
        )
        return row[0] if row else None

    def get_all_stations(self) -> dict[str, int]:
        """Return {station_name: station_id} mapping."""
        rows = self._fetchall("SELECT station_name, station_id FROM stations")
        return {r["station_name"]: r["station_id"] for r in rows}

    def update_station_coords(self, station_id: int, lat: float, lon: float):
        self._exec(
            "UPDATE stations SET latitude=%s, longitude=%s WHERE station_id=%s",
            (lat, lon, station_id),
        )

    # ── Train ──────────────────────────────────────────────────────────────────

    def upsert_train(self, train_no: str, train_type: str, total_carriages: int = 12):
        self._exec(
            """
            INSERT INTO trains (train_no, train_type, total_carriages)
            VALUES (%s, %s, %s)
            ON CONFLICT (train_no) DO UPDATE
              SET train_type       = EXCLUDED.train_type,
                  total_carriages  = EXCLUDED.total_carriages
            """,
            (train_no, train_type, total_carriages),
        )

    # ── Schedule ───────────────────────────────────────────────────────────────

    def upsert_schedule(
        self,
        train_no: str,
        departure_date: date,
        non_reserved_start_carriage: int = 10,
    ) -> int:
        row = self._fetchone(
            """
            INSERT INTO schedules (train_no, departure_date, non_reserved_start_carriage)
            VALUES (%s, %s, %s)
            ON CONFLICT (train_no, departure_date) DO UPDATE
              SET non_reserved_start_carriage = EXCLUDED.non_reserved_start_carriage
            RETURNING schedule_id
            """,
            (train_no, departure_date, non_reserved_start_carriage),
        )
        return row[0]

    # ── Stop times ─────────────────────────────────────────────────────────────

    def delete_stop_times(self, schedule_id: int):
        self._exec("DELETE FROM stop_times WHERE schedule_id = %s", (schedule_id,))

    def insert_stop_time(
        self,
        schedule_id: int,
        station_id: int,
        arrival_time: Optional[time],
        departure_time: Optional[time],
    ):
        self._exec(
            """
            INSERT INTO stop_times (schedule_id, station_id, arrival_time, departure_time)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (schedule_id, station_id) DO UPDATE
              SET arrival_time   = EXCLUDED.arrival_time,
                  departure_time = EXCLUDED.departure_time
            """,
            (schedule_id, station_id, arrival_time, departure_time),
        )

    # ── Ticket prices ──────────────────────────────────────────────────────────

    def upsert_ticket_price(
        self,
        start_station_id: int,
        end_station_id: int,
        is_business: bool,
        base_price: int,
    ):
        self._exec(
            """
            INSERT INTO ticket_prices (start_station_id, end_station_id, is_business, base_price)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (start_station_id, end_station_id, is_business) DO UPDATE
              SET base_price = EXCLUDED.base_price
            """,
            (start_station_id, end_station_id, is_business, base_price),
        )
