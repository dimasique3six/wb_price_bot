"""
Модуль работы с базой данных SQLite.
"""

import sqlite3
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

DB_PATH = "wb_tracker.db"


class Database:
    def __init__(self):
        self.path = DB_PATH

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def init(self):
        """Создаёт таблицы при первом запуске."""
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS trackings (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id     INTEGER NOT NULL,
                    article     INTEGER NOT NULL,
                    name        TEXT    NOT NULL,
                    last_price  INTEGER NOT NULL DEFAULT 0,
                    updated_at  TEXT    NOT NULL,
                    UNIQUE(user_id, article)
                );

                CREATE TABLE IF NOT EXISTS price_history (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id     INTEGER NOT NULL,
                    article     INTEGER NOT NULL,
                    old_price   INTEGER NOT NULL,
                    new_price   INTEGER NOT NULL,
                    change_pct  REAL    NOT NULL,
                    recorded_at TEXT    NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_trackings_user
                    ON trackings(user_id);

                CREATE INDEX IF NOT EXISTS idx_history_article
                    ON price_history(user_id, article);
            """)
        logger.info("База данных инициализирована.")

    def add_tracking(self, user_id: int, article: int, name: str, price: int) -> bool:
        """Добавляет товар в отслеживание. Возвращает True если добавлен, False если уже есть."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        try:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO trackings (user_id, article, name, last_price, updated_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (user_id, article, name, price, now),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def remove_tracking(self, user_id: int, article: int) -> bool:
        """Удаляет товар из отслеживания. Возвращает True если удалён."""
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM trackings WHERE user_id = ? AND article = ?",
                (user_id, article),
            )
            return cur.rowcount > 0

    def get_user_trackings(self, user_id: int) -> list[dict]:
        """Возвращает все товары пользователя."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM trackings WHERE user_id = ? ORDER BY id",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_all_users(self) -> list[int]:
        """Возвращает список всех user_id у которых есть отслеживания."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT user_id FROM trackings"
            ).fetchall()
        return [row["user_id"] for row in rows]

    def update_price(self, user_id: int, article: int, price: int):
        """Обновляет последнюю известную цену товара."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        with self._conn() as conn:
            conn.execute(
                """UPDATE trackings SET last_price = ?, updated_at = ?
                   WHERE user_id = ? AND article = ?""",
                (price, now, user_id, article),
            )

    def add_price_history(
        self,
        user_id: int,
        article: int,
        old_price: int,
        new_price: int,
        change_pct: float,
    ):
        """Сохраняет запись об изменении цены."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO price_history
                       (user_id, article, old_price, new_price, change_pct, recorded_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (user_id, article, old_price, new_price, change_pct, now),
            )
