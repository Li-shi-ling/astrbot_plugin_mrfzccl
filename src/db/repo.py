from datetime import datetime
from typing import List, Optional, Tuple
from sqlalchemy import desc, func, select, update, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from sqlalchemy.engine import CursorResult

from .tables import UserQnAStats
from .database import DBManager


class UserQnARepo:
    """用户问答统计仓库，封装所有的数据库交互逻辑"""

    def __init__(self, db_manager: DBManager):
        self.db = db_manager

    # 获取或者创建用户数据
    async def get_or_create_user_stats(self, session: AsyncSession, user_id: str, user_name: str = "") -> UserQnAStats:
        """并发安全的 get_or_create 用户统计记录"""
        stmt = select(UserQnAStats).where(
            UserQnAStats.user_id == user_id
        )

        result = await session.execute(stmt)
        record = result.scalar_one_or_none()

        if record:
            # 如果用户名称有变化，更新用户名称
            if user_name and record.user_name != user_name:
                record.user_name = user_name
                record.updated_at = datetime.now()
            return record

        # 创建新记录
        record = UserQnAStats(
            user_id=user_id,
            user_name=user_name or f"用户_{user_id}",
            correct_count=0,
            wrong_count=0,
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        session.add(record)

        try:
            await session.flush()
            return record
        except IntegrityError:
            # 并发下被其他事务插入，重新读取
            result = await session.execute(stmt)
            return result.scalar_one()

    # 增加答题正确数量
    async def increment_correct_count(self, user_id: str, user_name: str = "", increment: int = 1) -> bool:
        """增加用户答对次数（原子操作）"""
        async with self.db.get_session() as session:
            # 先尝试更新现有记录
            stmt = (
                update(UserQnAStats)
                .where(UserQnAStats.user_id == user_id)
                .values(
                    correct_count=UserQnAStats.correct_count + increment,
                    updated_at=datetime.now()
                )
            )

            result: CursorResult = await session.execute(stmt)

            if result.rowcount == 0:
                # 记录不存在，创建新记录
                record = await self.get_or_create_user_stats(session, user_id, user_name)
                record.correct_count += increment
                record.updated_at = datetime.now()
                await session.commit()
                return True

            # 如果提供了user_name，检查是否需要更新
            if user_name:
                user_stmt = select(UserQnAStats).where(UserQnAStats.user_id == user_id)
                user_result = await session.execute(user_stmt)
                user_record = user_result.scalar_one()
                if user_record.user_name != user_name:
                    user_record.user_name = user_name
                    user_record.updated_at = datetime.now()

            return True

    # 增加答题错误数量
    async def increment_wrong_count(self, user_id: str, user_name: str = "", increment: int = 1) -> bool:
        """增加用户答错次数（原子操作）"""
        async with self.db.get_session() as session:
            stmt = (
                update(UserQnAStats)
                .where(UserQnAStats.user_id == user_id)
                .values(
                    wrong_count=UserQnAStats.wrong_count + increment,
                    updated_at=datetime.now()
                )
            )

            result: CursorResult = await session.execute(stmt)

            if result.rowcount == 0:
                # 记录不存在，创建新记录
                record = await self.get_or_create_user_stats(session, user_id, user_name)
                record.wrong_count += increment
                record.updated_at = datetime.now()
                await session.commit()
                return True

            # 如果提供了user_name，检查是否需要更新
            if user_name:
                user_stmt = select(UserQnAStats).where(UserQnAStats.user_id == user_id)
                user_result = await session.execute(user_stmt)
                user_record = user_result.scalar_one()
                if user_record.user_name != user_name:
                    user_record.user_name = user_name
                    user_record.updated_at = datetime.now()

            return True

    # 增加答题正确和答题错误数量
    async def increment_both_counts(self, user_id: str, user_name: str = "",correct_increment: int = 1, wrong_increment: int = 1) -> bool:
        """同时增加用户答对和答错次数（原子操作）"""
        async with self.db.get_session() as session:
            # 先尝试更新现有记录
            stmt = (
                update(UserQnAStats)
                .where(UserQnAStats.user_id == user_id)
                .values(
                    correct_count=UserQnAStats.correct_count + correct_increment,
                    wrong_count=UserQnAStats.wrong_count + wrong_increment,
                    updated_at=datetime.now()
                )
            )

            result: CursorResult = await session.execute(stmt)

            if result.rowcount == 0:
                # 记录不存在，创建新记录
                record = await self.get_or_create_user_stats(session, user_id, user_name)
                record.correct_count += correct_increment
                record.wrong_count += wrong_increment
                record.updated_at = datetime.now()
                await session.commit()
                return True

            # 如果提供了user_name，检查是否需要更新
            if user_name:
                user_stmt = select(UserQnAStats).where(UserQnAStats.user_id == user_id)
                user_result = await session.execute(user_stmt)
                user_record = user_result.scalar_one()
                if user_record.user_name != user_name:
                    user_record.user_name = user_name
                    user_record.updated_at = datetime.now()

            return True

    # 按ID查找用户并获取当前排名
    async def get_user_stats_with_rank(self, user_id: str) -> Tuple[Optional[UserQnAStats], Optional[int], int]:
        """
        按ID查找用户并获取当前排名

        返回:
            (用户统计记录, 排名(从1开始), 总用户数)
            如果用户不存在，返回(None, None, 总用户数)
        """
        async with self.db.get_session() as session:
            # 获取总用户数
            total_stmt = select(func.count()).select_from(UserQnAStats)
            total_result = await session.execute(total_stmt)
            total_users = total_result.scalar_one() or 0

            if total_users == 0:
                return None, None, 0

            # 获取用户记录
            user_stmt = select(UserQnAStats).where(UserQnAStats.user_id == user_id)
            user_result = await session.execute(user_stmt)
            user_record = user_result.scalar_one_or_none()

            if not user_record:
                return None, None, total_users

            # 计算排名: correct_count 越高排名越高
            # 使用窗口函数或子查询计算排名
            rank_stmt = select(
                func.count().label('rank')
            ).where(
                and_(
                    UserQnAStats.correct_count > user_record.correct_count,
                    UserQnAStats.user_id != user_id
                )
            )
            rank_result = await session.execute(rank_stmt)
            # 排名从1开始
            rank = (rank_result.scalar_one() or 0) + 1

            return user_record, rank, total_users

    # 按照正确的题目数量从大到小排序，返回前N个用户
    async def get_top_users(self, limit: int = 10) -> List[UserQnAStats]:
        """
        按照正确的题目数量从大到小排序，返回前N个用户

        参数:
            limit: 返回的用户数量

        返回:
            排名前N的用户列表
        """
        async with self.db.get_session() as session:
            stmt = (
                select(UserQnAStats)
                .order_by(desc(UserQnAStats.correct_count), UserQnAStats.updated_at)
                .limit(limit)
            )

            result = await session.execute(stmt)
            return list(result.scalars().all())

    # 创建或更新用户统计记录（完整记录）
    async def create_or_update_user(self, user_id: str, user_name: str, correct_count: int = 0, wrong_count: int = 0) -> UserQnAStats:
        """创建或更新用户统计记录（完整记录）"""
        async with self.db.get_session() as session:
            record = await self.get_or_create_user_stats(session, user_id, user_name)

            # 更新数据
            record.correct_count = correct_count
            record.wrong_count = wrong_count
            record.updated_at = datetime.now()

            return record

    # 批量创建或更新用户统计记录
    async def batch_create_or_update_users(self, users_data: List[dict]) -> int:
        """
        批量创建或更新用户统计记录

        参数:
            users_data: 用户数据列表，每个元素为字典，包含:
                - user_id: 用户ID
                - user_name: 用户名
                - correct_count: 答对数量
                - wrong_count: 答错数量

        返回:
            成功处理的数量
        """
        if not users_data:
            return 0

        processed_count = 0
        async with self.db.get_session() as session:
            for user_data in users_data:
                try:
                    record = await self.get_or_create_user_stats(
                        session,
                        user_data['user_id'],
                        user_data.get('user_name', '')
                    )

                    # 更新数据（可以设置为增量或覆盖，这里用增量）
                    if 'correct_count' in user_data:
                        record.correct_count += user_data['correct_count']
                    if 'wrong_count' in user_data:
                        record.wrong_count += user_data['wrong_count']

                    record.updated_at = datetime.now()
                    processed_count += 1

                except Exception as e:
                    # 记录错误但继续处理其他用户
                    print(f"处理用户 {user_data.get('user_id')} 时出错: {e}")
                    continue

            await session.commit()

        return processed_count

    # 分页获取用户排名
    async def get_user_rankings_page(self, page: int = 1, page_size: int = 20) -> Tuple[List[UserQnAStats], int]:
        """
        分页获取用户排名

        参数:
            page: 页码（从1开始）
            page_size: 每页数量

        返回:
            (当前页的用户列表, 总用户数)
        """
        async with self.db.get_session() as session:
            # 获取总用户数
            total_stmt = select(func.count()).select_from(UserQnAStats)
            total_result = await session.execute(total_stmt)
            total_users = total_result.scalar_one() or 0

            # 计算偏移量
            offset = (page - 1) * page_size

            # 获取分页数据
            stmt = (
                select(UserQnAStats)
                .order_by(desc(UserQnAStats.correct_count), UserQnAStats.updated_at)
                .offset(offset)
                .limit(page_size)
            )

            result = await session.execute(stmt)
            users = list(result.scalars().all())

            return users, total_users

    # 根据用户名关键词搜索用户
    async def search_users_by_name(self, name_keyword: str, limit: int = 10) -> List[UserQnAStats]:
        """
        根据用户名关键词搜索用户

        参数:
            name_keyword: 用户名关键词
            limit: 返回的最大数量

        返回:
            匹配的用户列表，按正确数量排序
        """
        async with self.db.get_session() as session:
            stmt = (
                select(UserQnAStats)
                .where(UserQnAStats.user_name.contains(name_keyword))
                .order_by(desc(UserQnAStats.correct_count), UserQnAStats.updated_at)
                .limit(limit)
            )

            result = await session.execute(stmt)
            return list(result.scalars().all())

    # 获取总用户数量
    async def get_user_total_count(self) -> int:
        """获取总用户数量"""
        async with self.db.get_session() as session:
            stmt = select(func.count()).select_from(UserQnAStats)
            result = await session.execute(stmt)
            return result.scalar_one() or 0

    # 删除用户统计记录
    async def delete_user_stats(self, user_id: str) -> bool:
        """删除用户统计记录"""
        async with self.db.get_session() as session:
            stmt = select(UserQnAStats).where(UserQnAStats.user_id == user_id)
            result = await session.execute(stmt)
            record = result.scalar_one_or_none()

            if record:
                await session.delete(record)
                return True
            return False

    # 批量获取多个用户的统计信息
    async def get_user_stats_by_ids(self, user_ids: List[str]) -> List[UserQnAStats]:
        """批量获取多个用户的统计信息"""
        if not user_ids:
            return []

        async with self.db.get_session() as session:
            stmt = select(UserQnAStats).where(UserQnAStats.user_id.in_(user_ids))
            result = await session.execute(stmt)
            return list(result.scalars().all())
