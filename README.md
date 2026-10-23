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

> 🚧 本节在 P5 阶段补齐完整内容。目标：评委无需申请 API Key 也能跑通全部演示。

三条路径，任选其一：

| 路径 | 前置条件 | 适合 |
|---|---|---|
| **A. 全量 Docker** | Docker Desktop | 完整体验（推荐） |
| **B. 前端 Mock 回放** | 只需 Node | 无网、无 Key 也能看完整交互 |
| **C. 在线 Demo** | 浏览器 | 最快 |

### 路径 A：全量 Docker

```bash
git clone <repo-url> && cd codeatlas
cp .env.example .env      # 按需填入 SILICONFLOW_API_KEY
docker compose up -d
# 打开 http://localhost:5173
```

数据库镜像已内置知识库快照（含 embedding），**不需要重新建库，不需要 API Key 也能看到完整数据**。

### 路径 B：前端 Mock 回放

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

| 来源 | 域 | 许可证 |
|---|---|---|
| JavaGuide | 后端 | CC BY-SA 4.0 |
| CS-Notes | 后端 | CC BY-SA 4.0 |
| MySQL / Redis 官方文档 | 后端 | 各自官方条款 |
| JVM 规范（JVMS） | 后端 | Oracle 规范许可 |
| HNSW 原论文（Malkov & Yashunin） | AI | arXiv 预印本，引用+摘要 |
| RAG 原论文（Lewis et al.） | AI | arXiv 预印本，引用+摘要 |
| Anthropic《Building effective agents》 | AI | 官方博客，引用+摘要 |
| Lilian Weng《LLM Powered Autonomous Agents》 | AI | 博客，引用+摘要 |
| Prompt Engineering Guide（dair-ai） | AI | CC BY-NC 4.0 |

原始文件**不随仓库分发**，由 `scripts/fetch_sources.py` 按 `sources.manifest.yaml` 拉取；论文类只保留自写摘要与原文链接，不转存全文。

署名与完整清单见 [`sources.manifest.yaml`](sources.manifest.yaml)。

---

## 参赛信息

2026 传智杯 · 全国高校 Vibe Coding 开发挑战赛 · 省赛 · B 组
开发过程与 Prompt 记录见 [`docs/prompts/`](docs/prompts/)。
