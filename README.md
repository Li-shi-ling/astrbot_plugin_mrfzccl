# 明日方舟猜猜乐（Mrfzccl）

AstrBot 插件：遮挡干员立绘猜名字；支持排行榜、名片、比赛模式。

## 命令

### 游戏

| 命令 | 说明 | 示例 |
|---|---|---|
| `/fc` | 开始一局（私聊=个人；群聊=群内同一题） | `/fc` |
| `/fcc 干员名` | 猜测干员名称 | `/fcc 能天使` |
| `/fct` | 下一条提示 | `/fct` |
| `/fcw` | 一次性三条提示 | `/fcw` |
| `/fce` | 强制结束并显示答案 | `/fce` |

### 统计（`/ccl`）

| 命令 | 说明 |
|---|---|
| `/ccl 排行榜` | 正确量排行榜 |
| `/ccl 错误排行榜` | 错误量排行榜 |
| `/ccl 提示排行榜` | 提示使用排行榜 |
| `/ccl 名片 [用户ID]` | 用户名片（不填=自己） |

注：`require_admin=true` 时，排行榜仅管理员可用。

### 比赛（群聊，仅管理员）

| 命令 | 说明 | 示例 |
|---|---|---|
| `/ccl 比赛帮助` | 查看比赛命令 | `/ccl 比赛帮助` |
| `/ccl 比赛创建 [名称] [题目限制] [时间限制(分钟)]` | 创建比赛（0=不限制） | `/ccl 比赛创建 春节赛 20 30` |
| `/ccl 比赛开始` | 开始比赛并发送第一题 | `/ccl 比赛开始` |
| `/ccl 比赛结束` | 结束比赛并结算荣誉/排行 | `/ccl 比赛结束` |
| `/ccl 比赛排行` | 查看当前比赛排行 | `/ccl 比赛排行` |
| `/ccl 清除数据 [user_id]` | 清除指定用户的比赛数据 | `/ccl 清除数据 123456` |
| `/ccl 清除荣誉 [user_id]` | 清除指定用户的比赛荣誉 | `/ccl 清除荣誉 123456` |
| `/ccl 清除所有数据` | 清除所有用户的比赛数据 | `/ccl 清除所有数据` |
| `/ccl 清除所有荣誉` | 清除所有用户的比赛荣誉 | `/ccl 清除所有荣誉` |
| `/ccl 授予荣誉 [user_id] [名次] [比赛名称] [答对数量]` | 授予用户比赛荣誉 | `/ccl 授予荣誉 123456 1 春节赛 20` |

## 比赛机制

- 自动出题：`/ccl 比赛开始` 后发送第一题；任意玩家答对后自动发送下一题。
- 自动结束：达到题目上限或时间上限会自动结束并发送排行榜，同时写入荣誉（名片可查）。
- 题目上限口径：按“累计答对题数（每题首次答对）”计。
- 计分：`score = correct_count - wrong_count / 3`。
- 自动提示：每题超过 `match_hint_delay` 秒未答对，会按提示序列持续发送提示直到没有可提示为止。

## 提示规则

提示序列（每次提示推进 1 步）：

1. 职业及分支
2. 星级
3. 阵营
4. 获取方式
5. 名称提示：每次增加显示 `ceil(len(name)/3)` 个字，直到全名

名称提示示例：名字长度 5 → 每次增加 2 个字 → 2/4/5。

## 配置（`_conf_schema.json`）

- `mrfz_data_path`: 题库 JSON 路径（默认 `arknights_skins_dict.json`）
- `target_size`: 输出图片参考大小
- `easy_probability` / `medium_probability` / `hard_probability`: 难度概率
- `similarity_threshold`: 相似度阈值（SequenceMatcher）
- `calculate_threshold`: 字符覆盖率阈值
- `enable_homophone`: 同音字识别
- `enable_operator_alias_match`: 是否启用干员别名精确判别
- `daily_game_limit`: 每日开局次数（0<不限制）
- `match_question_limit`: 比赛题目上限（0=不限制）
- `match_time_limit`: 比赛时间上限（分钟；0=不限制）
- `match_hint_delay`: 比赛超时自动提示（秒；0=关闭；默认 30）
- `admin_ids`: 比赛/管理指令管理员列表
- `require_admin`: 排行榜/名片是否仅管理员可用
- `low_weight_characters`: 低权重干员关键词（逗号分隔）
- `low_weight_ratio`: 低权重干员出现比例
- `character_aliases`: 别名映射（`别名:正名,...`）
- `operator_aliases_path`: 干员别名数据 JSON 路径（默认 `arknights_operator_aliases.json`）
- `renderer_theme`: 排行榜/名片主题

## 本地打包工具

在插件目录执行：

```bash
python scripts/package_plugin.py
```

脚本将打包 `git ls-files` 返回的已跟踪文件，默认输出到 `dist/astrbot_plugin_mrfzccl-<version>.zip`。

 ## 📊 数据来源 
 - 感谢blibliwiki的立绘资源 
 - 干员数据基于公开的明日方舟游戏信息 

 ## 📄 许可证 
 AGPL-3.0 

 ## 👨‍💻 开发者 
 - **开发者**：Lishining
 - **标语**：你知道的,我一直是明日方舟高手 
 - **QQ群**: 1083090761 

 --- 
 *感谢所有参与测试的明日方舟博士们！游戏愉快！🎮*
 *欢迎iss和pr,我看见了会认真修改的！*
 
[![Moe Counter](https://count.getloli.com/get/@li-shi-ling?theme=minecraft)](https://github.com/Li-shi-ling/astrbot_plugin_mrfzccl)
