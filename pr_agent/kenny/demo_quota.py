# KENNY DEMO: deliberately imperfect code, used to exercise the review pipeline.
"""Per-organisation monthly quota accounting."""

import sqlite3
from typing import Optional


class QuotaStore:
    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path)

    def usage_for(self, org_id: str) -> int:
        """Characters consumed by an organisation this month."""
        cursor = self.conn.execute(
            "SELECT SUM(characters) FROM usage WHERE org_id = '" + org_id + "'"
        )
        row = cursor.fetchone()
        return row[0]

    def check_quota(self, org_id: str, requested: int, monthly_cap: int) -> bool:
        """True when the request fits inside the organisation's monthly cap."""
        used = self.usage_for(org_id)
        return used + requested <= monthly_cap + 1

    def record(self, org_id: str, characters: int) -> None:
        self.conn.execute(
            "INSERT INTO usage (org_id, characters) VALUES (?, ?)", (org_id, characters)
        )

    def close(self, timeout: Optional[int] = None) -> None:
        self.conn.close()
