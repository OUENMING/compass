# Compass · 罗盘

> **给那些没人递过说明书的学生，补一本说明书。**

[![License: MIT](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12%2B-blue?style=flat-square)](https://www.python.org/)
[![Strands Agents](https://img.shields.io/badge/Strands-Agents%20SDK-orange?style=flat-square)](https://strandsagents.com/)
[![AgentCore](https://img.shields.io/badge/Deployed-AgentCore%20Runtime-yellow?style=flat-square)](https://aws.amazon.com/bedrock/agentcore/)
[![Tests](https://img.shields.io/badge/tests-132%20passing-brightgreen?style=flat-square)](tests/)
[![Data](https://img.shields.io/badge/data-100%25%20synthetic-lightgrey?style=flat-square)](#-许可与数据)

[English](README.md) · **简体中文**

一个常驻后台的 agent，像教务老师那样读懂大学的学位规则。一切正常时**完全沉默**，
只在「再不出声她就要付出收不回的代价」时才冒泡——而且**当场把事做掉**，不是描述一遍。

为 **AWS Agents for Humans** 黑客松而作 · **Good Neighbor Agents** 赛道。

![Compass 架构](docs/architecture.png)

<p align="center">
  <a href="#-问题">问题</a> ·
  <a href="#-功能">功能</a> ·
  <a href="#-安装">安装</a> ·
  <a href="#-使用">使用</a> ·
  <a href="#-项目结构">项目结构</a> ·
  <a href="#-技术栈">技术栈</a> ·
  <a href="#-工作原理沉默是一个决定">工作原理</a> ·
  <a href="#-常见问题">常见问题</a> ·
  <a href="ARCHITECTURE.md">架构文档</a> ·
  <a href="docs/DEVPOST.md">Devpost</a> ·
  <a href="docs/blog/">博客</a>
</p>

---

## 🧭 问题

大学的运转依赖一套规则，而这套规则**从来不是写给学生的**。

先修课链条，要等两个学期后才咬人。一笔图书罚款，悄悄升级成注册封锁。一条规则变更，
埋在手册内页而不是发进你的邮箱。一份学位计划，必须在选课窗口开放前审批通过，
顺序没人解释过。

这些都不是秘密，全都白纸黑字公开着——**按法典的方式公开**：完整、没有索引、
写给执行它的人看。

被逮住的不是学业吃力的学生，而是**家里没人走过这条路**的学生：第一代大学生，
以及除了学期日历、还要额外对着一张签证日历的国际学生。这就是本项目的全部受众，
也是 demo 里那个学生必须是这样一个人的原因。

**今天市面上的产品，是给机构做的，不是给学生做的。** EAB、Stellic、Ellucian、Druid，
全都卖给教务处：数据分析、学位审核工具、留存率看板。2026 年一份品类调研直说，
**至今没有面向学生的 agent**。学生是这些系统的*对象*，从来不是*用户*。

### 为什么是 agent，而不是又一个 App

黑客松的要求原文写得很直接：*"instead of another app people open and manage, the agent
runs autonomously and only surfaces when there's a real decision to make."*

**选课系统恰恰是这句话要排除的东西。** Compass 不是学生主动打开的 App，
而是持续读规则的守夜人——**一学期最多打扰你六次**，且只有当不打扰的代价
是她收不回来的东西时才出声。

---

## ✨ 功能

| 功能名称 | 功能说明 | 技术栈 | 状态 |
|---|---|---|---|
| **确定性沉默闸门** | 六条纯 Python 规则决定要不要出声。**模型没有投票权。** | `src/compass/gate.py` | ✅ |
| **后果推理** | 读出一个截止日期，返回结构化 `Finding`：`{irreversible_after_deadline, days_until_last_safe_action, confidence, options}` | Strands + Pydantic v2 | ✅ |
| **真实副作用** | 七个动作，按教务处系统的方式拒绝——先修课未过、学分上限、课已满、审核不过 | `src/compass/tools/actions.py` | ✅ |
| **可复现的回执** | 每个动作写一条 append-only 回执，确认号是**确定性**推导的。重跑 demo，同一串号 | `data/receipts.jsonl`（运行时写入） | ✅ |
| **Agent 白名单** | 只放行两个自动动作。花钱、改专业、联系人——永远不在名单上 | `AUTO_ACT_PERMITTED` | ✅ |
| **决策卡界面** | 静默 → 卡片滑入 → 她拍板 → 执行 → 回执上屏 | FastAPI + SSE | ✅ |
| **校园数据隔在协议后** | 课程目录、学位规则、学生记录由 FastMCP 服务经 stdio 提供，而非 import。两条传输路径，同一份工具清单 | FastMCP · `MCPClient` | ✅ |
| **三个专家 agent** | Pathfinder（先修课链）· Sentinel（截止日扫描）· Explainer（规则含义），agents-as-tools 编排 | Strands Agents SDK | ✅ |
| **已部署，可远程驱动** | 线上跑在 `eu-west-1` 的 AgentCore Runtime；`compass.remote` 经 `InvokeAgentRuntime` 打通完整四动词契约 | AgentCore · boto3 | ✅ |
| **模型后端可插拔** | `bedrock` · `openai` · `deepseek`，一个环境变量切换 | `src/compass/llm.py` | ✅ |

三个 demo 场景的完整叙述见 [`docs/DEVPOST.md`](docs/DEVPOST.md)。

---

## 📦 安装

### 环境要求

| 项 | 要求 |
|---|---|
| Python | **3.12+**（线上跑 3.14） |
| [uv](https://docs.astral.sh/uv/) | 任意较新版本 |
| AWS 账号 | 本地跑**完全不需要** |
| Docker | **不需要**（CodeZip 部署） |

### 安装步骤

```bash
git clone https://github.com/OUENMING/compass
cd compass
uv venv && uv pip install -e ".[web,dev]"
```

安装就这些——没有数据库、没有云依赖。但需要配一个模型后端：设 `COMPASS_PROVIDER`
及其 key，或 `DEEPSEEK_API_KEY`，或 `OPENAI_API_KEY`。一个都没有时，
`resolve_provider()` 会直接报错，不会替你猜。见下文「可选依赖」。

### 可选依赖

```bash
uv pip install -e ".[remote]"   # 仅当你的 AWS 凭证来自 `aws login`
uv pip install -e ".[docs]"     # 仅用于重新生成 docs/architecture.png
```

`aws login` 通过 AWS Common Runtime 发放基于浏览器的临时凭证，而 `botocore` 缺少
`crt` extra 时会拒绝该 provider。凭证是普通 access key 的话，不需要装这个。

架构图已签入仓库，所以跑项目、读项目都不需要 `docs` extra——只有重画它才需要。

---

## 🚀 使用

### 1 · 生成合成数据集

```bash
python -m compass.data.generate
```

确定性的：跑两次，产出逐字节相同的文件。测试就是在断言这一点。

### 2 · 选一个模型后端

Compass 刻意做成模型无关，后端从环境变量读：

```bash
export COMPASS_PROVIDER=deepseek DEEPSEEK_API_KEY=...   # 或 openai、bedrock
```

### 3 · 跑一次扫描

```bash
python -m compass.agents.compass                     # 扫描，并对 R4 类直接执行
python -m compass.agents.compass --direct-tools      # 跳过 MCP 子进程
python -m compass.agents.compass --json              # 机器可读的判决
python -m compass.agents.compass --ask "如果我转专业会怎样？"
```

**有东西冒泡时退出码是 `10`**，所以 cron 任务能区分"没什么可报的"和"她有个决定要做"。

### 4 · 打开决策卡

```bash
uvicorn web.app:app        # → http://localhost:8000
```

静默 → 卡片滑入 → 点一个选项 → 动作执行 → 回执出现。

### 5 · 驱动线上 agent

`agentcore invoke` 会把给它的任何东西包成 `{"prompt": ...}`，只能到达契约里"问答"那一半，
`sweep` 和 `decide` 永远收不到真正的 payload。这两个动词需要 payload 完整抵达——
这就是 `compass.remote` 存在的理由：

```bash
python -m compass.remote --json > sweep.json      # 扫描线上 agent
python -m compass.remote                          # 读报告
python -m compass.remote --decide 2 --option 1 --from sweep.json
python -m compass.remote --ask "W 截止日是什么时候？"
```

对线上端点的真实一次运行：

```text
2026-09-28 — 2 finding(s): 2 surfaced, 0 handled, 0 deliberately passed over.

  [1] surfaced: Overdue library items are blocking your registration and escalate on 5 October
          by 2026-10-05 (7 day(s) left)  ·  severity critical  ·  confidence 0.95
          -> 1. return-in-person: Return the three items in person
          -> 2. pay-charge: Authorise the EUR 45.00 replacement charge
          choose with: --decide 1 --option 1
```

执行 `--decide 1 --option 1` 之后：

```text
[LIB-2026-B6E2B7] Recorded the items as returned and cleared the library hold.
```

**同一个 session 里再扫一次，只剩一条 finding 而不是两条。** 线上 agent 真的把事做了，
而且它改动的状态仍然是被改过的样子。

> **finding 按"报告里的序号"寻址，不按 id。** id 是模型每次扫描时现编的，两次运行
> 结果不同；序号不会动，因为报告和客户端走的是同一个列表、同一个顺序。

> **session 是状态的单位**，所以 `decide` 必须指明它的 `sweep` 跑在哪个 session。
> 每次调用都会打印它用的那个，`--session` 可以带回来。不带就是新 session，
> 从随包发布的数据集开始。

---

## 📁 项目结构

```
compass/
├── README.md                  英文版（主）
├── README.zh-CN.md            本文件
├── CLAUDE.md                  AI agent 在本仓库的入场说明
├── ARCHITECTURE.md            怎么搭的，以及为什么
├── ARCHITECTURE.review-20260918.md   产出上面那份文档的审查
├── LICENSE                    MIT
├── pyproject.toml             extras: web · dev · remote
│
├── data/                      合成数据集 —— 26 门课、先修课图、
│   ├── courses.json           学位要求、一个学生、校历、公告
│   ├── degree_requirements.json
│   ├── student.json
│   ├── calendar.json
│   ├── announcements.json
│   ├── meta.json              来源说明 + "这里全是虚构的"
│   └── receipts.jsonl         它做过的一切，append-only（运行时生成）
│
├── src/compass/
│   ├── gate.py                ★ 六条确定性规则 —— 通往学生注意力的
│   │                            唯一路径
│   ├── models.py              `Finding` 契约（Pydantic v2）
│   ├── store.py               读时重读；写是原子的
│   ├── prereq.py              先修课图遍历
│   ├── audit.py               学位计划审核
│   ├── llm.py                 后端选择（bedrock · openai · deepseek）
│   ├── remote.py              线上 runtime 的客户端
│   ├── agents/
│   │   ├── compass.py         编排层：observe → judge → act → record
│   │   ├── pathfinder.py      先修课链、学位缺口
│   │   ├── sentinel.py        ★ 截止日扫描 → 结构化判决
│   │   └── explainer.py       hold / W 截止 / double-count 是什么意思
│   ├── tools/
│   │   ├── school_mcp_server.py   FastMCP over stdio（部署路径）
│   │   ├── school_tools.py        同一批函数，in-process @tool（测试路径）
│   │   ├── analysis_tools.py
│   │   ├── registry.py            选传输方式，一份工具清单
│   │   └── actions.py             真实副作用 + 回执
│   └── data/generate.py       确定性数据集生成器
│
├── web/
│   ├── app.py                 FastAPI: /, /api/events (SSE), POST /api/decide
│   └── static/                决策卡
│
├── app/Compass/main.py        AgentCore 入口（复用 src/compass）
├── agentcore/                 部署配置 + SSM 读取策略
│
├── tests/                     132 个测试，不联网，~4s
├── docs/
│   ├── architecture.png       由 make_architecture.py 生成 ——
│   │                            图是代码，所以不会过期
│   ├── DEVPOST.md             提交文案
│   ├── VIDEO.md               演示视频逐镜头
│   └── blog/                  三篇博客
└── agentcore/policies/        只授权单个 ARN 的 SSM 策略
```

---

## 🛠 技术栈

| 技术 | 版本 | 用途 | 官网 |
|---|---|---|---|
| [Strands Agents SDK](https://strandsagents.com/) | 1.55.1 | 三个专家 agent、`@tool`、agents-as-tools、`MCPClient` | strandsagents.com |
| [FastMCP](https://github.com/jlowin/fastmcp) | — | 校园数据隔在 stdio 协议后 | github.com/jlowin/fastmcp |
| [Amazon Bedrock AgentCore Runtime](https://aws.amazon.com/bedrock/agentcore/) | — | 部署（CodeZip，`eu-west-1`） | aws.amazon.com |
| Amazon Bedrock | — | 一等模型后端（Claude） | aws.amazon.com/bedrock |
| AWS Systems Manager Parameter Store | — | 线上凭证，存为 `SecureString` | aws.amazon.com/systems-manager |
| [Pydantic](https://docs.pydantic.dev/) | v2 | 模型与闸门之间的 `Finding` 契约 | docs.pydantic.dev |
| [FastAPI](https://fastapi.tiangolo.com/) + SSE | — | 决策卡 | fastapi.tiangolo.com |
| [uv](https://docs.astral.sh/uv/) | — | 环境与打包 | docs.astral.sh/uv |
| [pytest](https://pytest.org/) | — | 132 个测试，不联网 | pytest.org |
| Python | 3.12+ | 运行时（线上 3.14） | python.org |

开发工具：**Claude Code**。

---

## 🧠 工作原理：沉默是一个决定

> 这一段才是值得读的部分。其余都是任何一个合格 agent 都会有的管道。

你问模型*"这个重要吗？"*，它会说是——几乎对什么都说是，因为"有点重要"永远站得住脚。
所以这样搭起来的通知系统最后都变成噪音，而一个已经学会无视自己 agent 的学生，
**比根本没有 agent 更惨**：她连那份会让她主动看一眼的担心都失去了。

**Compass 从不问模型要不要出声。**

模型负责建立**事实**——什么变了、代价多少、最后一个安全时刻在何时、它有多确信、
有哪些选项。这些以 `Finding` 的形式交上来。而"要不要打扰人"，
由 [`src/compass/gate.py`](src/compass/gate.py) 里纯粹的 Python 按固定顺序决定：

| 规则 | 条件 | 判决 |
|---|---|---|
| **R1** | 置信度低于 0.70 | 沉默——绝不凭猜测行动 |
| **R2** | 最后一个安全时刻已经过去 | 沉默——已经没有可给的选项了 |
| **R3** | 后果可挽回 | 沉默——后台处理，一旦性质变了再出声 |
| **R4** | 不可逆，且成文规则已完全决定结果 | **执行**，从白名单里取，并留下回执 |
| **R5** | 不可逆，但距今还有 45 天以上 | 沉默——这是观察项，不是决策 |
| **R6** | 不可逆、在窗口内、且选择权确实属于她 | **弹出一张卡** |

```text
Finding —— 只有事实；要不要出声从不由模型决定
   │
   ▼
gate.py · R1 → R2 → R3 → R4 → R5 → R6 · 先命中者生效
   │
   ├── 沉默          R1 · R2 · R3 · R5
   ├── 执行 + 回执    R4   （仅限白名单）
   └── 冒泡          R6 ──▶ 学生
```

**R6 是整个系统里通往学生注意力的唯一路径。**

这样做会自然掉出三个性质，每一个都是交付物而不是声称：

| 性质 | 证据 |
|---|---|
| **可解释** | 每个判决都引用产生它的那条规则，用写给学生的语言，并直接显示在卡片上。她可以问*"我为什么会看到这个？"*，并得到真实答案。 |
| **可复现** | 同一条 finding 在同一天永远得到同一个判决，所以录下来的 demo 和测试套件验证的是同一件事。 |
| **可审计** | 沉默也带理由：无论是否冒泡，`GateDecision.reason` 都有值——于是*"它什么都没做"*是可检视的，而不是跟"它崩了"长得一样。 |

### 白名单才是安全性所在

`gate.py` 里的 `AUTO_ACT_PERMITTED` 只放**两个**动作：修复学位计划、提交学位计划。
两者都是成文规则已经完全定死的簿记工作。其余一切——花钱、改变她学什么、联系人——
都不在这份名单上，而且永远也不会在。

这防的是一个很具体的失败，也正是这个项目存在的理由。模型完全可能看着那笔 €45 的
图书馆账单，正确地推出"这钱迟早要付"，然后报一个 `needs_human_choice: false`——
*"无需判断"*。一个信任这个字段的闸门，就会替她把这笔钱付了。

**Compass 不信任这个字段。** 只要结果不在白名单上，这条 finding 就落到 R5/R6，
学生就会被问。

> *问一句花三秒；猜错花掉的是她收不回来的东西。*

### 真实动作，带回执

"not just chat about it" 是这届黑客松的主线，所以动作是真的，而且像教务系统那样校验。

出厂七个动作：`register_modules`、`drop_module`、`resolve_library_hold`、
`set_specialisation`、`repair_degree_plan`、`file_degree_plan`、`notify_advisor`。

每一个都**按真实系统的方式拒绝**。在先修课未通过时注册 *Econometrics II*，返回：

```json
{"error": "ECON30010 requires ECON20030, which the student has not passed. Registration refused."}
```

注册会检查未满足的先修课、学期 ECTS 上限、余位、重复注册，并**在任何改动之前**完成全部校验
——所以被拒绝的注册不会占掉座位。`file_degree_plan` 会拒绝通不过自身审核的计划，
这让"先修复、再提交"成为强制顺序，而不是建议。

每一个成功的动作都写一条回执，确认号是**确定性**的——由动作及其参数推导，而不是随机值，
所以重跑 demo 会得到同一串号。**回执就是证据**：`data/receipts.jsonl`
是它做过的一切的 append-only 记录，**包括那些没问就做了的事**。

### Compass 不会做的事

用限制来表述，因为这样的系统是由它拒绝做的事定义的：

| 不会…… | 因为 |
|---|---|
| **花学生的钱** | 任何有成本的动作都是一张卡，永远不是自动执行。 |
| **自作主张改变她学什么** | 转专业只会被"提供"，不会被"执行"。 |
| **替她联系人** | 除非她主动选择。给导师发消息的不可逆程度和修一份计划不同，回执里写明了这一点。 |
| **凭低置信度的判断行动** | 低于 0.70 一律沉默，无论猜对了后果多严重。 |
| **为一件以后还能修的事打扰她** | 可挽回的问题在后台处理，直到它不再可挽回。 |

---

## ☁️ 部署

线上 agent **就是**同一个 agent。`app/Compass/main.py` 校验 payload、调用
`compass.agents.compass`、序列化答案；Compass 的行为没有任何一部分住在入口文件里，
所以本地 demo 和线上 runtime 不可能跑偏。

```bash
agentcore validate
agentcore package                 # → agentcore/Compass.zip
agentcore deploy --yes
agentcore invoke "when is the W deadline?"
```

Runtime **没有可写存储**，所以一个 session 的第一次调用会把随包发布的数据集复制到
scratch 并把 `COMPASS_DATA_DIR` 指过去。session 之内写入是真的——注册一门课占掉一个座位，
退掉就还回来——而它们随 session 结束而结束，对虚构数据来说，这正是正确的生命周期。

### 契约

`POST /invocations` 接受四种 payload 之一。决策卡直接调前两个：

```jsonc
{"action": "sweep"}                                    // 全貌
{"action": "decide", "finding": {...}, "option_id": "return_in_person"}
{"action": "ask", "question": "when is the W deadline?"}
{"action": "reset"}                                    // 重新生成数据集
```

不带 `action` 的 payload 按其内容解读：一个裸的 `prompt` 是提问，什么都没有则是扫描。

`reset` 的存在是因为**线上 demo 会被第一个访问者消费掉**——一旦有人清掉了图书 hold，
下一个来看的人就没有东西可看。生成器是确定性的、数据是虚构的，所以把它放回去
是诚实的。它是**demo 的便利设施，不属于 agent 本身**。

注意前两者之间的不对称，那就是设计。扫描是无人值守的，所以它只能跑白名单里的
两个簿记动作。`decide` 携带的是人的选择，所以它执行所选的，并且回执会记下选的是哪个。

每一个失败都以**值**的形式返回，因为一个抛异常的入口只会给调用方一个 502
和一片无从下手的空白：

```python
def handle(payload: dict, compass: Compass) -> dict:
    try:
        return _dispatch(payload, compass)
    except CompassError as exc:
        return {"ok": False, "kind": "refused", "error": str(exc)}
    except ValueError as exc:
        return {"ok": False, "kind": "bad_request", "error": str(exc)}
```

*请求有误* 和 *被规则拒绝* 是两回事，应该得到不同的回答。而后者是一个值得展示给学生的
结果——它就是教务处会给出的那个拒绝。

### 仓库里不能有的那个凭证

线上 agent 需要模型凭证，而 `agentcore.json` 是进 git 的。它的 `envVars` 因此
不是放密钥的地方。Runtime 的环境变量只有 `name` 和 `value` 两个字段，没有引用语法——
所以进仓库的是 SSM 参数的**名字**，值留在 SSM：

```json
{"name": "COMPASS_SECRET_PARAMETER", "value": "/compass/model-api-key"},
{"name": "COMPASS_SECRET_TARGET",    "value": "DEEPSEEK_API_KEY"}
```

配合一条挂在 runtime 执行角色上的策略，**只授权那一个 ARN** 的 `ssm:GetParameter`
（[`agentcore/policies/model-key.json`](agentcore/policies/model-key.json)）。
入口在冷启动时读取它，幂等，且变量已存在时是空操作——所以本地 demo、CLI 和测试套件
都不会因为它去碰 AWS。

### 由哪个模型回答

Compass 支持三个后端，从 `COMPASS_PROVIDER` 里选一个：`bedrock`、`openai`、
`deepseek`。**线上跑的是 `deepseek`。**

`bedrock` 是一等路径，也是开发时对着写的那个。本次部署所用的 AWS 账号，
在 Bedrock **数据平面**上受新账号限制——
`ValidationException: Access to Bedrock models is not allowed for this account`，
表现为 `Error 002`。隔离测试表明这个限制是**账号级**而非模型级：
**Amazon Nova 和 Titan 一样失败**，换区域、用账号 root 自己的凭证也一样；
而 Bedrock 的*控制平面*返回 200，控制台的 Playground 渲染完全正常。
**这个不对称，正是"控制台看着健康、但每个 API 调用都失败"的原因。**

与其让这件事决定 demo 能不能跑，不如把 runtime 指向另一个 provider——
这本来就是那层抽象存在的理由。**换回去是一个环境变量加一次重新部署；代码路径是同一条。**

---

## ✅ 测试

```bash
python -m pytest tests -q      # 132 passed，不联网，~4s
```

测试套件从不调用模型，也从不碰仓库里已签入的 `data/`：每个测试在临时目录里生成一份
全新数据集，autouse fixture 会把 AWS 变量和 provider 选择变量从环境里剥掉、
把 `HOME` 指向一个空目录——所以套件在一台恰好登录着的机器上不会表现不同。

三个文件值得单独指出：

- **[`test_gate.py`](tests/test_gate.py)** —— 直接测策略。真正要守的性质是：
  R6 是通往冒泡判决的**唯一**路径，以及一个"报告说无需判断、但解决方式不在白名单上"
  的 finding，**仍然会被问**。
- **[`test_bundle.py`](tests/test_bundle.py)** —— 在临时目录里搭出部署包的目录形状，
  用剥离过的环境在里面跑入口。它存在是因为 MCP server 跑在**子进程**里，
  而子进程继承的是环境变量、不是父进程的 `sys.path`——所以一个只补了 `sys.path`
  的修复会通过所有本地测试，却在第一次真实调用时失败：这是再多常规本地测试
  也找不出来的部署 bug。

  断言落在**入口为子进程构建的环境**上，而不是落在集成上：把 `PYTHONPATH` 那行导出
  删掉再跑集成检查，**它照样通过**，因为子进程以正常的 `site` 处理启动，
  而 checkout 里的 editable 安装反正也能解析这个 import。**一个把修复删掉还通过的
  测试不是测试**，所以不变量被断言在它真正承重的地方，集成那一半被明确标注为
  它本来的样子：冒烟测试。

- **[`test_remote.py`](tests/test_remote.py)** —— 钉住线上 agent 与 `compass.remote`
  之间的线上契约。一边把那份 JSON 当 dict 构造，另一边当 dict 读，
  所以这个接缝没有任何类型检查；测试断言的是每个动词放到线上的精确 payload——
  而任何一边改了字段名，都会打断它。

---

## ❓ 常见问题

<details>
<summary><b>跑这个需要 AWS 账号吗？</b></summary>

不需要。数据层、工具、agent、闸门、Web UI 全都不碰 AWS。唯一需要凭证的是
`agentcore deploy` 和 `compass.remote`。

但需要一个**模型后端**，可以是任何 OpenAI 兼容端点：

```bash
export COMPASS_PROVIDER=openai OPENAI_API_KEY=...
```

</details>

<details>
<summary><b>为什么不让模型自己判断该不该通知我？</b></summary>

因为它会说"该"，而且几乎对什么都这么说。这正是整个设计要绕开的失败模式——
见[沉默是一个决定](#-工作原理沉默是一个决定)。模型提供事实，
一套固定顺序的六条 Python 规则决定要不要打扰你。

这也让 demo **可复现**：同一条 finding 在同一天永远产生同一个判决，
所以你在视频里看到的就是测试所断言的。

</details>

<details>
<summary><b>它会花我的钱吗？</b></summary>

不会。有一个 `resolve_library_hold` 动作可以授权 €45 的赔偿扣款，
而它**不在**自动动作白名单上。任何有成本的动作永远是一张由你选择的卡。

这不是假想——开发过程中，模型把这笔扣款报成了 `needs_human_choice: false`，
理由是"这钱迟早要付"。一个信任该字段的闸门就会把它付掉。
现在有一条测试专门盯着这件事。

</details>

<details>
<summary><b>为什么大学是虚构的？</b></summary>

`data/` 里的每一条记录都是合成的，那所大学——*Harbour University Dublin*——
并不存在。这是设计决定，不只是许可上的便利。

这些场景依赖对规则的具体解读：一条被撤回的豁免、一笔在特定日期升级的罚款、
一条 double-count 规则。把它们建在一所真实大学的手册上，
意味着发布一份**对真实机构规章作出断言**的文档——机构一改规则，这些断言立刻变错，
而且错的方式可能误导真实的学生。

虚构机构让 demo 变得诚实：**里面的一切对那个虚构世界都是真的，
而没有任何一条是对你的世界的断言。**

</details>

<details>
<summary><b>线上 demo 看起来没什么可看的，怎么回事？</b></summary>

有人先到了。一个线上 demo 会被第一个访问者消费掉——一旦有人清掉了图书 hold，
下一个来看的人看到的是一份干净的记录。

向 `/invocations` 发 `{"action": "reset"}`（或在决策卡里点 **Reset**）重新生成数据集。
生成器是确定性的、数据是虚构的，所以放回去是诚实的。

</details>

<details>
<summary><b>为什么 <code>agentcore invoke</code> 做不了 sweep？</b></summary>

因为 `agentcore invoke` 会把你传的任何东西包成 `{"prompt": ...}`。
这只能到达 `ask` 动词，仅此而已——`sweep` 和 `decide` 永远看不到它们真正的 payload。

用 `python -m compass.remote`：一个走 `InvokeAgentRuntime` 的小客户端，
说完整的契约。它有自己的测试
（[`tests/test_remote.py`](tests/test_remote.py)），因为 payload 形状是一份
没有任何类型检查的契约。

</details>

<details>
<summary><b>能对着我自己的专业用吗？</b></summary>

可以，而且数据集生成器本来就按 requirement group 参数化了——
闸门里没有任何一行知道"经济学"是什么。把 `data/*.json` 换成你自己的课程目录、
先修课图和学位要求分组即可；三个 agent 通过同一批工具读它们。

真正有意思的开放问题是**规则形状**能不能泛化——一条先修课链、
一个会升级的截止日、一条 double-count。见[路线图](#-路线图)。

</details>

---

## 🗺 路线图

| 方向 | 论点 |
|---|---|
| **要泛化的是规则形状，不是一个专业** | 目前的规则词汇表只有一个经济学专业。值得回答的问题是那些*形状*能不能泛化——我认为能，因为生成器本来就按 requirement group 参数化，而闸门对"经济学"一无所知。 |
| **把没写下来的规则也读进来** | Sentinel 现在推理的是手册上写着的规则。更难、也更有价值的那版，推理的是**没写下来的那部分**——那种*"学院可酌情决定"*的句式。 |
| **从服务一个学生到服务一群人** | 目前的 demo 只跟一份记录。闸门、白名单、回执日志本来就都是按学生隔离的，而**回执日志恰恰是学生支持办公室真正会想要的那块东西**：一份"agent 自己做了什么、为什么"的审计留痕。 |
| **从定时扫描到事件驱动** | 现在的扫描是按需触发的；一个跑满整个学期的部署应该挂在校历触发器上，以及手册变更检测上。 |

---

## 📚 文档

| 文档 | 内容 |
|---|---|
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | 怎么搭的，以及*为什么*——包括考虑过并否掉的方案 |
| [`ARCHITECTURE.review-20260918.md`](ARCHITECTURE.review-20260918.md) | 产出架构文档的那次审查：哪里是深模块、哪里是浅的、还有什么没解决 |
| [`CLAUDE.md`](CLAUDE.md) | AI agent 在本仓库的入场说明——东西在哪、哪些坑不要踩 |
| [`docs/DEVPOST.md`](docs/DEVPOST.md) | 提交文案：问题、受众、三个 demo 场景 |
| [`docs/VIDEO.md`](docs/VIDEO.md) | 演示视频逐镜头 |
| [`docs/blog/01`](docs/blog/01-agents-for-humans-silence-by-default.md) | 沉默优先：拒绝让模型决定何时出声 |
| [`docs/blog/02`](docs/blog/02-agents-for-humans-agentcore-deployment.md) | 部署到 AgentCore：一个本地测试永远找不到的 bug |
| [`docs/blog/03`](docs/blog/03-agents-for-humans-testing.md) | 测试一个由"拒绝做什么"定义的 agent |
| [`docs/make_architecture.py`](docs/make_architecture.py) | 架构图是代码，所以它不会过期 |

---

## 📄 许可与数据

MIT —— 见 [LICENSE](LICENSE)。SPDX-License-Identifier: `MIT`。

这是为本届黑客松写的原创作品；**没有复用任何既有项目代码。**

### 关于数据，再说一次

所有记录都是虚构的，机构是虚构的，**这个仓库里没有任何真实学生的信息**。
见 [`data/meta.json`](data/meta.json)。
