# 明日方舟猜猜乐（Mrfzccl）

AstrBot 插件：遮挡干员立绘猜名字，支持单局游戏、排行榜、用户名片和群比赛模式。

当前版本：`2.0.0-beta.1`

## 功能概览

- 立绘遮挡猜干员，支持私聊个人局和群聊共享题目。
- 支持提示、强制结束、每日开局次数限制。
- 支持正确、错误、提示使用次数排行榜。
- 支持用户名片和比赛荣誉统计。
- 支持群比赛模式：题数限制、时间限制、自动提示、自动结算。
- 支持多种判题方式：精确匹配、相似度、字符覆盖率、同音字、干员别名、LLM 兜底判题。
- 支持网络 T2I 渲染排行榜/名片图片，失败时回退本地 Html2Image。
- 问答统计图片支持 `light`、`industrial`、`retro_win` 三种主题。

## 命令

### 游戏

| 命令 | 说明 | 示例 |
|---|---|---|
| `/fc` | 开始一局。私聊为个人局，群聊为群内同一题 | `/fc` |
| `/fcc 干员名` | 猜测当前题目的干员名称 | `/fcc 能天使` |
| `/fct` | 获取下一条提示 | `/fct` |
| `/fcw` | 一次性获取三条提示 | `/fcw` |
| `/fce` | 强制结束当前题目并显示答案 | `/fce` |

游戏期间如果开启 `enable_other_message_exact_match`，普通聊天消息只要精确包含当前正确答案，也会被判定为答对。通过 @ 或唤醒词触发的消息也会参与该检测；未命中正确答案时不会回复，也不会影响后续消息处理。

### 统计

| 命令 | 说明 |
|---|---|
| `/ccl 排行榜` | 查看正确次数排行榜 |
| `/ccl 错误排行榜` | 查看错误次数排行榜 |
| `/ccl 提示排行榜` | 查看提示使用排行榜 |
| `/ccl 名片 [用户ID]` | 查看用户名片。不填写用户 ID 时查看自己 |

当 `require_admin=true` 时，排行榜相关指令仅管理员可用。

### 比赛

比赛指令仅群聊管理员可用。

| 命令 | 说明 | 示例 |
|---|---|---|
| `/ccl 比赛帮助` | 查看比赛命令 | `/ccl 比赛帮助` |
| `/ccl 比赛创建 [名称] [题目限制] [时间限制(分钟)]` | 创建比赛，限制填 `0` 表示不限 | `/ccl 比赛创建 春节赛 20 30` |
| `/ccl 比赛开始` | 开始比赛并发送第一题 | `/ccl 比赛开始` |
| `/ccl 比赛结束` | 结束比赛并结算荣誉、排行 | `/ccl 比赛结束` |
| `/ccl 比赛排行` | 查看当前比赛排行 | `/ccl 比赛排行` |
| `/ccl 清除数据 [user_id]` | 清除指定用户的比赛数据 | `/ccl 清除数据 123456` |
| `/ccl 清除荣誉 [user_id]` | 清除指定用户的比赛荣誉 | `/ccl 清除荣誉 123456` |
| `/ccl 清除所有数据` | 清除所有用户的比赛数据 | `/ccl 清除所有数据` |
| `/ccl 清除所有荣誉` | 清除所有用户的比赛荣誉 | `/ccl 清除所有荣誉` |
| `/ccl 授予荣誉 [user_id] [名次] [比赛名称] [答对数量]` | 手动授予比赛荣誉 | `/ccl 授予荣誉 123456 1 春节赛 20` |

## 比赛机制

- 自动出题：`/ccl 比赛开始` 后发送第一题，任意玩家答对后自动发送下一题。
- 自动结束：达到题目上限或时间上限时自动结束，并发送排行榜。
- 题目上限口径：按累计答对题数计算，每题只统计首次答对。
- 计分方式：`score = correct_count - wrong_count / 3`。
- 自动提示：每题超过 `match_hint_delay` 秒未答对时，按提示顺序持续发送提示，直到没有可发送提示为止。

## 提示规则

提示会按以下顺序推进：

1. 职业及分支
2. 星级
3. 阵营
4. 获取方式
5. 名称提示：每次增加显示 `ceil(len(name) / 3)` 个字，直到显示全名

示例：名称长度为 5 时，每次名称提示会显示 2、4、5 个字。

## 配置说明

配置文件为 `_conf_schema.json`，每个配置项都带有 AstrBot 配置界面提示文本。

### 基础与数据

| 配置项 | 说明 |
|---|---|
| `mrfz_data_path` | 明日方舟角色数据 JSON 路径，默认使用插件自带 `arknights_skins_dict.json` |
| `operator_aliases_path` | 干员别名数据 JSON 路径，默认使用插件自带 `arknights_operator_aliases.json` |
| `target_size` | 角色立绘最终输出的参考大小 |
| `daily_game_limit` | 每个用户每日开启游戏次数限制，`-1` 表示无限制 |
| `admin_ids` | 管理员 QQ 号列表 |
| `require_admin` | 排行榜查看指令是否启用管理员限制 |

### 难度与随机池

| 配置项 | 说明 |
|---|---|
| `easy_probability` | 简单难度概率，默认 `0.6` |
| `medium_probability` | 中等难度概率，默认 `0.3` |
| `hard_probability` | 困难难度概率，默认 `0.1` |
| `low_weight_characters` | 低权重干员关键词，逗号分隔 |
| `low_weight_ratio` | 低权重干员出现概率缩放比例 |

### 判题

| 配置项 | 说明 |
|---|---|
| `enable_similarity_match` | 是否启用相似度匹配判题 |
| `similarity_threshold` | 相似度阈值，越高要求越严格 |
| `enable_character_coverage_match` | 是否启用字符覆盖率匹配判题 |
| `calculate_threshold` | 字符覆盖率阈值，只判断字是否覆盖，不要求位置一致 |
| `enable_homophone` | 是否启用同音字识别 |
| `enable_operator_alias_match` | 是否启用干员别名精确判别 |
| `enable_other_message_exact_match` | 是否启用普通消息精确包含答案判题 |
| `character_aliases` | 旧版别名映射，格式为 `别名:正名,别名2:正名2` |
| `character_aliases_json` | JSON 版别名映射，会与旧版 `character_aliases` 合并 |

### LLM 兜底判题

`llm_judge` 只会在前置判题都失败时启用。

| 子配置项 | 说明 |
|---|---|
| `llm_judge.enabled` | 是否启用 LLM 兜底判题 |
| `llm_judge.provider_id` | AstrBot 原生模型选择器，留空等同关闭该判题方式 |
| `llm_judge.prompt` | 模型提示词，支持 `{answer}` 和 `{guess}` 占位符 |
| `llm_judge.debug` | 是否开启 LLM 判题调试日志 |
| `llm_judge.enable_retry` | 模型调用失败或输出无法识别时是否重试 |
| `llm_judge.max_retries` | 额外重试次数，`0` 表示只请求 1 次 |
| `llm_judge.retry_interval_seconds` | 每次重试之间的等待秒数 |

LLM 输出解析规则：

- 大小写无关地检测输出中是否包含独立的 `true` 或 `false`。
- 包含 `false` 时判为错误。
- 只包含 `true` 时判为正确。
- 无法识别时按重试配置继续重试。
- 重试耗尽后默认判为 `false`。

### 比赛

| 配置项 | 说明 |
|---|---|
| `match_question_limit` | 默认比赛答题数量限制，`0` 表示不限制 |
| `match_time_limit` | 默认比赛时间限制，单位分钟，`0` 表示不限制 |
| `match_hint_delay` | 比赛超时自动提示间隔，单位秒，`0` 表示关闭 |

### 图片渲染与主题

| 配置项 | 说明 |
|---|---|
| `renderer_theme` | 问答统计图片主题，可选 `light`、`industrial`、`retro_win` |
| `image_download_retry.max_retries` | bilibili wiki 图片下载失败后的额外重试次数 |
| `image_download_retry.retry_interval_seconds` | 图片下载重试间隔秒数 |
| `t2i.enabled` | 是否启用网络 T2I 渲染，默认开启 |
| `t2i.max_concurrent` | 网络 T2I 最大并发数 |

T2I 调用链路说明：

- 插件不维护 T2I 服务地址配置。
- 网络 T2I 通过 AstrBot 原生 `html_render` 调用。
- 实际 T2I 服务地址请在 AstrBot 系统配置 `t2i_endpoint` 中维护。
- 网络 T2I 失败时会自动回退到本地 Html2Image。
- 使用网络 T2I 时，插件会使用适配远程截图行为的 HTML 渲染方案，并对 T2I 返回图片做边缘裁剪，减少右侧和底部白边。

## 本地打包

在插件目录执行：

```bash
python scripts/package_plugin.py
```

脚本会读取插件版本并输出到：

```text
dist/astrbot_plugin_mrfzccl-<version>.zip
```

当前版本打包产物示例：

```text
dist/astrbot_plugin_mrfzccl-v2.0.0-beta.1.zip
```

## 数据来源

- 感谢 bilibili wiki 的立绘资源。
- 干员数据基于公开的明日方舟游戏信息。

## 许可

AGPL-3.0

## 开发者

- 开发者：Lishining
- 标语：你知道的，我一直是明日方舟高手
- QQ 群：1083090761

欢迎 issue 和 PR，我看到后会认真处理。

[![Moe Counter](https://count.getloli.com/get/@li-shi-ling?theme=minecraft)](https://github.com/Li-shi-ling/astrbot_plugin_mrfzccl)
