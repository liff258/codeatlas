# CLAUDE.md — CodeAtlas 项目约定

> 本文件是给 AI 助手（以及我自己）的项目级上下文。每次让 AI 改代码前，先把它完整贴进去。
> 它是「意图控制策略」的一部分，会作为技术文档的附录提交。

---

## 1. 项目是什么

**CodeAtlas**：面向计算机专业学生与 Java 后端求职者的计算机知识库智能体。
不是「问 AI 要答案」，而是让 AI 走完一条**有出处、可追问、可验证**的学习路径。

核心能力：文档摄入 → 多跳检索 → 自评改写 → 带引用生成 → 知识图谱可视化。

---

## 2. 架构不变量（违反即为 Bug，不接受任何"临时绕过"）

1. **依赖单向**：`浏览器 → Java Gateway → Python Agent`。Python **永远不回调** Java，Python 不知道 Java 存在。
2. **表所有权隔离**：单库 Postgres，但两侧各写各的表，禁止双写同一张表。
   - Java 写：`session` `message` `document` `ingest_task` `feedback` `eval_run`
   - Python 写：`chunk` `chunk_embedding` `entity` `relation` `agent_trace` `agent_step` `eval_case` `eval_result`
   - 完整定义见 `contracts/db-schema.sql`，该文件是唯一真相
   - 唯一交叉点：`document.status` 只由 Python 更新，Java 只读。
3. **契约先行**：任何跨服务接口变更，先改 `contracts/` 下的文件，再改实现。契约是唯一真相。
4. **SSE 只能用 `fetch + ReadableStream` 解析**。禁止 `EventSource`（它只支持 GET，问题文本放不进 URL）。
5. **禁止引入 `contracts/deps.md` 依赖清单之外的第三方库**。需要新库先写进清单并说明理由。
6. **`.env` 永不提交**。新增配置项必须同步加到 `.env.example`。

---

## 3. 目录结构

```
p1/
├─ contracts/           # 唯一真相：接口契约、SSE 协议、DB schema
│  ├─ openapi.yaml
│  ├─ sse-events.md
│  ├─ db-schema.sql
│  └─ deps.md
├─ docs/
│  ├─ prompts/          # Prompt 日志（25% 复现性分数的直接证据）
│  └─ tech-doc/         # 技术文档草稿
├─ services/
│  ├─ java-gateway/     # Spring Boot 3.5.x，对外唯一入口
│  └─ python-agent/     # FastAPI，Agent 编排 + 检索
├─ web/                 # React 18 + Vite 6
├─ db/                  # 初始化 SQL、快照 dump
└─ docker-compose.yml
```

---

## 4. 技术栈（版本已锁，不要擅自升级）

| 层 | 选型 | 版本 |
|---|---|---|
| Java | Spring Boot + MyBatis-Plus | 3.5.x / 3.5.9 |
| SSE 客户端 | Spring WebFlux `WebClient` | 随 Boot |
| Python | FastAPI + uvicorn | Python 3.11(Docker) / 3.13(本地) |
| ORM | SQLAlchemy + psycopg | 2.0 / 3.x，**同步 Session** |
| 前端 | React + Vite + TS | 18 / 6 / 5.6 |
| 状态 | Zustand + TanStack Query | 5 / 5 |
| 样式 | Tailwind + shadcn/ui | **3.4**（不要用 4） |
| 图谱 | react-force-graph-2d | 1.2x |
| DB | Postgres 16 + pgvector | pgvector 0.8 |

---

## 5. 编码约定

### Python
- 分层：`api/`（路由）→ `agent/`（状态机节点）→ `rag/`（检索）→ `infra/`（DB、LLM 客户端）
- 每个节点函数签名统一：`def node_xxx(state: AgentState) -> AgentState`，**纯函数式，不在这里做 IO 之外的副作用**
- 所有 LLM 调用走 `infra/llm.py` 的统一封装，禁止在业务层直接 `import openai`
- 结构化输出用 `pydantic` 模型校验，**解析失败必须降级而不是抛异常**（降级策略见 `agent/degrade.py`）

### Java
- 分层：`controller` → `service` → `client`（调 Python）→ `mapper`
- 对外统一返回 `Result<T>` 包装；异常走 `GlobalExceptionHandler`
- 调 Python 一律通过 `AgentClient`，不要在 controller 里直接用 WebClient

### 前端
- 组件分 `components/ui`（shadcn 原子）与 `components/feature`（业务）
- 流式状态只放 Zustand，**不要放 React state**（高频更新会掉帧）
- 所有动效必须可被 `prefers-reduced-motion` 关闭

---

## 6. 提交规范

```
feat(agent): 增加相关性自评节点 [prompt#012]
fix(sse): 修复 Nginx 缓冲导致流式阻塞 [prompt#031]
docs(prompts): 归档 10-25 检索调参对话 [prompt#044]
```

- 每次提交只做一件事，**禁止一次性提交多个不相关功能**
- commit message 必须带 `[prompt#NNN]`，指向 `docs/prompts/` 下对应的日志
- 每天 3–8 次提交，宁碎不全

---

## 7. 给 AI 的固定提示词前缀

> 在本项目写代码时，你已阅读 CLAUDE.md。请遵守其中的架构不变量。
> 改动前先确认：涉及哪一层？是否会破坏表所有权隔离？是否需要先改 contracts/？
> 不要引入新依赖，不要改动版本号，不要写 `EventSource`，不要在 Python 里做异步 Session。
