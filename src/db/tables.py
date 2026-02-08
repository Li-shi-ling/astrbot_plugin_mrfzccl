from datetime import datetime
from typing import Optional
from sqlmodel import Field, SQLModel


class UserQnAStats(SQLModel, table=True):
    """用户问答统计表 - 记录用户的答题统计数据"""

    __tablename__ = "user_qna_stats"
    __table_args__ = {"extend_existing": True}

    # 主键ID - 自增主键，每条记录的唯一标识
    id: Optional[int] = Field(default=None, primary_key=True, description="主键ID，自增唯一标识")

    # 用户ID - 用户的唯一标识符，用于关联用户
    user_id: str = Field(index=True, description="用户ID，用户的唯一标识符")

    # 用户名称 - 用户的显示名称，用于展示
    user_name: str = Field(index=True, description="用户名称，用户的显示名称")

    # 答对次数 - 用户回答正确的问题数量
    correct_count: int = Field(default=0, description="答对次数，用户回答正确的问题数量")

    # 答错次数 - 用户回答错误的问题数量
    wrong_count: int = Field(default=0, description="答错次数，用户回答错误的问题数量")

    # 提示次数 - 用户使用提示的次数
    tip_count: int = Field(default=0, description="提示次数，用户使用提示的次数")

    # 创建时间 - 记录首次创建的时间，不可修改
    created_at: datetime = Field(
        default_factory=datetime.now,
        description="创建时间，记录首次创建的时间，自动生成且不可修改"
    )

    # 更新时间 - 记录最后一次更新的时间，每次修改记录时自动更新
    updated_at: datetime = Field(
        default_factory=datetime.now,
        description="更新时间，记录最后一次更新的时间，每次修改记录时自动更新"
    )