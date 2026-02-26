import aiosqlite
from typing import Optional
from config import config

class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._connection: Optional[aiosqlite.Connection] = None

    async def connect(self):
        self._connection = await aiosqlite.connect(self.db_path)
        await self._init_tables()

    async def close(self):
        if self._connection:
            await self._connection.close()

    async def _init_tables(self):
        # Исправлено: DEFAULT значения прописаны напрямую, не через ?
        await self._connection.execute(f"""
            CREATE TABLE IF NOT EXISTS tracked_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_user_id BIGINT NOT NULL,
                steamid64 TEXT NOT NULL,
                appid INTEGER DEFAULT {config.DEFAULT_APPID},
                contextid INTEGER DEFAULT {config.DEFAULT_CONTEXTID},
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(tg_user_id, steamid64, appid)
            )
        """)

        await self._connection.execute(f"""
            CREATE TABLE IF NOT EXISTS inventory_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                steamid64 TEXT NOT NULL,
                appid INTEGER DEFAULT {config.DEFAULT_APPID},
                item_hash TEXT NOT NULL,
                detected_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(steamid64, appid, item_hash)
            )
        """)

        await self._connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_tracked_steamid ON tracked_users(steamid64, appid)"
        )
        await self._connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_snapshot_steamid ON inventory_snapshots(steamid64, appid)"
        )
        await self._connection.commit()

    async def add_tracked_user(self, tg_user_id: int, steamid64: str,
                              appid: int = None, contextid: int = None) -> bool:
        appid = appid or config.DEFAULT_APPID
        contextid = contextid or config.DEFAULT_CONTEXTID
        try:
            await self._connection.execute(
                """INSERT OR IGNORE INTO tracked_users 
                   (tg_user_id, steamid64, appid, contextid) 
                   VALUES (?, ?, ?, ?)""",
                (tg_user_id, steamid64, appid, contextid)
            )
            await self._connection.commit()
            return True
        except Exception as e:
            print(f"DB Error (add_tracked_user): {e}")
            return False

    async def remove_tracked_user(self, tg_user_id: int, steamid64: str,
                                 appid: int = None) -> bool:
        appid = appid or config.DEFAULT_APPID
        try:
            await self._connection.execute(
                "DELETE FROM tracked_users WHERE tg_user_id = ? AND steamid64 = ? AND appid = ?",
                (tg_user_id, steamid64, appid)
            )
            await self._connection.commit()
            return True
        except Exception as e:
            print(f"DB Error (remove_tracked_user): {e}")
            return False

    async def get_tracked_users(self, tg_user_id: Optional[int] = None,
                               steamid64: Optional[str] = None):
        query = "SELECT tg_user_id, steamid64, appid, contextid FROM tracked_users WHERE 1=1"
        params = []
        if tg_user_id:
            query += " AND tg_user_id = ?"
            params.append(tg_user_id)
        if steamid64:
            query += " AND steamid64 = ?"
            params.append(steamid64)

        async with self._connection.execute(query, params) as cursor:
            return await cursor.fetchall()

    async def get_item_hashes(self, steamid64: str, appid: int) -> set[str]:
        async with self._connection.execute(
            "SELECT item_hash FROM inventory_snapshots WHERE steamid64 = ? AND appid = ?",
            (steamid64, appid)
        ) as cursor:
            return {row[0] for row in await cursor.fetchall()}

    async def save_item_hashes(self, steamid64: str, appid: int, hashes: set[str]):
        for h in hashes:
            await self._connection.execute(
                "INSERT OR IGNORE INTO inventory_snapshots (steamid64, appid, item_hash) VALUES (?, ?, ?)",
                (steamid64, appid, h)
            )
        await self._connection.commit()

    async def cleanup_old_snapshots(self, days: int = 30):
        await self._connection.execute("""
            DELETE FROM inventory_snapshots 
            WHERE steamid64 NOT IN (SELECT DISTINCT steamid64 FROM tracked_users)
            OR detected_at < datetime('now', ?)
        """, (f"-{days} days",))
        await self._connection.commit()

db = Database(config.DATABASE_PATH)