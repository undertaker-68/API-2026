import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Iterator


@dataclass
class OrderState:
    posting_number: str
    ms_order_id: Optional[str]
    last_status: Optional[str]
    demand_created: int
    move_created: int
    forgotten: int
    last_seen_ts: Optional[int]   # unix ts
    missed_cycles: int


class StateStore:
    def __init__(self, path: str = "data/state.db"):
        Path("data").mkdir(exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.execute("""
        CREATE TABLE IF NOT EXISTS orders (
          posting_number TEXT PRIMARY KEY,
          ms_order_id TEXT,
          last_status TEXT,
          demand_created INTEGER DEFAULT 0,
          move_created INTEGER DEFAULT 0,
          forgotten INTEGER DEFAULT 0,
          last_seen_ts INTEGER,
          missed_cycles INTEGER DEFAULT 0
        )
        """)
        self._ensure_columns()
        self.conn.commit()

    def _ensure_columns(self) -> None:
        cur = self.conn.execute("PRAGMA table_info(orders)")
        cols = {row[1] for row in cur.fetchall()}
        if "last_seen_ts" not in cols:
            self.conn.execute("ALTER TABLE orders ADD COLUMN last_seen_ts INTEGER")
        if "missed_cycles" not in cols:
            self.conn.execute("ALTER TABLE orders ADD COLUMN missed_cycles INTEGER DEFAULT 0")

    def get(self, posting_number: str) -> OrderState:
        cur = self.conn.execute(
            """SELECT posting_number, ms_order_id, last_status, demand_created, move_created, forgotten,
                      last_seen_ts, missed_cycles
               FROM orders WHERE posting_number=?""",
            (posting_number,),
        )
        row = cur.fetchone()
        if not row:
            return OrderState(posting_number, None, None, 0, 0, 0, None, 0)
        return OrderState(*row)

    def upsert(self, s: OrderState) -> None:
        self.conn.execute("""
        INSERT INTO orders(posting_number, ms_order_id, last_status, demand_created, move_created, forgotten, last_seen_ts, missed_cycles)
        VALUES(?,?,?,?,?,?,?,?)
        ON CONFLICT(posting_number) DO UPDATE SET
          ms_order_id=excluded.ms_order_id,
          last_status=excluded.last_status,
          demand_created=excluded.demand_created,
          move_created=excluded.move_created,
          forgotten=excluded.forgotten,
          last_seen_ts=excluded.last_seen_ts,
          missed_cycles=excluded.missed_cycles
        """, (s.posting_number, s.ms_order_id, s.last_status, s.demand_created, s.move_created, s.forgotten, s.last_seen_ts, s.missed_cycles))
        self.conn.commit()

    def iter_active(self) -> Iterator[OrderState]:
        cur = self.conn.execute("""
          SELECT posting_number, ms_order_id, last_status, demand_created, move_created, forgotten, last_seen_ts, missed_cycles
          FROM orders
          WHERE forgotten=0
        """)
        for row in cur.fetchall():
            yield OrderState(*row)
