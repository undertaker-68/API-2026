import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

@dataclass
class OrderState:
    posting_number: str
    ms_order_id: Optional[str]
    last_status: Optional[str]
    demand_created: int
    move_created: int
    forgotten: int

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
          forgotten INTEGER DEFAULT 0
        )
        """)
        self.conn.commit()

    def get(self, posting_number: str) -> OrderState:
        cur = self.conn.execute(
            "SELECT posting_number, ms_order_id, last_status, demand_created, move_created, forgotten FROM orders WHERE posting_number=?",
            (posting_number,),
        )
        row = cur.fetchone()
        if not row:
            return OrderState(posting_number, None, None, 0, 0, 0)
        return OrderState(*row)

    def upsert(self, s: OrderState) -> None:
        self.conn.execute("""
        INSERT INTO orders(posting_number, ms_order_id, last_status, demand_created, move_created, forgotten)
        VALUES(?,?,?,?,?,?)
        ON CONFLICT(posting_number) DO UPDATE SET
          ms_order_id=excluded.ms_order_id,
          last_status=excluded.last_status,
          demand_created=excluded.demand_created,
          move_created=excluded.move_created,
          forgotten=excluded.forgotten
        """, (s.posting_number, s.ms_order_id, s.last_status, s.demand_created, s.move_created, s.forgotten))
        self.conn.commit()
