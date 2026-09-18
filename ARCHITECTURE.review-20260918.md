# Compass 架构审查

> 审查对象：`/Users/owen/compass`（HEAD `d14011b`，12 commits，工作树干净，Python 3.12+，约 6.6k 行源码 + 测试）
> 方法：读源码 + git 历史，逐条核对文件路径与行号；未运行 agent、未联网、未修改任何代码。
> 术语约定：本文严格使用 **module / interface / implementation / depth / seam / adapter / leverage / locality / deletion test**（`codebase-design` 词汇表）。不以"组件 / 服务 / API / 边界"替代这些概念。
>
> ⚠️ 本路径原先已有一份项目自述的英文架构文档（393 行，commit `794eb74`）。本次审查覆盖了它。原文完整可取回：
> `git show HEAD:ARCHITECTURE.md`（或 `git checkout -- ARCHITECTURE.md`）。两份文档定位不同：那份讲"为什么这样设计"，本文讲"现在的 module 边界是否站得住"。

---

## 1. 这是什么

Compass 是一个**面向单个学生的"学业规则哨兵"**：它盯着大学的模块目录、学位要求、学术日历、公告流和这一名学生的档案，只在"沉默会造成不可逆损失"的时候才打断学生。

- **目标用户**：第一代大学生、国际生，从工程转入经济学的二年级学生。她不知道 "standing waiver"、"degree audit"、"requirement group" 是什么（这段人设写死在 `src/compass/agents/sentinel.py:58-61`、`pathfinder.py:30-32`、`explainer.py:29-32` 三处 prompt 里）。
- **核心主张**：**"要不要打断她"由代码决定，不由模型决定**。模型只报告事实（`Finding`），`src/compass/gate.py` 用六条编号规则给出三种判决：`SILENT`（并记录理由）、`AUTO_ACT`（自己做完，留下 receipt）、`SURFACE`（放一张卡，等她点）。
- **数据全部是合成的**：`data/*.json` 由 `python -m compass.data.generate` 确定性生成，`demo_today` 固定在 `2026-09-28`（`data/meta.json`），所以"还剩几天"是可复现的数字而不是跑的时刻的函数。
- **怎么跑**：三种入口，全都调同一个 orchestrator，差别只在"代码在谁那边"。
  | 入口 | 命令 / 位置 |
  |---|---|
  | 本地 CLI（一次 sweep 或一次问答） | `python -m compass.agents.compass`（`src/compass/agents/compass.py:311`），或 `compass` console script（`pyproject.toml:41`） |
  | 本地决策卡 UI | `python web/app.py` → FastAPI + SSE（`web/app.py:264`） |
  | 已部署的 AgentCore runtime | HTTP `POST /invocations`（`app/Compass/main.py:260-281`），客户端是 `python -m compass.remote`（`src/compass/remote.py:270`） |

**为 AWS Hackathon "Agents for Humans" 而建**（`agentcore/agentcore.json:11`）。关键背景：AWS Bedrock 在账户级被封（`Error 002: Access to Bedrock models is not allowed for this account`，记录在 `README.md:489-500`），所以部署时的模型后端从 bedrock 改成了 **deepseek**（`agentcore/agentcore.json:24-25`）。本文 §5.1 专门评估这次 swap 有没有留下伤。

---

## 2. 技术栈与框架

**Python 栈**（`pyproject.toml`，requires-python `>=3.12`）：

| 层 | 用什么 | 位置 |
|---|---|---|
| Agent 框架 | **Strands Agents** `>=1.55.1`（`Agent`、`@tool`、adapters-as-tools、`structured_output_model`） | `pyproject.toml:9` |
| 工具协议 | **FastMCP** `>=2.0`（stdio server） | `pyproject.toml:10` |
| 数据契约 | **Pydantic v2**（`Finding` / `Option` / `Receipt` / 学校数据） | `pyproject.toml:11` |
| 模型后端 | Strands 的 `BedrockModel` 或 `OpenAIModel`（deepseek / openai 都走 OpenAI-compatible） | `src/compass/llm.py:80-125` |
| 部署宿主 | **bedrock-agentcore** `>=1.9.1` + `aws-opentelemetry-distro` | `pyproject.toml:17-18` |
| 凭证 | boto3 读 SSM Parameter Store（SecureString） | `app/Compass/main.py:99-129` |
| Web（extra `web`） | FastAPI + uvicorn + 原生 `StreamingResponse` SSE | `pyproject.toml:29` |
| 测试（extra `dev`） | pytest，127 个顶层 test 函数（README 称收集到 132 个用例；未运行验证） | `tests/` |

**没有的东西（都是刻意的，`ARCHITECTURE.md` 旧版 §9 有记录）**：没有数据库、没有向量检索 / embeddings、没有跨会话对话记忆、没有 lockfile。规则集是 26 个模块 + 5 条成文规则，直接查表比检索更精确。

**模型 provider 接线**（这是本次审查的重点，先给结论）：
`src/compass/llm.py` 是一个 144 行的 module，interface 只有三个函数 —— `resolve_provider()`（`:55`）、`build_model()`（`:74`）、`describe()`（`:132`）。选 provider 的顺序是：显式 `COMPASS_PROVIDER` → 有 AWS 凭证就 bedrock → 能找到 deepseek key 就 deepseek → `OPENAI_API_KEY` → 否则抛错并告诉你该设什么（`llm.py:55-71`）。模型 id 一律可被 `COMPASS_MODEL_ID` 覆盖，默认值在 `llm.py:30-32`。

**部署故事**：
- `agentcore/agentcore.json` 声明 `build: CodeZip`、`codeLocation: "./"`（**仓库根**）、`entrypoint: app/Compass/main.py`、`runtimeVersion: PYTHON_3_14`、region `eu-west-1`。从仓库根打包意味着 `src/`、`data/`、`app/` 三者在 bundle 里是兄弟目录（`app/Compass/main.py:42-59` 为此把 `src/` 塞进 `sys.path` **并且**导出 `PYTHONPATH`，因为 MCP server 是子进程，只继承环境不继承 `sys.path`）。
- runtime 的 bundle 只读，所以每个 session 第一次调用把 `data/*.json` 拷到 `/tmp/compass-data` 再指 `COMPASS_DATA_DIR`（`app/Compass/main.py:73-96`）；session 内写入是真的，随 session 消失。
- 本地 / 测试路径完全不需要 AWS 或 bedrock-agentcore：`tests/conftest.py:56-68` 会剥掉 `AWS_PROFILE`、`COMPASS_PROVIDER` 等变量并把 `HOME` 指到临时目录。

---

## 3. 数据流与代码逻辑

### 3.1 一次 sweep（主路径）

以 `python -m compass.agents.compass -v` 为例：

1. `main()`（`src/compass/agents/compass.py:311`）解析参数 → `Compass(data_dir=None, use_mcp=True)`。
2. `Compass.__init__`（`compass.py:131-145`）：
   - `store.default_data_dir()` → `<repo>/data`（`src/compass/store.py:39-40`）；
   - **`:142` 把 `COMPASS_DATA_DIR` 写进 `os.environ`** —— 因为 action tool 是被模型按名字调用的，没法传目录，只能靠环境变量让"agent 的写"和"orchestrator 的读"落在同一份文件上；
   - `:143` `build_model()` → `src/compass/llm.py:74`。
3. `Compass.sweep()`（`compass.py:153`）：`SchoolStore(self.data_dir).today` 读 `data/meta.json` 的 `demo_today` → `2026-09-28`（`store.py:78-81`）。
4. `:160-161` 进入 `agent_tools(use_mcp=True, data_dir=...)` 上下文（`src/compass/tools/registry.py:33`）：起 MCP 子进程 `python -m compass.tools.school_mcp_server`（`registry.py:55-59`），拿到 **6 个 school tool + 7 个 analysis tool**（`registry.py:62`）。
5. `build_sentinel(model, tools)`（`src/compass/agents/sentinel.py:235`）→ `scan()`（`sentinel.py:255`）→ `agent(prompt, structured_output_model=SentinelReport)`（`sentinel.py:280-281`）。
6. **模型这一轮做的真实 tool call**：
   - `list_announcements(only_unannounced=true)` → **越过 MCP 进程边界** → `school_tools.list_announcements`（`src/compass/tools/school_tools.py:201`）→ `store()`（`:35`）→ `SchoolStore._read("announcements")`（`store.py:56`）→ `data/announcements.json`；
   - `audit_degree_plan()`（**不越边界**，in-process）→ `audit.audit()`（`src/compass/audit.py:95`）+ `audit.unassigned_modules()`（`audit.py:196`）→ 每组学分、重复计数、未指派模块；
   - `check_module_eligibility(code)` / `trace_prerequisite_chain(code)` / `term_load()`（`src/compass/tools/analysis_tools.py:120/159/195`）→ `prereq.missing_prereqs` / `chain_to` / `satisfiable` / `unlocks`（`src/compass/prereq.py:46/96/112/81`）。
7. 返回 `SentinelReport{findings: [...]}`（`sentinel.py:229-232`）→ Pydantic 校验成 `list[Finding]`（`src/compass/models.py:211-235`）。若撞 `MaxTokensReachedException` 或没拿到 structured output，**用一句 nudge 再问一次**（`sentinel.py:277-291`），两次都失败才抛。
8. `decide_all(findings, today)`（`src/compass/gate.py:193`）—— **纯函数，无 I/O、无时钟、无随机**：逐条过 `decide()`（`gate.py:114-190`）的六条规则（R1 置信度、R2 窗口已关、R3 可挽回、R4 无选择、R5 太早、R6 单向门），再按"单向门的紧迫度"而非 severity 排序（`gate.py:208-222`）。**R6 是通向学生的唯一路径**（`gate.py:184-190`）。
9. 对每个 `AUTO_ACT`（只可能是 `repair_degree_plan` 或 `file_degree_plan`，白名单在 `gate.py:97`）：`Compass.execute()`（`compass.py:192`）→ `_option()` 选 option（`:79`）→ 校验 action 名都在 `ACTION_BY_NAME` 里（`:209-214`）→ `_call()`（`:226-247`，先用 `inspect.signature().bind()` 把模型传错的参数名变成"这次动作被拒"，而不是一个 500）→ 真的执行 `actions.repair_degree_plan` / `file_degree_plan`（`src/compass/tools/actions.py:285/325`）→ 写 `data/student.json`（`store.py:113`，原子写 `:59-70`）+ 追加 `data/receipts.jsonl`（`store.py:139`）。
10. `SURFACE` 的决策**不产生任何副作用**，只是被 `Sweep.surfaced` 暴露给调用方（`compass.py:102-104`）；退出码 `10` 表示"至少有一张卡上去了"（`compass.py:345`）。

### 3.2 一次 free-form 问答

`Compass.ask()`（`compass.py:251-272`）：重新开一个 `agent_tools` 上下文 → 构造 `pathfinder` 和 `explainer`（`agents/pathfinder.py:70`、`agents/explainer.py:69`）→ **把两个 specialist 当作 tools 交给一个 router `Agent`**（`:264-271`），router 的 prompt 在 `compass.py:58-77`。router 自己没有数据 tool（"it cannot answer from memory because it has nothing to answer from"），只能把问题转给 specialist。注意 `ask()` 的 docstring 说明了为什么**问答路径上没有 gate**：人主动提问时已经付出了注意力，没有"要不要打断"要判。

### 3.3 部署路径的一次 sweep

`POST /invocations` → `invoke()`（`app/Compass/main.py:260-275`）→ `_load_provider_secret()`（`:99`，从 SSM 取 key 放进环境，幂等，已设则 no-op）→ `Compass(data_dir=data_dir(), use_mcp=True)` → `handle()`（`:146`，纯函数，可无 runtime 测试）→ `_dispatch()`（`:183-257`）把 `Sweep` 序列化成 `{ok, today, summary, data_dir, surfaced, handled, silent, receipts}`。四个 verb：`sweep` / `decide` / `ask` / `reset`。`decide` **要求调用方把 finding 整体传回来**（`:224-236`），而不是按 id 查一遍 —— 这样授权来自"点下去的那个人"，而不是来自"产生它的那次 sweep"。

---

## 4. 架构：module · interface · depth

判定标准用词汇表的定义：**depth 是 interface 上的 leverage** —— 调用方（或测试）每学一单位 interface 能驱动多少 behaviour。implementation 行数不算 depth。

| Module | interface（调用方必须知道的一切） | implementation 藏了什么 | depth 判定 |
|---|---|---|---|
| `compass.gate`（`gate.py`，222 行） | `decide(finding, today, horizon_days, min_confidence) -> GateDecision`；`decide_all(findings, today, ...) -> list[GateDecision]`；`AUTO_ACT_PERMITTED`；`auto_chain(finding)` | 六条规则的**顺序**（顺序本身是语义：R3 在 R5 前吞掉所有可挽回的）、每条规则的 reason 文案、R4 的"声明无选择但不在白名单时如何降级"（`:161-170`）、排序策略。纯函数，无 I/O | **deep**。两个函数 + 一个 frozenset 撑起整个产品主张；interface 就是测试面（`tests/test_gate.py` 20 个 test 直接打在这上面） |
| `compass.models`（`models.py`，258 行） | 全部 Pydantic 类型：`Finding` / `Option` / `Verdict` / `GateDecision` / `Receipt` + 学校数据六型 | 字段级约束（`confidence: ge=0, le=1`）、`Option.after` 的语义、"`Finding` 故意没有 `should_surface` 字段"这个负空间 | **无 behaviour 的契约 module**。这不是 shallow —— 它没有 implementation 可藏，它的价值是把"模型"和"策略"之间的 seam 定成可校验的类型 |
| `compass.store`（`store.py`，150 行） | `SchoolStore(dir)`；读：`.today` / `.courses` / `.course(code)` / `.student` / `.requirements` / `.calendar` / `.announcements` / `.event(id)` / `.receipts()`；写：`save_student` / `take_seat(code, delta)` / `record_receipt` | 每次读都重解析（没有缓存，`store.py:100-106` 说明了为什么：agent 的 tool 和 orchestrator 常常在不同进程）、原子写（temp + `os.replace`，`:59-70`）、`take_seat` 必须从**新读**的副本改（`:116-130`，否则改的是 throwaway copy） | **deep**。11 个读写入口，藏住"没有缓存 + 原子写 + 必须重读"三条不变量 —— 这三条正是最容易写错的地方 |
| `compass.llm`（`llm.py`，144 行） | `build_model()` / `describe()` / `resolve_provider()` | provider 选择顺序、三套默认 model id、凭证发现（含一条本机路径，见 §5.1）、按 provider 分支的 params | **deep（但有泄漏）**。interface 很小，implementation 里的"选择策略"是真的策略；问题不在 depth，在 interface 收进了 machine-local 假设 |
| `compass.audit` + `compass.prereq`（`audit.py` 199 行 / `prereq.py` 147 行） | `audit(store, plan)` / `propose_fix(store, student, plan)` / `unassigned_modules(...)`；`missing_prereqs` / `satisfiable` / `chain_to` / `unlocks` / `passed_codes` | 规则 1、2 的实现、图的传递闭包、`satisfiable` 与 `missing_prereqs` 的关键区别（"今天被堵住" vs "还能不能补上"） | **deep**。纯函数、可测、无 I/O（除读 catalogue），这是把"算术"从 prompt 里搬出来的成果 |
| `compass.tools.school_tools` + `school_mcp_server`（240 + 46 行） | 6 个普通函数（`list_courses` / `get_course` / `get_degree_requirements` / `get_student_record` / `get_academic_calendar` / `list_announcements`），签名即 JSON schema，docstring 即 tool 描述 | 数据形状的投影（`_course_dict` 的 brief/full 两档 `:49-65`）、`_hold_dict` 把 `status` 摆在第一行（`:141-156`）、`store()` 的进程内缓存 | **moderate**。它同时是"数据投影 + tool 描述 + transport 无关的函数定义"三种角色。`school_mcp_server.py` 本身是**正确的 shallow**（46 行、唯一职责是 adapter，`mcp.tool(fn)` 循环） |
| `compass.tools.registry`（62 行） | `agent_tools(use_mcp, data_dir)` —— 一个 context manager | MCP 子进程的启动/关闭、`env` 传递、两个 transport 的接线、以及"analysis tools 永远直连、绝不走协议边界"这条决定 | **deep**。一个 `with` 语句换掉"子进程生命周期 + 环境传递 + tool 集合组装" |
| `compass.tools.analysis_tools`（314 行） | 7 个 `@tool`：`today` / `days_from_today` / `audit_degree_plan` / `check_module_eligibility` / `trace_prerequisite_chain` / `term_load` / `compare_specialisations` | 每个函数里有：store 解析、委托给 audit/prereq、面向模型的 JSON 投影、`compare_specialisations` 的"takeable today vs closable with detour"双计分 | **shallow-to-moderate**（见 §6 D5）。算术已经搬走，剩下的主体是**投影**；7 个 interface 各有自己的参数与返回形状，但背后行为很薄。可接受的 shallow：它的调用方是模型，模型需要窄而多的 tool 而不是一个宽 interface |
| `compass.tools.actions`（435 行） | 7 个 `@tool` + `ACTION_BY_NAME` / `ACTION_TOOLS` | 每个动作的 registrar 级校验（先全部校验、再任何 mutation，`actions.py:81-113`）、确定性 receipt 号（`sha256(action+args)[:6]`，`:47-55`）、`set_specialisation` 的"先把两组都清掉再放进新组"防双计的细节（`:249-259`）、`file_degree_plan` 拒绝未通过 audit 的 plan（`:341-353`） | **deep**。7 个 interface 背后是真实的规则校验 + 状态变更 + 审计记录 |
| `compass.agents.sentinel`（296 行） | `build_sentinel(model, tools)` / `scan(agent, attempts=2) -> list[Finding]` | ~200 行 prompt 里的"怎么算 irreversible""什么算一个 root cause 而不是三个症状""先确认事实是否仍然成立再报"、结构化解码 + 重试策略 | **moderate**。它是"prompt as implementation" —— interface 很小，implementation 全在自然语言里。好处是这套知识有 locality（一个文件），坏处是它不可被测试直接覆盖（测试只能钉它的下游） |
| `compass.agents.pathfinder` / `explainer`（89 / 88 行） | `build_*(model, tools)` / `explore(agent, q)` / `explain(agent, q)` | 两套人设 prompt + "绝不在脑子里算数" / "引用，不要猜" 两条硬约束 | **shallow by design**。它们几乎没有 behaviour，只是 prompt 的容器。`explore`/`explain`（各 2 行）是纯 pass-through —— 按 deletion test 该考虑删掉，但保留它们让三个 specialist 的 interface 对称，代价可接受 |
| `compass.agents.compass`（349 行，orchestrator） | `Compass(data_dir, model, use_mcp, on_event)`；`sweep(findings=None) -> Sweep`；`execute(decision, option_id=None) -> list[Receipt]`；`ask(question) -> str`；`main(argv)` | observe→judge→act 的编排、`_emit` 的事件流、`Sweep` 的桶（surfaced/auto_acted/silent）、AUTO_ACT 失败时的"停止行动而不是重试"（`:173-185`）、`_call` 的参数校验 | **deep**。`sweep()` 一个调用换一整套流水线；`findings` 参数是一个真实的内部 seam（测试用它完全绕过模型，`tests/test_orchestrator.py` 15 个 test 全靠它） |
| `app/Compass/main.py`（281 行） | `handle(payload, compass) -> dict`（纯函数，可无 runtime 测试）+ `invoke(payload)` entrypoint | session 级可写数据目录的准备、SSM 凭证注入、四个 verb 的分派、把每个调用方可造成的失败变成**值**（`refused` vs `bad_request`） | **moderate**。`handle` 是很干净的深 interface；`_dispatch` 的 70 行是"把 Sweep 翻译成 wire envelope"，属 adapter 职责 |
| `compass.remote`（352 行） | `Remote(arn, region, session)` 的 4 个 verb：`sweep` / `ask` / `decide` / `reset`；`runtime_arn()` | `InvokeAgentRuntime` 调用、session 语义、以及 `_flatten` / `_find` / `_option` 的"finding 按位置寻址" | **mixed**。`Remote` 类本身 moderate（4 个 verb 藏了 wire + session）；`main()`（`:270-352`）是 80 行的 argparse + 报告格式化，interface 是命令行而不是函数 —— shallow |
| `web/app.py`（264 行） | 6 个 HTTP endpoint + `AppState` | SSE 广播（`loop.call_soon_threadsafe`，`:71-77`）、后台线程跑 sweep | **shallow**。module 级 `STATE`（`:64`）是 process-global 状态，没有可测的 interface；`tests/` 下**没有任何 test 覆盖 web/**（已核实：9 个 test 文件，无 `test_web.py`） |

---

## 5. Seam 与职责边界

> 这一节回答一个问题：provider swap（Bedrock → deepseek）发生时，改动是否被限制在应该被限制的地方。判定标准用词汇表：**one adapter means a hypothetical seam, two adapters means a real one**。

### 5.1 model provider seam —— 判决：**seam 是真的，adapter 有三个；但 interface 的边缘有 6 处泄漏**

**先说站得住的部分（这是真成果，不是客套）：**

- `src/compass/llm.py` 是唯一知道"provider"这个概念的地方。全仓 grep（排除 vendor / build / docs）后，`bedrock` / `deepseek` / `openai` / `anthropic` 这几个词**只出现在** `llm.py`、`pyproject.toml` 的依赖与注释、`app/Compass/main.py` 的平台 SDK import（那是宿主不是 provider）、`agentcore/agentcore.json` 的配置、以及 README / 旧架构文档的叙述里。**没有任何 agent、gate、tool、store、model 提到 provider。**
- 三个 adapter 满足同一个 interface（都是 Strands 的 model 对象）：`BedrockModel`（`llm.py:80-89`）、以及 `OpenAIModel` 承载的 deepseek 与 openai（`llm.py:91-125`）。按词汇表，**三 adapter = 真 seam**，不是假 seam。
- 上层只在 `Compass.__init__`（`compass.py:143`）见到 `build_model()`。gate 是纯 Python，根本不经过模型 —— 所以"换 provider 后 gate 判决不变"这句话是**结构上成立**的，不是观察出来的。这是这次 swap 能活下来的根本原因。
- 往上的部署 seam 也做对了：`_load_provider_secret()`（`app/Compass/main.py:99-129`）不硬编码任何 provider 名，只读 `COMPASS_SECRET_PARAMETER` → `COMPASS_SECRET_TARGET` 两个配置；IAM 策略只授一个 ARN（`agentcore/policies/model-key.json`）。

**泄漏清单（按严重度）：**

| # | 位置 | 泄漏了什么 | 后果 |
|---|---|---|---|
| L1 | `llm.py:35` | `DEEPSEEK_KEY_FILE = Path.home() / "lecture-live" / ".deepseek_key"` —— **个人相邻项目的本机路径写进了库代码**，并被 `_deepseek_key()`（`:38-44`）当默认凭证源 | 公开仓库里指向作者的本机目录布局；对任何其他读者是个坏默认值（要么不存在、要么读到别人的 key）。这也是"provider seam"收进了不该收的东西：**凭证从哪来** 与 **用哪个 provider** 是两个决定，现在混在同一个 interface 后面 |
| L2 | `llm.py:47-52` + `:55-64` | `_has_aws_credentials()` 嗅探 `AWS_ACCESS_KEY_ID` / `AWS_PROFILE` / `~/.aws/credentials`，命中就**优先选 bedrock**，排在 deepseek 前面 | provider 由**机器状态**决定而不是由代码决定。在 Owen 本机（有 AWS 凭证）不设 `COMPASS_PROVIDER` 跑本地 demo，会去打 bedrock —— 也就是那个被 Error 002 封掉的账户。README 说"换回去是一个环境变量"（`README.md:500`），字面上对（显式变量优先），但不设时的默认**不是** deepseek |
| L3 | `llm.py:86-89` vs `llm.py:112-125` | 两个 adapter 收到的 params **不对称**：OpenAI-compatible 分支带 `temperature=0, max_tokens=8192`（`:124`），`BedrockModel` 分支什么 params 都没传 | "贪心解码 / 录出来和测出来一样"这条**只属于 deepseek 路径**。同一份代码在 bedrock 上是另一种采样行为。`DEFAULT_BEDROCK_MODEL`（`:30`）也没有任何测试碰过 |
| L4 | `llm.py:121-123` | 注释写明 `max_tokens` 调高是因为 **Sentinel 的输出是多个 finding 的结构化报告** | provider adapter 知道某个 agent 的输出形状。这不是致命耦合（只是注释），但它记录了一条真实依赖：**provider seam 的 payload 上限与 Sentinel 的输出契约互相牵制**，而 Sentinel 的重试（`sentinel.py:282-284`）正是为这个上限写的 |
| L5 | `agentcore/agentcore.json:24-33` + `app/Compass/main.py:115-118` | 凭证注入本身是 provider-agnostic 的（好），但提交的部署配置把 provider 名（`deepseek`）和目标变量名（`DEEPSEEK_API_KEY`）都写成了字面量 | "换 provider"在部署侧要同时改 envVars 和 SSM 参数名，不是纯粹的一个变量 |
| L6 | `pyproject.toml:17,23,27` | `bedrock-agentcore`、`openai`、`boto3` 是**核心依赖**而不是 extra | 三个 provider / 宿主 platform 的实现细节全部常驻依赖图。注释（`:13-15`、`:19-22`）解释了原因（AgentCore 从这份文件解析依赖），理由成立，但这意味着**"Compass 这个 agent"与"AgentCore 这个宿主"之间的 seam 没有被依赖图表达出来** |

**另一处不属于 swap、但属于 provider seam 的风险**：`sentinel.py:281` 依赖 Strands 的 `structured_output_model`。在 bedrock 路径上这通常是原生 tool-use；在 OpenAI-compatible 路径上由 Strands 的 `OpenAIModel` 实现，**其行为在本仓库里没有被任何测试覆盖**（未确认其可靠性）。而 `scan()` 只捕获 `MaxTokensReachedException` 与"没有 structured output"两种情况（`sentinel.py:282-291`）；如果 deepseek 返回的结构不满足 `SentinelReport`，Pydantic 校验会在 `SentinelReport(**report)`（`:291`）处抛 `ValidationError`，**一次不合规的输出会掀掉整个 sweep** —— 包括 gate 本该给出的"R1：置信度不足，保持沉默"这条安全降级。这是本次 swap 后最值得补一个测试的地方。

### 5.2 retriever / data source seam —— 判决：**真 seam，而且"双轨"是有据的；泄漏在数据目录的表达方式**

**站得住的部分：**

- school data 有**两个 adapter**，而且不是两份 implementation：`school_tools.py:230-240` 定义 6 个裸函数，FastMCP 用 `mcp.tool(fn)` 装饰（`school_mcp_server.py:41-42`），Strands 用 `tool(fn)` 装饰（`school_tools.py:240`）—— **同一批函数对象**。这是"two transports is exactly the setup that rots"的正面解法。
- 更聪明的一点：**analysis tools 永远不越协议边界**。`registry.py:62` 把 7 个 analysis tool 直接拼进列表，`registry.py:15-18` 说明了理由（那是 Compass 自己的算术，不是学校的数据；gate 的正确性依赖它们的精确性，MCP server 挂了它们也得活着）。
- 所以实际上存在**两个 data-access seam**：(i) school-data seam（agents 用，2 个 adapter → 真 seam）；(ii) direct-store seam（orchestrator 的算术与 action 用，只有 1 个 adapter → 按词汇表是 hypothetical seam）。**这种"假 seam"在这里是正确的**：它与真 seam 之间存在真实差异（越不越进程、是否允许失败），不是为了将来可能的替换而预留的空洞。

**泄漏：**

- **数据目录不是参数，是进程级环境变量。** 写入点有 2 处（`compass.py:142`、`registry.py:41/52-53`），读取点有 3 处（`school_tools.py:37`、`analysis_tools.py:37`、`actions.py:43`）。MCP 子进程只能靠 env 传递，所以 env 本身是对的；问题是 in-process 路径也走 env，导致：(a) 一个 module "读哪个数据集"这个事实**不在它的 interface 里**；(b) `school_tools.py:43` 的 `reset_store()` 这个纯为测试存在的后门必须公开 —— 这是 shallow interface 的典型症状（为了测试而把内部状态暴露出来）。
- **缓存语义不一致。** `school_tools.store()` 缓存首个实例（`school_tools.py:32-40`），`analysis_tools._store()`（`:36-38`）和 `actions._store()`（`:42-44`）每次调用新建一个 `SchoolStore`。同一件事（"从 env 解析出数据集"）在三个地方有三种说法，这是 §6 D2 的对象。

### 5.3 tool layer seam —— 判决：**放置得很漂亮（授权住在规则旁边，不在能力旁边），但"agent 拿不到 action tool"这条性质只靠构造维持，没有断言**

**站得住的部分（这是本仓库最佳的一处 seam 放置）：**

- `registry.agent_tools` 只发 school + analysis tools（`registry.py:45/62`）。action tools（`actions.py:410-418`）**从不进 agent 的 tool bundle**。模型只能在 `Option.action` 里**提名**一个字符串（`models.py:200`），执行权在 `Compass.execute`（`compass.py:192`），而无监督执行权在 `gate.AUTO_ACT_PERMITTED`（`gate.py:97`）。
- 白名单住在 policy module 而不是 capability module —— `gate.py:88-97` 的注释把这件事讲透了："`compass.tools.actions` can do many things; which of them may run without asking is a decision about the student, and that decision lives here." 这是把 authorization 与 correctness 分开的教科书式做法。**这解释了为什么 `sentinel.py:98-107` 那个 prompt bug（把 €45 图书费误判为 `needs_human_choice: false`）没能变成一次自动支付**：R4 不信任模型的 `needs_human_choice`，它只问"这个 resolution 在不在白名单上"（`gate.py:152-170`）；不在，就降级成"问一下"。
- `actions.py:19-22` 同样把这条纪律写进了 module docstring："These functions are capability, not policy."

**这个 seam 的问题：**

- **关键不变量没有测试。** `tests/test_gate.py:185-187` 断言了 `AUTO_ACT_PERMITTED ⊆ ACTION_BY_NAME`（白名单里的动作都真的存在），`tests/test_actions.py:257` 钉住了 action 名的集合 —— 但**没有任何测试断言 `agent_tools` 的返回里不含 action tools**。把 `ACTION_TOOLS` 加进 `registry.py:45` 的列表，或者哪天有人"顺手"把 actions 也接进去，套件不会响。这是"the interface is the test surface"的反面案例：这条安全性质目前只活在两行列表推导里。
- **同一个集合被列举三次**：`ACTION_TOOLS`（`actions.py:410`）、`ACTION_BY_NAME`（`:422`）、`__all__`（`:424-435`）。`SPECIALISATION_MODULES` 也双向引用（定义在 `audit.py:38`，被 `actions.py:37` 导入并从 `__all__` re-export）。drift 面不大，但没有单一来源。
- **执行的步骤语义在两个 module 里各推导一遍**（`gate.auto_chain` `:100-111` 与 `Compass.execute` `:204,220-221`）。这是 §6 D1。

### 5.4 三条 seam 的一句话总结

| seam | adapter 数 | 真 / 假 | 判决 |
|---|---|---|---|
| model provider（`llm.py`） | 3（bedrock / deepseek / openai） | 真 | **通过**。换 provider 只碰一个 module；泄漏 6 处，最重的是 `llm.py:35` 的本机 key 路径与 `:47-64` 的机器状态决定 provider |
| school data（`school_tools.py` + `registry.py`） | 2（MCP stdio / in-process `@tool`） | 真 | **通过**，且同函数对象双装饰是正确解法。泄漏在数据目录靠进程 env 表达 + 三份重复的 store 解析 |
| tool capability（`actions.py` vs agent bundle） | 1（能力只有一份，policy 是另一份） | 假 seam，但正确 | **方向对，护栏缺**。授权住在 policy 侧是最大的架构正确；"agent 拿不到 action tool"没有测试盯着 |
| deployment host（`app/Compass/main.py`） | 2（本地 CLI / AgentCore runtime） | 真 | **通过**。`handle()` 是纯函数，所以部署契约可以脱离 runtime 测（`tests/test_runtime.py` 11 个 test 用 stand-in agent） |

---

## 6. 摩擦与深化机会

按"收益 / 成本"排序。每条给出 module、为什么 shallow（附 deletion test）、更深的 interface、payoff。**只列真正有 friction 的，按 YAGNI 排序。**

### D1 ⭐ 把"option → 有序执行步骤"的知识收到一个 module

- **module**：`gate.auto_chain`（`gate.py:100-111`）与 `Compass.execute`（`compass.py:204`、`:220-221`）
- **为什么 shallow**：同一条规则（"一个 option 的执行顺序是 `after` 然后 `action`；`after` 不带参数，`action_args` 属于 `action`"）被推导了**两遍**。policy 侧用它判授权（`set(chain) <= AUTO_ACT_PERMITTED`），execution 侧用它真执行。两边必须永远一致，但没有任何东西保证 —— 它是一个**隐式 interface**，只活在注释里（`models.py:196-207` 和 `compass.py:218-219` 各写了一遍"`after` 不接收自己的参数"）。
- **deletion test**：删掉任何一边，另一边不会报错，只是行为悄悄分叉（例如将来给 `after` 加参数支持，只改一处就够通过所有测试，而在另一处失效）。
- **更深的 interface**：`steps_for(option) -> list[Step]`，`Step = (name, args)`。`gate.auto_chain` 改成对 `steps_for(...)` 取名字做白名单判定；`Compass.execute` 改成对 `steps_for(...)` 循环执行。
- **payoff**：**locality**（`after` 的语义改一处）；**leverage**（gate 的 20 个 test 与 orchestrator 的 15 个 test 现在压在同一份语义上，测试面从两个变成一个纯函数）；顺带消掉 `_option()`（`compass.py:79-91`）与 `gate.auto_chain` 里两份"取 recommended、否则取第一个"的推导（`compass.py:91` vs `gate.py:109`）。

### D2 ⭐ 数据目录与 store 构造的唯一入口

- **module**：`school_tools.store`（`school_tools.py:32-46`）、`analysis_tools._store`（`analysis_tools.py:36-38`）、`actions._store`（`actions.py:42-44`），加上两个 env 写入点（`compass.py:142`、`registry.py:41/52`）
- **为什么 shallow**：三份重复的 `env → SchoolStore` 解析，**语义还不一致**（第一份带模块级缓存，另两份每次新建）。而"这个 module 读哪个数据集"根本不是签名里的参数，是进程环境 —— 所以它真实的 interface 一半在签名里、一半在 `os.environ` 里。
- **deletion test**：删掉 `reset_store()`，复杂度**不会**转移到 7 个 analysis tool 上，而是逼出一个更诚实的 interface（"构造时接受数据目录、不做全局缓存"）—— 这是"yes, concentrates"的信号。反过来，删掉三份 `_store()` 中任意一份，复杂度只是被搬到另外两份里 —— 那是"just moves it"，说明它们现在是纯重复。
- **更深的 interface**：一个 `dataset(data_dir=None) -> SchoolStore`，内部**唯一**决定 env 读取与缓存策略；MCP 子进程的 env 传递只允许发生在 `registry.agent_tools` 这一个地方（现在也是两处，`registry.py:41` 和 `:52-53`）。
- **payoff**：**locality**（数据集语义一处）；**可测**（不需要 `reset_store()` 这个测试后门，因为它存在的唯一理由就是全局缓存）；顺带修掉一个真实的潜伏 bug —— `school_tools.store()` 的缓存意味着同一个进程内先读 A 数据集再切到 B 数据集时会读到 A（只有显式 `reset_store()` 能纠正；MCP 子进程每次新建所以掩盖了它）。

### D3 ⭐ Sweep 的 wire 契约与 finding 寻址只定义一次

- **module**：`app/Compass/main.py` 的 `_dispatch`（`:183-257`）、`web/app.py` 的 `/api/decisions`（`:127-140`）与 `_run_sweep`（`:157-169`）、`remote.py` 的 `_flatten` / `_find` / `_option`（`:151-224`）
- **为什么 shallow**：
  1. 同一个 `Sweep` 被序列化成**两种** envelope —— runtime 一种（`main.py:186-222`），web 一种（`web/app.py:131-139`）。只有 runtime 那种被 `tests/test_remote.py`（18 个 test）钉住；web 那种**一个测试都没有**（`tests/` 下无 `test_web.py`，已核实）。
  2. **两张皮对 finding 的寻址约定正相反**：`remote.py:162-174` 明确拒绝用 id（"Ids are written by the model on every sweep, so the same finding can be named differently on two runs"），改用位置；而 `web/app.py:166` 恰恰用 `d.finding.id` 当 dict 的 key —— 模型一旦两次吐出同一个 id，第二张卡会被**静默覆盖**。同一份数据、两个前端、两个矛盾的寻址契约。
  3. `remote._report_sweep` 靠 `is` 比较已解析的 JSON 对象来算序号（`remote.py:236-241`），并且每次都要重跑一遍 `_flatten`（O(n²) 且依赖两次调用产生同一批对象引用）。
- **deletion test**：删掉 `_flatten`，复杂度会分散到 `_find`、`_option`、`_report_sweep`、以及（应该存在的）web 侧 —— "yes, concentrates"。
- **更深的 interface**：`Sweep.index() -> list[IndexedFinding]`（位置 + finding + verdict + 是否 surfaced），一个 module 定义"一张卡怎么被寻址、怎么被序列化"；runtime 与 web 都从它渲染，`remote` 从它解析。
- **payoff**：**locality**（寻址语义一处，两个前端不可能再分叉）；**leverage**（两个前端 + 4 个 verb 共用）；**可测**（web 层第一次拥有一个不需要 HTTP 的纯函数）。

### D4 把 provider 的 machine-local 残渣移出 `llm.py` 的 interface

- **module**：`compass.llm`（`llm.py:35`、`:38-44`、`:47-64`）
- **为什么 shallow / 有摩擦**：interface 太小而收进了不该收的决定 —— `~//lecture-live/.deepseek_key` 是一条本机约定，`_has_aws_credentials()` 让 provider 由机器状态决定。两者都属于"开发便利"，却坐在库的 interface 后面（`describe()` 会把结果打进 UI：`web/app.py:105`）。
- **更深的 interface**：`build_model(provider=None, model_id=None)` 保持显式；凭证发现降级为"只读标准环境变量"，本机 key 文件那条路径挪到调用方（CLI / entrypoint extra）或删掉。这样"选 provider"与"凭证从哪来"也能分开。
- **payoff**：**locality**（provider 的默认值不再依赖谁在哪台机器上跑）；**可测**（`resolve_provider()` 变成可以直测的纯优先级表，而不是要 monkeypatch `HOME` 才可控 —— 现在 `tests/conftest.py:56-68` 正是为此存在的）；公开仓库不再把人名/本机布局带出去。

### D5 收拢偏 shallow 的 adapter / 列举层（优先级低，Speculative）

- `analysis_tools` 的 7 个 tool 各自重复 store 解析与 JSON 投影（`analysis_tools.py:36-38` + 每个函数体）。**但注意**：它的调用方是模型，7 个窄 tool 比 1 个宽 tool 对模型更友好 —— **不要**为了"看起来更深"把它合并成一个 `analyze(kind=...)`，那会把 interface 的复杂度推给 prompt。
- `actions.py` 的三重列举（`:410`、`:422`、`:424-435`）与 `SPECIALISATION_MODULES` 的 re-export（`:37`）：可以留一份 `ACTION_TOOLS`，其余由它派生。
- `remote.py:270-352` 的 80 行 CLI：interface 是 argparse 而非函数。除非要重用，否则不值得动。
- `web/app.py` 的 `STATE`（`:64`）：module 级 process-global，没有 interface 可测。如果要给 web 层补测试，第一步是把 `AppState` 变成可注入的参数，而不是去 mock FastAPI。
- `store._write_atomic`（`store.py:59-70`）原子写，而 `data/generate.write_all`（`generate.py:431`）用裸 `write_text` —— 两个写同一批文件的 module，写纪律不一致。生成器只在一个 setup 步骤里跑，所以是可接受的不一致，但值得写进注释。

---

## 7. 风险与债务

### 7.1 正确性

- **R1｜一次不合规的结构化输出会掀掉整个 sweep（最高优先级）。** `scan()`（`sentinel.py:277-296`）只兜住 `MaxTokensReachedException` 与 `structured_output is None`；`SentinelReport(**report)`（`:291`）抛出的 `ValidationError` 不在捕获范围内。后果不是"少一个 finding"，而是**连 R1（低置信度→沉默）这条安全降级都拿不到**：`Compass.sweep` 直接抛，runtime 的宽 except（`main.py:273`）把它变成 `{"ok": false, "kind": "error"}`。**并且换到 deepseek 之后这条路径的暴露面变大了**（见 §5.1 末尾：`structured_output_model` 在 OpenAI-compatible adapter 上的行为在本仓库里没有测试覆盖）。
- **R2｜id 作为主键的两处不一致（D3）**：`web/app.py:166` 用模型编的 `finding.id` 当 dict key，而同仓库的 `remote.py:162-174` 明确论证过不能这么做。两个 id 相同即静默丢卡。
- **R3｜没有 lockfile**：`pyproject.toml` 全是 `>=`；部署是 CodeZip，每次 deploy 解析出的依赖可能不同。对一个"演示必须可复现"的项目，这是可复现性上的一个缺口（`tests/` 不依赖网络，所以本地测试不受影响）。
- **R4｜`write_all` 与 `_write_atomic` 写纪律不一致**（`generate.py:431` vs `store.py:59-70`）。低危：生成器只在 setup / `reset` 时跑。好消息是 `write_all` 会删掉旧的 `receipts.jsonl`（`generate.py:437-439`），所以 reset 后 receipt 与记录不会不一致 —— 这一点是对的。

### 7.2 portability

- **R5｜"换 provider 是一个环境变量"这句话要打个折。** 代码路径确实是一条（§5.1），但**行为**不是：`temperature=0` / `max_tokens=8192` 只在 OpenAI-compatible 分支（`llm.py:124`），Bedrock 分支没有 params（`:86-89`）；`DEFAULT_BEDROCK_MODEL`（`:30`）无测试；`structured_output_model` 的实现在两个 adapter 上不同。所以切回 bedrock 会改变**确定性、截断行为、以及结构化输出的可靠性** —— 而这三样恰好是"demo 和测试是同一个东西"这个卖点的支柱。
- **R6｜provider 由机器状态决定**（`llm.py:47-64`）：有 AWS 凭证的机器默认走 bedrock。Owen 本机就是这种机器，所以"本地跑一下什么都别设"会去撞被封的账户。修法很便宜：把默认改成"没有显式 `COMPASS_PROVIDER` 就不猜"，或把 bedrock 的嗅探降到最后。
- **R7｜`~/lecture-live/.deepseek_key`**（`llm.py:35`）：公开仓库 + 私人相邻项目路径。既是坏默认值，也是本机布局的信息泄漏（轻度）。测试靠 `HOME` 重定向躲开（`conftest.py:68`），意味着**只有测试环境是安全的**。
- **R8｜宿主 platform 是核心依赖**：`bedrock-agentcore`、`aws-opentelemetry-distro`、`boto3`、`openai` 都在 `[project.dependencies]`（`pyproject.toml:17-27`）。注释解释了原因（AgentCore 从这份文件解析依赖），但对"Compass 这个 agent"来说，装它就得装三个 provider 的 SDK 和一个云厂商宿主。**agent 与 host 之间的 seam 没有出现在依赖图里**。
- **R9｜提交的部署状态**：`agentcore/.cli/deployed-state.json` 被 `.gitignore` 显式豁免而入库（`agentcore/.gitignore:15`），含账号 id 与 runtime ARN。账号 id 不是密钥，但它会 stale；`remote.py:73-76` 特意不去读这个文件（改用 control plane 按名查）—— 这个判断是对的，值得保持。

### 7.3 provider swap 的后果（专项）

**积极的**：swap 被限制在一个 144 行的 module 里，并且**产品主张本身对 provider 免疫** —— 因为打断决策由 `gate.py` 的纯 Python 做出，模型只提供事实。这条设计在 swap 前就存在（不是为 swap 而做的），但 swap 是它的第一次实战验证，结果是通过。

**消极的 / 未验证的**：
1. **只有 deepseek 路径在跑，但没有 deepseek 的契约测试。** `tests/` 从不调用模型（`conftest.py:1-10` 与 `test_orchestrator.py` 用注入的 findings 绕过模型），所以"deepseek 能不能稳定产出满足 `SentinelReport` 的结构化输出"这件事，**只有 `docs/VIDEO.md` 里的手工演示在证明**。`README.md:516` 声称测试 132 passed —— 那是**不碰模型的** 132 个。
2. **R1 的暴露面因此放大**：结构化输出是整条链上唯一"没有 gate 兜底"的环节。gate 能兜住模型的**判断**错误（R1-R6），兜不住模型的**格式**错误。
3. **bedrock 路径成了未测试的代码**：`DEFAULT_BEDROCK_MODEL`、`BedrockModel(...)` 的构造、以及 `region_name` 的解析在 `tests/` 里没有任何覆盖（`test_runtime.py` 用 stand-in agent，`test_data.py` 走裸文件）。如果 AWS 解封、切回 bedrock，第一个问题不会出现在 gate 上而会出现在这里。
4. **叙述与配置的漂移**：`agentcore/agentcore.json:25` 是 `deepseek`，`README.md:8` 挂着 AgentCore 徽章、`:286-287` 的致谢表把 Bedrock 列为"First-class model backend (Claude)"，`:489-500` 解释 swap。叙事层次本身是诚恳的，但对一个只读代码的人，"这个项目跑在什么模型上"要读三处才能确定。
5. **build bundle 里有一份文档副本**：`agentcore/.cache/Compass/staging/`（未入 git，`agentcore/.gitignore:12`）含 `README.md` / `ARCHITECTURE.md` 的旧副本。这是 vendor CLI 的缓存，不是债务，但说明了 bundle 包含文档 —— 别人读到的可能是旧版。

---

## 8. 一页速览

**动这个仓库之前必须知道的事。**

| 位置 | 角色（它提供的 interface） | depth | 动它之前 |
|---|---|---|---|
| `src/compass/gate.py` | `decide()` / `decide_all()` / `AUTO_ACT_PERMITTED` —— 唯一的"要不要打断"决策者 | **deep** | 纯函数，无 I/O / 无时钟 / 无随机。改规则顺序会改变语义（R1-R6 是**有序**的）。R6 是通向学生的唯一路径。不要在这里引入 model 调用 |
| `src/compass/models.py` | `Finding` / `Option` / `Receipt` / `GateDecision` 等全部契约 | 契约 | `Finding` **故意没有** `should_surface` 字段。`Option.after` 是"强制第一步、不接收参数"。改字段等于改模型与 policy 之间的 seam |
| `src/compass/llm.py` | `build_model()` / `describe()` / `resolve_provider()` | **deep（有泄漏）** | 唯一知道 provider 的 module。⚠️ `:35` 硬编码本机 key 路径；`:47-64` 有 AWS 凭证就默认 bedrock（不是 deepseek）；`:124` 的 `temperature=0` 只在 OpenAI-compatible 分支 |
| `src/compass/agents/compass.py` | `Compass.sweep()` / `.execute()` / `.ask()`；`Sweep` | **deep** | `sweep(findings=[...])` 是给测试用的真 seam（不传就调模型）。`:142` 会写 `COMPASS_DATA_DIR` 到进程环境。`execute()` 是唯一的无监督副作用入口，只有两处能到它：gate 的 R4 和一次点击 |
| `src/compass/tools/actions.py` | 7 个 `@tool` + `ACTION_BY_NAME` | **deep** | 是 capability，不是 policy。**先全部校验、再任何 mutation**（否则 demo 在说谎）。action 名集合被列举三次（`:410/:422/:424`） |
| `src/compass/tools/registry.py` | `agent_tools(use_mcp, data_dir)` context manager | **deep** | 决定 agent 拿得到哪些 tool —— **action tools 绝不进这个列表**（这条不变量没有测试盯着）。analysis tools 永远直连，不走 MCP |
| `src/compass/tools/school_tools.py` | 6 个裸函数（签名即 schema，docstring 即 tool 描述） | moderate | 两个 transport 装饰**同一批函数对象**，不要在这里分叉出第二份实现。`store()` 有模块级缓存（`:32-40`），`reset_store()` 是测试后门 |
| `src/compass/tools/analysis_tools.py` | 7 个算术 tool（`audit_degree_plan` / `compare_specialisations` / …） | shallow→moderate | 算术在 `audit.py` / `prereq.py`，这里只做投影。`compare_specialisations` 区分"今天能选"与"绕一步还能补上"—— 别把它简化成前者。每个函数自己解析 store（`:36-38`） |
| `src/compass/audit.py` / `prereq.py` | 规则 1/2 与先修图 | **deep** | 纯函数。`MAX_TERM_CREDITS=30`（`audit.py:32`）与 `SPECIALISATION_MODULES`（`:38`）是课程知识，别复制到别处 |
| `src/compass/store.py` | `SchoolStore` 读写 + `take_seat` | **deep** | **没有缓存，每次重读**（跨进程可见性）。写一律原子。`take_seat` 必须从新读的副本改，改 `course()` 的返回值是空操作 |
| `src/compass/agents/sentinel.py` | `build_sentinel()` / `scan()`；~200 行 prompt | moderate | 它**只报事实**，不做"要不要打断"的判断。prompt 里三条教训（别把一个 root cause 拆成三张卡 / €45 不是"无选择" / 别报已经解决的事）都是测试逼出来的，删之前先读旧架构文档 §3 |
| `src/compass/agents/pathfinder.py` / `explainer.py` | prompt 容器 + `explore()` / `explain()` | shallow（刻意） | "绝不在脑子里算数" / "引用，不要猜"。`explore`/`explain` 是纯 pass-through，保留是为了三个 specialist 的 interface 对称 |
| `app/Compass/main.py` | `handle(payload, compass)`（纯函数）+ `invoke()` | moderate | `handle` 可无 runtime 测试，改部署契约要先改它。`:46-59` 必须同时设 `sys.path` **和** `PYTHONPATH`（MCP 是子进程，只继承环境）。`decide` 要求调用方把 finding 整体传回来 —— 授权来自点下去的人，不是来自产生它的 sweep。**每个调用都重建 `Compass`**（`:272`） |
| `web/app.py` | 6 个 endpoint + 模块级 `STATE` | **shallow** | ⚠️ **无测试覆盖**。`STATE.decisions` 用模型编的 `finding.id` 当 key（`:166`）—— 与 `remote.py` 的位置寻址约定相反。sweep 跑在后台线程，SSE 经 `call_soon_threadsafe` 广播 |
| `src/compass/remote.py` | `Remote` 的 4 个 verb（sweep/ask/decide/reset） | mixed | 是 client，agent 不 import 它。**finding 按位置寻址，不按 id**（`_find` `:162`）。`decide` 必须复用 sweep 的 session |
| `src/compass/data/generate.py` | `write_all(out_dir)` / `DEMO_TODAY` | moderate | **确定性**（跑两次逐字节相同，有测试）。`demo_today` 固定在 `2026-09-28`，所有"还剩几天"都相对于它。会删掉旧的 `receipts.jsonl`（`:437-439`） |
| `tests/conftest.py` | 三个 fixture + 一个 autouse 凭据剥离 | — | 每个测试自己生成数据集到 tmp，**从不读仓库里的 `data/`**。autouse fixture 剥掉 `AWS_PROFILE` / `COMPASS_PROVIDER` 并把 `HOME` 指向 tmp（`:56-68`）—— 改 `llm.py` 的凭证发现会立刻影响它 |
| `agentcore/agentcore.json` | 部署声明 | — | `codeLocation: "./"`（**仓库根**）、`COMPASS_PROVIDER=deepseek`（`:25`）、`COMPASS_SECRET_TARGET=DEEPSEEK_API_KEY`（`:33`）。换 provider 要同时动这里和 SSM |

**一句话给未来的 agent**：这个项目的架构核心不是"用了 Strands"，而是**授权住在 policy（`gate.py`）而不是住在 capability（`actions.py`）**。任何改动只要削弱"模型只能报事实、代码才能决定打断、白名单外的动作一律问人"这三条，就算测试全绿也是错的。
