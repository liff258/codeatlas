# 依赖清单（白名单）

> **CLAUDE.md 规则 5：禁止引入本清单之外的第三方库。** 需要新库先在这里登记并写明理由，再动代码。
> 理由：AI 生成代码时最危险的行为是"顺手引入一个没装过的库"，报错后又会编造 API 去适配。白名单是最便宜的一道闸。

---

## Java（`services/java-gateway/pom.xml`）

| 依赖 | 版本 | 用途 | 备注 |
|---|---|---|---|
| spring-boot-starter-web | 3.5.x | MVC + SseEmitter | |
| spring-boot-starter-webflux | 3.5.x | **仅用 WebClient** 消费 Python SSE | 不要用它的 Netty 替换 Tomcat |
| spring-boot-starter-validation | 3.5.x | 参数校验 | |
| mybatis-plus-spring-boot3-starter | 3.5.9 | ORM | PG 方言 |
| mybatis-plus-jsqlparser | 3.5.9 | 分页插件依赖 | 3.5.9 起需显式引入 |
| postgresql | 42.7.x | PG 驱动 | |
| lombok | 1.18.x | 减少样板 | |
| springdoc-openapi-starter-webmvc-ui | 2.6.x | 接口文档 | 复现性加分项 |

**禁用**：JPA / Hibernate（与 MyBatis-Plus 冲突）、spring-ai（版本坑多，本项目不用）、任何 Redis 客户端（P0–P2 阶段无缓存需求）。

## Python（`services/python-agent/requirements.txt`）

| 依赖 | 版本 | 用途 |
|---|---|---|
| fastapi | 0.115.x | Web 框架 |
| uvicorn[standard] | 0.32.x | ASGI server |
| pydantic | 2.x | 数据校验 |
| pydantic-settings | 2.x | 读 .env |
| sqlalchemy | 2.0.x | ORM（**同步 Session**） |
| psycopg[binary] | 3.2.x | PG 驱动 |
| pgvector | 0.3.x | SQLAlchemy 的 vector 类型 |
| openai | 1.x | 调硅基流动（OpenAI 兼容协议） |
| pymupdf | 1.24.x | PDF 解析 |
| jieba | 0.42.x | 中文分词（BM25 用） |
| rank-bm25 | 0.2.x | 关键词检索 |
| torch | 2.4+ (**CPU 版**) | 本地 bge-m3 推理 |
| transformers | 4.44+ | 模型加载与 tokenizer |
| safetensors | 0.4+ | 模型权重格式 |
| httpx | 0.27.x | 测试与内部调用 |
| tenacity | 9.x | 重试（LLM 限流退避） |

**关于 torch/transformers 的登记理由**（P1 新增）：

需求是「不花 API 预算也能做向量检索」。可选方案有三条，都评估过：

| 方案 | 体积 | 结论 |
|---|---|---|
| 硅基流动 embedding API | 0 | **否决**：需要 API key，用户明确说没预算 |
| sentence-transformers | 含 torch | **否决**：多一层封装，我们的 mean-pooling 只有 5 行，自己写更能看清 attention mask 的处理 |
| torch + transformers（CPU） | ~2.3GB | **采纳** |

必须注意：**torch 要装 CPU 版**，`pip install torch` 在 Windows 上会拉 CUDA 运行时（多 2GB）：
```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
```

模型文件不进仓库（`data/models/` 已 gitignore），由 `scripts/fetch_model.py` 从 ModelScope 下载。

**禁用**：langchain / llamaindex（黑盒封装会吃掉"创新性"分，且版本地狱）、chromadb（本方案不用）、celery（单人项目不需要任务队列，用 asyncio 后台任务即可）、任何 async SQLAlchemy 驱动（`asyncpg`）。

## 前端（`web/package.json`）

| 依赖 | 版本 | 用途 |
|---|---|---|
| react / react-dom | 18.x | |
| vite | 6.x | 构建 |
| typescript | 5.6.x | |
| zustand | 5.x | 流式缓冲 |
| @tanstack/react-query | 5.x | 服务端状态 |
| tailwindcss | **3.4.x** | 样式（不要 4.x） |
| framer-motion | 12.x | 动效 |
| react-force-graph-2d | 1.27.x | 图谱 |
| react-markdown + remark-gfm | 9.x / 4.x | Markdown |
| rehype-katex + katex | 7.x / 0.16.x | 公式 |
| shiki | 1.x | 代码高亮 |
| clsx + tailwind-merge | — | shadcn 配套 |
| lucide-react | — | 图标 |

**禁用**：next.js（SSR 与 SSE 冲突）、redux（Zustand 够用）、antd / mui（会和 shadcn 打架）、任何 SSE 解析库（手写 40 行，比调试第三方库快）。

---

## 版本锁定原则

选「AI 语料最厚」而非「最新」。每次升级版本前问三个问题：
1. 这个版本的 breaking change 我能不能讲清楚？
2. AI 对这个版本的 API 熟不熟？（不熟 = 会编造方法名）
3. 升级能带来评分上的实际收益吗？（大多数时候答案是"没有"）
