# CLAUDE.md

动任何文件之前先读这份。它是**入口层**，不重复下面两份：

- `ARCHITECTURE.md` —— 项目自述，讲"为什么这样设计"和"否决了什么"（英文，392 行）。
- `ARCHITECTURE.review-20260918.md` —— module 边界审查，含 leak 清单（§5）、深化机会 D1-D5（§6）、风险与债务（§7）。

## 这是什么

Compass，一个**面向单个学生的"学业规则哨兵"**：盯着模块目录、学位要求、学术日历、公告流和这名学生的档案，只在"沉默会造成不可逆损失"时才打断她。目标用户是第一代大学生 / 国际生。为 AWS Hackathon "Agents for Humans" 而建。栈：Strands Agents + FastMCP + Pydantic + FastAPI/SSE + AgentCore Runtime。

## 一句话要害

**授权住在 policy（`src/compass/gate.py`），不住在 capability（`src/compass/tools/actions.py`）。**

模型只产出 `Finding` 事实；`gate.py` 用六条**有序**纯 Python 规则（R1 置信度 → R6 单向门）给出三种判决：SILENT / AUTO_ACT / SURFACE。**R6 是通向学生的唯一路径。** 无监督白名单 `AUTO_ACT_PERMITTED` 只含 `repair_degree_plan` / `file_degree_plan`。

先记住三条不变量：模型只能报事实；只有代码决定打断；白名单外的动作一律问人。削弱任一条，测试全绿也是错的。

## 文件地图

| 触发条件（你正想动什么） | 读哪个文件 |
|---|---|
| 打断判决 / 规则顺序 / 白名单 / 排序 | `src/compass/gate.py` —— 无 I/O、无时钟、无随机的纯函数。改规则**顺序**即改语义 |
| 契约 / 字段 / `Finding`·`Option`·`Receipt` | `src/compass/models.py` —— `Finding` 故意没有 `should_surface`；`Option.after` 是"强制第一步、不收参数" |
| 哪个动作能无监督执行 / registrar 级校验 / receipt | `src/compass/tools/actions.py` —— capability，不是 policy；先全部校验、再任何 mutation |
| 换模型 provider / 凭证 / 采样参数 | `src/compass/llm.py` —— 唯一知道 provider 的 module，interface 只有 `build_model()` / `describe()` / `resolve_provider()` |
| 数据读写 / 原子写 / `take_seat` | `src/compass/store.py` —— 无缓存、每次重读、写一律原子 |
| 一次 sweep 的编排 / 无监督副作用入口 | `src/compass/agents/compass.py` —— `sweep(findings=[...])` 是绕过模型的真 seam；`execute()` 是唯一边 |
| 模型拿得到哪些 tool / MCP 子进程 | `src/compass/tools/registry.py` —— action tools 绝不进这个列表 |
| Sentinel "只报事实"的 prompt | `src/compass/agents/sentinel.py` —— ~200 行 prompt 即实现，测试只能钉它的下游 |
| 决策卡 / SSE / 点击后执行 | `web/app.py` —— 无任何测试覆盖，见雷区 |
| 已部署 runtime 的契约 / 四个 verb | `app/Compass/main.py`（`handle()` 可无 runtime 测）+ `src/compass/remote.py`（client） |
| 合成数据集 / demo 日期 / 确定性生成 | `src/compass/data/generate.py` 与 `data/*.json` |
| 测试行为 / fixture / 凭据剥离 | `tests/conftest.py`，套件在 `tests/` |
| 部署声明 / provider / 密钥目标 | `agentcore/agentcore.json` |

## 本仓库特有雷区

1. **`llm.py:35` 硬编码 `~/lecture-live/.deepseek_key`** —— 一个相邻个人项目的本机路径，却是公开仓库里的默认凭证源。"凭证从哪来"与"用哪个 provider"是两个决定，现在混在同一个 interface 后面。测试靠把 `HOME` 重定向躲开它，所以**只有测试环境是安全的**。
2. **provider 由机器状态决定**（`llm.py:47-64`）：嗅探到 AWS 凭证就优先 bedrock，排在 deepseek 前。Owen 本机有 AWS 凭证 —— 不设 `COMPASS_PROVIDER` 跑本地 demo 会去撞**已被账户级封禁（Error 002）**的 Bedrock。跑之前显式设 `COMPASS_PROVIDER=deepseek`。
3. **`temperature=0` / `max_tokens=8192`（`llm.py:124`）只在 OpenAI-compatible 分支**；Bedrock 分支不传任何 params。"贪心解码、录出来=测出来"这条只属于 deepseek 路径。
4. **全套测试（README 称 132 用例）从不调用模型**：`tests/` 用注入的 findings 绕过模型（`test_orchestrator.py`），`conftest.py` 的 autouse fixture 剥掉凭据。所以模型行为、结构化输出可靠性、Bedrock 分支**都没有测试盯着** —— 改这些别指望套件会响。
5. **一次不合规的结构化输出会掀掉整个 sweep**：`scan()` 只兜 `MaxTokensReachedException` 与 `structured_output is None`，`SentinelReport(**report)` 的 `ValidationError` 不在捕获内 —— 连 R1 的安全降级都拿不到。
6. **`web/app.py:166` 用模型编的 `finding.id` 当 key**，而 `remote.py` 明确改用位置寻址（id 每次 sweep 由模型重写）。两个 id 相同即**静默丢卡**；该文件无测试。

## 当前状态 —— 只放指针，不抄数值

状态（commit 数、"Phase X 进行中"、日期）**永不写进这份 always-loaded 文档**：它每轮都进上下文，一旦腐烂比缺失更坏，而且你抄下的值一定比 `git` 旧。自己查：

```bash
git status                 # 工作树是否干净
git log --oneline -15      # 最近在做什么
```

- 风险与债务 → `ARCHITECTURE.review-20260918.md` §7；深化机会 D1-D5 → §6
- 路线图（未做的方向）→ `README.md` 的 "🗺 Roadmap" 一节
- 当前部署 provider / 密钥目标 → `agentcore/agentcore.json`（**唯一权威**，不要从 README 叙述里读）

## 完成判据

一个改动算完成，当且仅当：

- `python -m pytest` 全绿（无网络，约 4 秒）；
- 上面三条不变量仍成立：模型只报事实、`gate.py` 仍是无 I/O 纯函数、action tools 仍不在 `registry.agent_tools` 的返回里；
- 新行为有落在 **interface** 上的测试（callers 与 tests 走同一个 seam），而不是 mock 内部；
- 若碰了 `llm.py` 或任何 prompt：写清你是**怎么验的** —— 套件不覆盖模型行为，绿测试不构成证据。
