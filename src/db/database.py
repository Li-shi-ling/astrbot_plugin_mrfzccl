import asyncio
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel


class DBManager:
    """数据库管理器，负责异步连接和会话管理"""

    def __init__(self, db_path: str):
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)

        self.db_url = f"sqlite+aiosqlite:///{db_path}"

        # 创建异步引擎
        self.engine = create_async_engine(
            self.db_url,
            echo=False,
            pool_pre_ping=True,
            pool_recycle=3600,
            # pool_size=5,
            # max_overflow=5,
        )

        # 创建会话工厂
        self.async_session = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        self.async_session_factory = self.async_session
        self._init_lock = asyncio.Lock()
        self._initialized = False

    async def init_db(self):
        if self._initialized:
            return

        async with self._init_lock:
            if self._initialized:
                return

            await self._init_db_once()
            self._initialized = True

    async def _init_db_once(self):
        """初始化数据库，创建所有定义的表"""
        from . import tables  # noqa: F401

        async with self.engine.begin() as conn:
            try:
                await conn.run_sync(SQLModel.metadata.create_all)
            except OperationalError as e:
                if "already exists" not in str(e):
                    raise

        async with self.engine.begin() as conn:
            try:
                await conn.execute(
                    text(
                        "ALTER TABLE match ADD COLUMN question_limit INTEGER DEFAULT 0"
                    )
                )
            except OperationalError:
                pass
            try:
                await conn.execute(
                    text("ALTER TABLE match ADD COLUMN time_limit INTEGER DEFAULT 0")
                )
            except OperationalError:
                pass
            try:
                await conn.execute(
                    text("ALTER TABLE match ADD COLUMN started_at TIMESTAMP")
                )
            except OperationalError:
                pass
            try:
                await conn.execute(
                    text(
                        "ALTER TABLE match_participant ADD COLUMN wrong_count INTEGER DEFAULT 0"
                    )
                )
            except OperationalError:
                pass
            try:
                await conn.execute(
                    text(
                        "ALTER TABLE match_participant ADD COLUMN score REAL DEFAULT 0.0"
                    )
                )
            except OperationalError:
                pass
            try:
                await conn.execute(
                    text(
                        "ALTER TABLE match_honor ADD COLUMN wrong_count INTEGER DEFAULT 0"
                    )
                )
            except OperationalError:
                pass
            try:
                await conn.execute(
                    text("ALTER TABLE match_honor ADD COLUMN score REAL DEFAULT 0.0")
                )
            except OperationalError:
                pass

        # SQLite 优化 PRAGMA
        async with self.engine.connect() as conn:
            await conn.execute(text("PRAGMA journal_mode=WAL"))
            await conn.execute(text("PRAGMA synchronous=NORMAL"))
            await conn.execute(text("PRAGMA cache_size=-20000"))
            await conn.execute(text("PRAGMA temp_store=MEMORY"))
            await conn.execute(text("PRAGMA mmap_size=134217728"))
            await conn.execute(text("PRAGMA optimize"))
            await conn.commit()

        await self.validate_db()

    async def validate_db(self):
        """校验数据库表和字段是否完整"""
        from . import tables  # noqa: F401

        expected_tables = {
            table_name: set(table.columns.keys())
            for table_name, table in SQLModel.metadata.tables.items()
        }

        async with self.engine.connect() as conn:
            result = await conn.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'table'")
            )
            existing_tables = {str(row[0]) for row in result.fetchall()}

            missing_tables = sorted(
                table_name
                for table_name in expected_tables
                if table_name not in existing_tables
            )
            if missing_tables:
                raise RuntimeError(f"数据库缺少数据表: {', '.join(missing_tables)}")

            missing_columns: dict[str, list[str]] = {}
            for table_name, expected_columns in expected_tables.items():
                pragma_result = await conn.execute(
                    text(f'PRAGMA table_info("{table_name}")')
                )
                existing_columns = {
                    str(row[1]) for row in pragma_result.fetchall() if len(row) > 1
                }
                table_missing_columns = sorted(expected_columns - existing_columns)
                if table_missing_columns:
                    missing_columns[table_name] = table_missing_columns

            if missing_columns:
                missing_parts = [
                    f"{table_name} 缺少字段: {', '.join(columns)}"
                    for table_name, columns in missing_columns.items()
                ]
                raise RuntimeError("数据库结构不完整: " + "; ".join(missing_parts))

    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """异步获取数据库会话的上下文管理器"""
        session = self.async_session_factory()
        try:
            async with session.begin():
                yield session
        finally:
            await session.close()
