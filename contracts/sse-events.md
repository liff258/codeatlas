# SSE 事件协议 v1

> **这是唯一真相。** Java 侧和 Python 侧都按本文件实现，任何一方擅自加字段即为 Bug。
> 变更流程：改本文件 → 同步改 `openapi.yaml` → 改两侧实现 → 更新 `web/src/lib/sse.ts` 的类型定义。

---

## 1. 端点

| 端点 | 提供方 | 说明 |
|---|---|---|
| `POST /internal/agent/stream` | Python | 内部接口，需 `X-Internal-Token` 头，仅内网可达 |
| `POST /api/chat/stream` | Java | 对外接口，浏览器唯一调用入口 |

两侧事件**类型与语义完全一致**。Java 只做三件事：鉴权、透传、落库；额外补充 `message_id` 字段。

## 2. 传输约定

```
Content-Type: text/event-stream; charset=utf-8
Cache-Control: no-cache, no-transform
Connection: keep-alive
X-Accel-Buffering: no          ← 必须，否则 Nginx 会攒批
```

**三层缓冲必须全部关闭**，缺一层流式就会变成"等 5 秒一次性蹦出来"：

| 层 | 配置 |
|---|---|
| Python | `StreamingResponse` + 上面的响应头 |
| Java | `SseEmitter`，`spring.mvc.async.request-timeout=300000` |
| Nginx | `proxy_buffering off; proxy_read_timeout 300s; proxy_http_version 1.1;` |

**心跳**：每 15 秒发一条 SSE 注释行 `: ping`（不是事件，前端解析时直接跳过）。

**前端必须用 `fetch + ReadableStream` 解析**。`EventSource` 只支持 GET，问题文本放不进 URL，且无法带自定义 Header。

## 3. 通用信封

每个事件的 `data` 都是一个 JSON 对象，**至少包含以下三个字段**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `seq` | int | 单调递增，从 1 开始。断线续传的唯一依据 |
| `trace_id` | string | 本次问答的链路 ID，形如 `t_8f2a1c`。与 `agent_trace.trace_id` 一致 |
| `ts` | int | 服务端毫秒时间戳 |

Java 转发时额外注入：

| 字段 | 类型 | 说明 |
|---|---|---|
| `message_id` | int | 落库后的助手消息 ID。**只在 `done` 事件里出现**，前端用它做反馈和重新生成 |

## 4. 事件类型

### 4.1 `step` — 节点生命周期

一个 Agent 节点开始/结束时各发一次。前端思考面板的骨架就靠它。

```json
{"seq":1,"trace_id":"t_8f2a1c","ts":1761195600123,
 "node":"router","status":"running","label":"判断问题意图"}
```

| 字段 | 类型 | 取值 |
|---|---|---|
| `node` | string | `router` `planner` `retriever` `grader` `rewriter` `tool` `citation` `generator` |
| `status` | string | `running` `ok` `degraded` `failed` |
| `label` | string | 给人看的中文说明，如「判断问题意图」 |
| `detail` | string? | 降级/失败时的原因，如「解析失败，降级为单查询」 |

> `degraded` 是**正常路径**不是错误——它表示节点降级后继续跑。前端用黄色而非红色显示。

### 4.2 `plan` — 查询规划结果

```json
{"seq":4,"trace_id":"t_8f2a1c","ts":1761195601500,
 "intent":"concept","hops":2,
 "sub_queries":[
   {"id":"q1","text":"SATB 基本原理","entities":["SATB"]},
   {"id":"q2","text":"写屏障在 G1 中的作用","entities":["写屏障","G1"]},
   {"id":"q3","text":"SATB 漏标后果 浮动垃圾","entities":["漏标","浮动垃圾"]}
 ]}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `intent` | string | `concept` `compare` `debug` `quiz` `chitchat` |
| `hops` | int | 预期跳数，1–3 |
| `sub_queries[].id` | string | `q1` `q2` `q3`，`retrieval` 事件按此归组 |
| `sub_queries[].text` | string | 实际送进检索引擎的查询串 |
| `sub_queries[].entities` | string[] | 从问题里抽出的实体，用于图谱扩展 |

### 4.3 `retrieval` — 检索结果

按子查询分组发送，一个子查询一条事件。

```json
{"seq":6,"trace_id":"t_8f2a1c","ts":1761195602100,
 "query_id":"q1","engine":"hybrid",
 "chunks":[
   {"id":"c_102","doc_id":3,"score":0.83,"vec_rank":2,"bm25_rank":1,"rrf_score":0.032,
    "heading_path":"第3章 > 3.2 G1 > 3.2.4 SATB","preview":"SATB 全称 Snapshot-At-The-Beginning…"}
 ]}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `query_id` | string | 对应 `plan.sub_queries[].id` |
| `engine` | string | `vector` `bm25` `hybrid` |
| `chunks[].id` | string | `c_<数字>`，与 `chunk.id` 对应 |
| `chunks[].score` | float | 归一化后 0–1，**重排后的最终分** |
| `chunks[].vec_rank` | int? | 向量召回排名，调试台展示用 |
| `chunks[].bm25_rank` | int? | BM25 召回排名 |
| `chunks[].rrf_score` | float? | RRF 融合分 |
| `chunks[].heading_path` | string | 原文定位，点击引用时跳到这里 |
| `chunks[].preview` | string | 前 80 字，避免前端为预览再发一次请求 |

### 4.4 `grade` — 证据自评

```json
{"seq":9,"trace_id":"t_8f2a1c","ts":1761195603400,
 "coverage":0.42,"threshold":0.6,"decision":"rewrite","rewrite_n":1,
 "low_score_chunk_ids":["c_108"],
 "reason":"缺少『漏标后果』相关证据"}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `coverage` | float | 0–1，证据覆盖度 |
| `threshold` | float | 阈值，来自 `.env` 的 `AGENT_COVERAGE_THRESHOLD` |
| `decision` | string | `proceed`（够用，直接生成） `rewrite`（不够，改写重查） `give_up`（重查次数用尽） |
| `rewrite_n` | int | 当前第几轮改写 |
| `low_score_chunk_ids` | string[] | 被判为低分的 chunk，调试台高亮 |
| `reason` | string | 一句话说明为什么做这个判断 |

> **前端必须把这个事件渲染成可见的"自评-决策"节点**。这是"思考可视化"得分点最集中的地方。

### 4.5 `graph` — 知识图谱增量

```json
{"seq":11,"trace_id":"t_8f2a1c","ts":1761195604100,
 "nodes":[
   {"id":"G1","label":"G1 收集器","type":"组件","weight":3},
   {"id":"SATB","label":"SATB","type":"算法","weight":2}
 ],
 "edges":[
   {"source":"G1","target":"SATB","rel":"使用","weight":1.0}
 ],
 "active_path":["G1","SATB"],
 "replace":false}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `nodes[].id` | string | 用 `canonical_name`，前后一致才能合并 |
| `nodes[].type` | string | 概念 / 组件 / 算法 / 参数 / 问题（决定节点颜色） |
| `nodes[].weight` | int | 度数，决定节点大小 |
| `active_path` | string[] | 本次推理路径，前端给这条链上的节点/边加高亮和粒子流动 |
| `replace` | bool | `false` 表示增量合并到现有图；`true` 表示清空重画（切换话题时用） |

> **性能硬约束**：单次 `graph` 事件节点数 ≤ 80。超了前端必卡。全图浏览走单独的 `GET /api/graph/overview` 接口，且必须做度数聚合。

### 4.6 `token` — 答案正文增量

```json
{"seq":14,"trace_id":"t_8f2a1c","ts":1761195605200,"text":"G1 使用 SATB"}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `text` | string | 增量文本片段。前端直接 `buffer += text` |

引用角标以 `[1]` `[2]` 形式内嵌在正文里，由 `citation` 事件解析。

### 4.7 `citation` — 引用绑定

**必须在对应正文 token 发出之前或同时到达**，否则角标会先渲染成裸文本再跳变。

```json
{"seq":16,"trace_id":"t_8f2a1c","ts":1761195606000,
 "claim_id":2,
 "marker":"[2]",
 "chunk_ids":["c_102"],
 "quote":"SATB 通过写屏障记录并发标记期间的引用变更，避免对象被误删",
 "source":{"doc_id":3,"doc_name":"JVM 笔记","heading_path":"第3章 > 3.2 G1 > 3.2.4 SATB"}
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `claim_id` | int | 第几个论点，从 1 开始 |
| `marker` | string | 正文里的角标文本，如 `[2]` |
| `chunk_ids` | string[] | 支撑该论点的 chunk，可能多个 |
| `quote` | string | 原文摘录，鼠标悬停时显示 |
| `source` | object | 点击角标跳转所需的最小信息 |

> 若某论点找不到支撑，**不发 `citation` 事件**，前端对该 `claim_id` 显示「无出处」标记。这个指标会进评测（`no_source_rate`）。

### 4.8 `done` — 结束

```json
{"seq":22,"trace_id":"t_8f2a1c","ts":1761195610000,
 "message_id":128,
 "stop_reason":"normal",
 "coverage":0.78,
 "rewrite_count":1,
 "latency_ms":4210,
 "usage":{"input_tokens":9840,"output_tokens":1480,"cost_cny":0.021},
 "insufficient_evidence":false}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `message_id` | int | 仅 Java 侧有，Python 侧为 null |
| `stop_reason` | string | `normal` `step_limit` `rewrite_limit` `timeout` `budget` `error` |
| `insufficient_evidence` | bool | 为 `true` 时前端在答案顶部显示「证据不足，以下为模型推断」 |
| `usage.cost_cny` | float | 单次成本估算，产品透明度加分项 |

### 4.9 `error` — 错误

```json
{"seq":23,"trace_id":"t_8f2a1c","ts":1761195610500,
 "code":"LLM_TIMEOUT","message":"模型响应超时","retryable":true}
```

| `code` | 含义 | 前端处理 |
|---|---|---|
| `LLM_TIMEOUT` | 模型超时 | 显示重试按钮 |
| `LLM_RATE_LIMIT` | 限流 | 显示「稍后再试」，自动退避重试 1 次 |
| `RETRIEVAL_EMPTY` | 检索为空 | 提示「知识库里还没有相关内容，先上传文档」 |
| `INTERNAL` | 其他 | 显示 trace_id 供排查 |

`error` 之后**必须**紧跟一个 `done`（`stop_reason=error`），保证前端状态机一定能收尾。

---

## 5. 完整事件序列（正常路径）

```
: ping
event: step       data: {"seq":1,"node":"router","status":"running",...}
event: step       data: {"seq":2,"node":"router","status":"ok",...}
event: step       data: {"seq":3,"node":"planner","status":"running",...}
event: plan       data: {"seq":4,"sub_queries":[...],"hops":2,...}
event: step       data: {"seq":5,"node":"retriever","status":"running",...}
event: retrieval  data: {"seq":6,"query_id":"q1",...}
event: retrieval  data: {"seq":7,"query_id":"q2",...}
event: retrieval  data: {"seq":8,"query_id":"q3",...}
event: step       data: {"seq":9,"node":"grader","status":"running",...}
event: grade      data: {"seq":10,"coverage":0.42,"decision":"rewrite",...}
event: step       data: {"seq":11,"node":"rewriter","status":"ok",...}
event: retrieval  data: {"seq":12,"query_id":"q4",...}
event: grade      data: {"seq":13,"coverage":0.78,"decision":"proceed",...}
event: graph      data: {"seq":14,"nodes":[...],"active_path":["G1","SATB"],...}
event: step       data: {"seq":15,"node":"generator","status":"running",...}
event: citation   data: {"seq":16,"claim_id":1,"marker":"[1]",...}
event: token      data: {"seq":17,"text":"G1 使用 SATB"}
event: token      data: {"seq":18,"text":"（快照标记）算法"}
...
event: done       data: {"seq":22,"stop_reason":"normal",...}
```

**顺序保证（前端可以依赖）**
1. `step(running)` 一定在同类事件之前
2. `plan` 一定在所有 `retrieval` 之前
3. 每个 `retrieval.query_id` 必须能在 `plan.sub_queries[].id` 里找到
4. `citation` 一定在其引用的 token 之前或同时
5. `done` 一定是最后一个事件（`error` 之后也必有 `done`）

## 6. 断线续传

- 客户端重连时带上 `Last-Event-ID: <最后收到的 seq>`
- 服务端从 `seq + 1` 开始重发
- **注意**：`token` 事件是增量文本，重发会重复。前端用 `seq` 去重：`if (evt.seq <= lastSeq) return;`
- 若服务端已无法续传（超过 5 分钟），直接返回 `error` + `done`，前端提示重新提问

## 7. Mock 数据

`web/src/mock/stream.jsonl` 存放本文件第 5 节的完整序列（一行一个 `{event, data}`），
供 `VITE_MOCK=1` 模式回放。**这份 mock 必须与真实链路的事件顺序完全一致**，
否则演示时会露馅。
