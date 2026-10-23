# CodeAtlas · 计算机知识库智能体

> 让 AI 走完一条**有出处、可追问、可验证**的学习路径。

面向计算机专业学生与后端求职者，知识库覆盖**后端（JVM / 并发 / MySQL / Redis / Spring / 网络 / 分布式）**与 **AI（LLM 基础 / RAG / Agent / 向量检索 / Prompt 工程）**两个域。不是又一个 AI 聊天框 —— 它会先规划要查什么、查几次，检索后自评证据是否足够，不够就改写查询重查，最后给出**逐句可溯源**的答案，并在知识图谱上点亮推理路径。

**它最特别的一点**：图谱里存在**跨域边**。当你问「向量检索为什么不能用 B+ 树加速」，它会把 AI 域的「HNSW」和后端域的「B+ 树」用一条虚线连起来 —— 纯向量检索做不到这件事，因为它不知道这两段知识该放在一起对比。

---

## 它解决什么问题

| 痛点 | 现有工具的失败之处 | CodeAtlas 的做法 |
|---|---|---|
| 八股答案碎片化、无法验证真伪 | 聊天框给不出「这句话出自哪本书第几节」 | claim 级引用，点角标跳原文高亮 |
| 知识点孤立，面试官追问一层就崩 | 单轮问答不会主动补上下文 | 多跳检索 + 知识图谱邻居扩展 |
| **后端和 AI 的知识各学各的，连不起来** | 向量检索按语义相似度召回，召不回「关系」 | **跨域边**：图谱显式记录两个学科间的对比/依赖关系 |
| 不知道自己的理解对不对 | 没有反馈闭环 | 出题器从图谱抽知识点，按引用评分 |

---

## 架构

```
浏览器 (React SPA)
      │  SSE (fetch + ReadableStream)
      ▼
┌─────────────────────────────┐
│ Java Gateway  :8080         │  唯一对外入口 /api/**
│ 会话·消息·文档元数据          │  SSE 透传 + 落库 + 断线续传
└──────────┬──────────────────┘
           │ HTTP SSE（内网，X-Internal-Token）
           ▼
┌─────────────────────────────┐
│ Python Agent  :8000         │  仅暴露 /internal/**
│ Agent 状态机 · 检索层 · 摄入 │
└──────────┬──────────────────┘
           ▼
   Postgres 16 + pgvector
```

详细设计见 [`contracts/`](contracts/) 与 [`docs/tech-doc/`](docs/tech-doc/)。

---

## 10 分钟极速复现

> 🚧 完整复现指南在 P5 阶段补齐。当前已完成数据库层，可独立验证。

三条路径，任选其一：

| 路径 | 前置条件 | 适合 |
|---|---|---|
| **A. 全量 Docker** | Docker Desktop | 完整体验（推荐） |
| **B. 前端 Mock 回放** | 只需 Node | 无网、无 Key 也能看完整交互 |
| **C. 在线 Demo** | 浏览器 | 最快 |

### 当前可用：数据库层

```bash
cp .env.example .env
docker compose up -d          # 只起 postgres + pgvector
```

验证建库是否正确（在一个事务里跑完并回滚，不留脏数据）：

```bash
docker exec -i codeatlas-db psql -U codeatlas -d codeatlas \
  -v ON_ERROR_STOP=1 -f - < db/smoke-test.sql
```

期望输出 5 个 ✓：向量写入、跨域边查询、外键约束、唯一约束、自环约束。

> ⚠️ `contracts/db-schema.sql` 只在数据卷为空时执行。改了 schema 要重建：
> `docker compose down -v && docker compose up -d`

### 当前可用：Agent 服务（Mock 模式）

P0 阶段不接真实模型，先跑通 SSE 协议。**不需要 API Key。**

```bash
cd services/python-agent
uvicorn app.main:app --reload --port 8000
```

健康检查（`db` 应为 `ok`，`llm` 为 `missing_key`，`mode` 为 `mock`）：

```bash
curl -H "X-Internal-Token: $INTERNAL_TOKEN" http://127.0.0.1:8000/internal/health
```

看完整事件流（51 个事件，约 2 秒）：

```bash
curl -N -X POST http://127.0.0.1:8000/internal/agent/stream \
  -H "X-Internal-Token: $INTERNAL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"trace_id":"t_demo","question":"向量检索为什么不能用 B+ 树加速？"}'
```

跑协议一致性测试（13 个用例，守住 `contracts/sse-events.md` 的 5 条顺序保证）：

```bash
cd services/python-agent && pytest -v
```

### 当前可用：Java 网关

```bash
# ⚠️ 必须先加载 .env，否则数据库密码用的是 application.yml 里的占位默认值，连不上
set -a && source .env && set +a
cd services/java-gateway && mvn spring-boot:run
```

端到端验收（健康检查 → SSE 流 → 落库，三段全过才算 P0 完成）：

```bash
python scripts/e2e_check.py
```

**排障提示**

| 现象 | 原因 | 处理 |
|---|---|---|
| Tomcat 起在随机端口、报 `already in use` | 环境里存在 `SERVER_PORT` 变量，优先级高于 `application.yml` | 显式传 `-Dspring-boot.run.arguments=--server.port=8080` |
| 数据库连接失败 | 忘了 `source .env`，用了 yml 里的占位密码 | 启动前先 `set -a && source .env && set +a` |
| HTTP 200 但前端收不到事件 | SSE 帧 `event:step` 与 `event: step` 两种写法只认了一种 | 解析器必须容忍冒号后有无空格，见 `contracts/sse-events.md` |

### 路径 A：全量 Docker（P3 后可用）

```bash
docker compose --profile app up -d
# 打开 http://localhost:5173
```

数据库镜像将内置知识库快照（含 embedding），**不需要重新建库，不需要 API Key 也能看到完整数据**。

### 路径 B：前端 Mock 回放（P3 后可用）

```bash
cd web && npm install && VITE_MOCK=1 npm run dev
```

前端加载预录的 SSE 事件流（`web/src/mock/stream.jsonl`），完整复现演示视频里的每一个交互。

---

## 技术栈

Spring Boot 3.5 · MyBatis-Plus · FastAPI · SQLAlchemy 2.0 · Postgres 16 + pgvector
React 18 · Vite 6 · TypeScript · Tailwind 3.4 · react-force-graph
DeepSeek V4.1-Flash · BGE-M3 · bge-reranker-v2-m3

---

## 开发进度

- [x] P0 骨架与契约
- [ ] P1 知识库摄入与检索基线
- [ ] P2 Agent 状态机
- [ ] P3 前端视觉
- [ ] P4 打磨
- [ ] P5 参赛材料

---

## 数据来源与许可

本项目知识库仅使用**明确开源协议**的资料，原始文件不随仓库分发，由 `scripts/fetch_sources.py` 按 `sources.manifest.yaml` 拉取。

| 来源 | 域 | 许可证 | 入库方式 |
|---|---|---|---|
| JavaGuide（Snailclimb） | 后端 | **Apache-2.0** | 全文 |
| MySQL 8.0 Reference Manual | 后端 | 官方文档 | 结构化摘录 |
| Redis Documentation | 后端 | 官方文档 | 结构化摘录 |
| Qdrant Documentation | AI | **Apache-2.0** | 全文 |
| Prompt Engineering Guide（DAIR.AI） | AI | **MIT** | 全文 |
| HNSW 原论文（Malkov & Yashunin, arXiv:1603.09320） | AI | arXiv 预印本 | 结构化摘录 + 链接 |
| RAG 原论文（Lewis et al., arXiv:2005.11401） | AI | arXiv 预印本 | 结构化摘录 + 链接 |
| Anthropic《Building Effective Agents》 | AI | 版权归 Anthropic | 结构化摘录 + 链接 |
| Lilian Weng《LLM Powered Autonomous Agents》 | AI | 版权归作者 | 结构化摘录 + 链接 |
| The Illustrated Transformer（Jay Alammar） | AI | 版权归作者 | 结构化摘录 + 链接 |
| LlamaIndex《Production RAG》 | AI | 官方文档 | 结构化摘录 + 链接 |
| 本人学习笔记（4 篇） | 后端 / AI | 原创 | 全文 |

**入库方式说明**：只有 Apache-2.0 / MIT 这类允许全文使用的源才整篇入库；其余一律只保留**自己重写的结构化摘录 + 原文链接**，不转存原文。这样既规避版权风险，也让知识库内容本身构成原创。

原始文件**不随仓库分发**，由 `scripts/fetch_sources.py` 按 [`sources.manifest.yaml`](sources.manifest.yaml) 拉取。

> 注：本清单刻意**未采用 CS-Notes**——它的许可证是 CC BY-NC-SA 4.0，含「不可商用」与「相同方式共享」条款，与参赛作品的授权方式存在冲突。JavaGuide（Apache-2.0）已覆盖后端各学科，无需它补充。

署名与完整清单见 [`sources.manifest.yaml`](sources.manifest.yaml)。

---

## 参赛信息

2026 传智杯 · 全国高校 Vibe Coding 开发挑战赛 · 省赛 · B 组
开发过程与 Prompt 记录见 [`docs/prompts/`](docs/prompts/)。
