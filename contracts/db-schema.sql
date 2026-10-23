-- ============================================================================
-- CodeAtlas 数据库 Schema
-- Postgres 16 + pgvector 0.8
--
-- 【表所有权约定 — 违反即为 Bug】
--   JAVA   : session / message / document / ingest_task / feedback / eval_run
--   PYTHON : chunk / chunk_embedding / entity / relation / agent_trace / agent_step
--            / eval_case / eval_result
--   交叉点 : document.status 只由 Python 更新，Java 只读
--
-- 变更本文件必须同步更新 contracts/openapi.yaml 与两侧实体类。
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ============================================================================
-- 一、JAVA 拥有的表
-- ============================================================================

-- 会话
CREATE TABLE session (
    id          BIGSERIAL PRIMARY KEY,
    user_id     VARCHAR(64)  NOT NULL DEFAULT 'local',
    title       VARCHAR(200) NOT NULL DEFAULT '新对话',
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX idx_session_updated ON session (user_id, updated_at DESC);

-- 消息（含助手回复）
CREATE TABLE message (
    id          BIGSERIAL PRIMARY KEY,
    session_id  BIGINT       NOT NULL REFERENCES session(id) ON DELETE CASCADE,
    role        VARCHAR(16)  NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content     TEXT         NOT NULL,
    -- 助手消息关联的 trace，用于「回放思考过程」和「点击引用跳原文」
    trace_id    VARCHAR(40),
    -- 重新生成时指向被替换的消息
    parent_id   BIGINT REFERENCES message(id) ON DELETE SET NULL,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX idx_message_session ON message (session_id, id);

-- 文档元数据
-- 注意：status 由 Python 的摄入管线更新，Java 只读
CREATE TABLE document (
    id            BIGSERIAL PRIMARY KEY,
    filename      VARCHAR(300) NOT NULL,
    file_type     VARCHAR(16)  NOT NULL CHECK (file_type IN ('md', 'pdf', 'txt', 'html')),
    size_bytes    BIGINT       NOT NULL DEFAULT 0,
    content_hash  CHAR(64)     NOT NULL,          -- sha256，幂等去重
    storage_path  VARCHAR(500),                   -- 原始文件落盘路径（不进 git）
    status        VARCHAR(20)  NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending','parsing','chunking','embedding','done','failed')),
    chunk_count   INT          NOT NULL DEFAULT 0,
    error_msg     TEXT,
    uploaded_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uq_document_hash ON document (content_hash);
CREATE INDEX idx_document_status ON document (status);

-- 摄入任务（断点续跑的状态机）
CREATE TABLE ingest_task (
    id           BIGSERIAL PRIMARY KEY,
    document_id  BIGINT      NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    status       VARCHAR(20) NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending','parsing','chunking','embedding','done','failed')),
    stage        VARCHAR(40),
    progress     SMALLINT    NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
    retry_count  SMALLINT    NOT NULL DEFAULT 0,
    error_msg    TEXT,
    started_at   TIMESTAMPTZ,
    finished_at  TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_ingest_task_doc ON ingest_task (document_id, created_at DESC);
CREATE INDEX idx_ingest_task_status ON ingest_task (status);

-- 用户对答案的反馈（用于后续调优，也是产品闭环的证据）
CREATE TABLE feedback (
    id          BIGSERIAL PRIMARY KEY,
    message_id  BIGINT      NOT NULL REFERENCES message(id) ON DELETE CASCADE,
    rating      SMALLINT    NOT NULL CHECK (rating IN (-1, 1)),
    reason      VARCHAR(40),        -- 无出处 / 答非所问 / 引用错误 / 其他
    comment     TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_feedback_message ON feedback (message_id);

-- 评测汇总（由 Java 侧触发评测后写入，供前端大盘展示）
CREATE TABLE eval_run (
    id                 BIGSERIAL PRIMARY KEY,
    name               VARCHAR(120) NOT NULL,
    recall_at_5        NUMERIC(5,4),
    citation_accuracy  NUMERIC(5,4),
    no_source_rate     NUMERIC(5,4),
    case_count         INT          NOT NULL DEFAULT 0,
    config             JSONB        NOT NULL DEFAULT '{}'::jsonb,
    created_at         TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- ============================================================================
-- 二、PYTHON 拥有的表
-- ============================================================================

-- ---------------------------------------------------------------------------
-- 【学科分类体系 — 唯一真相，两侧都从这里读，不要在代码里硬编码枚举】
--   后端域 backend：JVM / 并发 / MySQL / Redis / Spring / 网络 / 分布式 / 消息队列
--   AI 域  ai     ：LLM基础 / RAG / Agent / 向量检索 / Prompt工程
--   通用   common ：工程实践
-- 新增分类只需往本表插一行，不用改代码。
--
-- 所有权：参考数据，随 schema 初始化，运行时只读（两侧均可读，均不写）。
-- 唯一允许的写操作是运维手工补录新学科。
-- ---------------------------------------------------------------------------

CREATE TABLE subject_taxonomy (
    code         VARCHAR(40) PRIMARY KEY,
    domain       VARCHAR(10) NOT NULL CHECK (domain IN ('backend', 'ai', 'common')),
    display_name VARCHAR(60) NOT NULL,
    sort_order   SMALLINT    NOT NULL DEFAULT 100,
    -- 前端分栏配色，图谱跨域边也用它区分
    color        VARCHAR(20) NOT NULL DEFAULT '#64748b'
);

INSERT INTO subject_taxonomy (code, domain, display_name, sort_order, color) VALUES
  ('JVM',        'backend', 'JVM',        10, '#f97316'),
  ('并发',        'backend', 'Java 并发',  20, '#ef4444'),
  ('MySQL',      'backend', 'MySQL',      30, '#3b82f6'),
  ('Redis',      'backend', 'Redis',      40, '#dc2626'),
  ('Spring',     'backend', 'Spring',     50, '#22c55e'),
  ('网络',        'backend', '计算机网络',  60, '#0ea5e9'),
  ('分布式',      'backend', '分布式系统',  70, '#8b5cf6'),
  ('消息队列',    'backend', '消息队列',    80, '#14b8a6'),
  ('LLM基础',    'ai',      'LLM 基础',    110, '#a855f7'),
  ('RAG',        'ai',      'RAG',        120, '#ec4899'),
  ('Agent',      'ai',      'Agent',      130, '#f43f5e'),
  ('向量检索',    'ai',      '向量检索',    140, '#06b6d4'),
  ('Prompt工程', 'ai',      'Prompt 工程', 150, '#eab308'),
  ('工程实践',    'common',  '工程实践',    200, '#64748b');

-- 切片（父子块：parent 1024 token 供生成，child 256 token 供检索）
CREATE TABLE chunk (
    id              BIGSERIAL PRIMARY KEY,
    document_id     BIGINT       NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    parent_chunk_id BIGINT REFERENCES chunk(id) ON DELETE CASCADE,
    level           VARCHAR(10)  NOT NULL CHECK (level IN ('parent', 'child')),
    content         TEXT         NOT NULL,
    token_count     INT          NOT NULL DEFAULT 0,
    -- 标题层级路径，如 "第3章 > 3.2 G1 收集器 > 3.2.4 SATB"
    heading_path    TEXT,
    ordinal         INT          NOT NULL DEFAULT 0,   -- 文档内顺序
    -- 自动打标结果
    subject         VARCHAR(40) REFERENCES subject_taxonomy(code),  -- 见上方学科分类体系
    difficulty      SMALLINT CHECK (difficulty BETWEEN 1 AND 5),
    knowledge_points TEXT[]     NOT NULL DEFAULT '{}',  -- 知识点标签
    content_hash    CHAR(64)    NOT NULL,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX idx_chunk_doc ON chunk (document_id, ordinal);
CREATE INDEX idx_chunk_parent ON chunk (parent_chunk_id);
CREATE INDEX idx_chunk_subject ON chunk (subject);
CREATE INDEX idx_chunk_kp ON chunk USING GIN (knowledge_points);
CREATE INDEX idx_chunk_content_trgm ON chunk USING GIN (content gin_trgm_ops);

-- 向量（只有 child 级别需要 embedding）
CREATE TABLE chunk_embedding (
    chunk_id   BIGINT       PRIMARY KEY REFERENCES chunk(id) ON DELETE CASCADE,
    model      VARCHAR(80)  NOT NULL DEFAULT 'BAAI/bge-m3',
    embedding  vector(1024) NOT NULL,
    created_at TIMESTAMPTZ  NOT NULL DEFAULT now()
);
-- HNSW + 余弦距离；m/ef_construction 取中等值，2 万级数据足够
CREATE INDEX idx_chunk_embedding_hnsw
    ON chunk_embedding USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- 知识图谱：实体
CREATE TABLE entity (
    id             BIGSERIAL PRIMARY KEY,
    name           VARCHAR(200) NOT NULL,
    canonical_name VARCHAR(200) NOT NULL,       -- 归一化后的标准名，如 "G1" / "Garbage First"
    entity_type    VARCHAR(40)  NOT NULL,       -- 概念 / 组件 / 算法 / 参数 / 问题
    -- 实体归属学科。前端用它给节点上色；一条边的两端 domain 不同 → 渲染成跨域边
    subject        VARCHAR(40)  REFERENCES subject_taxonomy(code),
    description    TEXT,
    doc_freq       INT          NOT NULL DEFAULT 1,
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uq_entity_canonical ON entity (canonical_name);
CREATE INDEX idx_entity_type ON entity (entity_type);

-- 知识图谱：关系
CREATE TABLE relation (
    id              BIGSERIAL PRIMARY KEY,
    src_entity_id   BIGINT      NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
    dst_entity_id   BIGINT      NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
    rel_type        VARCHAR(40) NOT NULL,   -- 依赖 / 属于 / 对比 / 导致 / 解决
    weight          NUMERIC(4,2) NOT NULL DEFAULT 1.0,
    source_chunk_id BIGINT REFERENCES chunk(id) ON DELETE SET NULL,  -- 关系出处
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_no_self_loop CHECK (src_entity_id <> dst_entity_id)
);
CREATE INDEX idx_relation_src ON relation (src_entity_id);
CREATE INDEX idx_relation_dst ON relation (dst_entity_id);
CREATE UNIQUE INDEX uq_relation ON relation (src_entity_id, dst_entity_id, rel_type);

-- Agent 全链路 trace（25% 复现性分数的直接证据，也是前端回放的来源）
CREATE TABLE agent_trace (
    id             BIGSERIAL PRIMARY KEY,
    trace_id       VARCHAR(40)  NOT NULL,
    session_id     BIGINT,                       -- 逻辑关联，不建外键（跨所有权）
    question       TEXT         NOT NULL,
    answer         TEXT,
    intent         VARCHAR(30),                  -- concept / compare / debug / quiz
    rewrite_count  SMALLINT     NOT NULL DEFAULT 0,
    step_count     SMALLINT     NOT NULL DEFAULT 0,
    coverage       NUMERIC(4,3),
    latency_ms     INT,
    token_input    INT          NOT NULL DEFAULT 0,
    token_output   INT          NOT NULL DEFAULT 0,
    -- 触发终止条件时的原因：step_limit / rewrite_limit / timeout / budget / normal
    stop_reason    VARCHAR(30),
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uq_agent_trace_tid ON agent_trace (trace_id);
CREATE INDEX idx_agent_trace_session ON agent_trace (session_id, created_at DESC);

-- Agent 单步记录（前端思考面板逐条渲染的数据源）
CREATE TABLE agent_step (
    id          BIGSERIAL PRIMARY KEY,
    trace_id    VARCHAR(40) NOT NULL,
    seq         SMALLINT    NOT NULL,
    node        VARCHAR(30) NOT NULL,   -- router/planner/retriever/grader/rewriter/tool/citation/generator
    status      VARCHAR(16) NOT NULL CHECK (status IN ('running','ok','degraded','failed')),
    -- 该节点的完整输入输出快照，前端展开时直接读
    payload     JSONB       NOT NULL DEFAULT '{}'::jsonb,
    duration_ms INT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uq_agent_step ON agent_step (trace_id, seq);

-- 评测集（50 题 gold set）
CREATE TABLE eval_case (
    id               BIGSERIAL PRIMARY KEY,
    question         TEXT         NOT NULL,
    expected_chunk_ids BIGINT[]   NOT NULL DEFAULT '{}',
    expected_points  TEXT[]       NOT NULL DEFAULT '{}',
    category         VARCHAR(40),
    difficulty       SMALLINT CHECK (difficulty BETWEEN 1 AND 5),
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- 评测单题结果
CREATE TABLE eval_result (
    id                 BIGSERIAL PRIMARY KEY,
    run_id             BIGINT      NOT NULL REFERENCES eval_run(id) ON DELETE CASCADE,
    case_id            BIGINT      NOT NULL REFERENCES eval_case(id) ON DELETE CASCADE,
    retrieved_ids      BIGINT[]    NOT NULL DEFAULT '{}',
    recall_at_5        BOOLEAN     NOT NULL DEFAULT false,
    citation_correct   BOOLEAN,
    has_source         BOOLEAN,
    latency_ms         INT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_eval_result_run ON eval_result (run_id);

-- ============================================================================
-- 三、初始数据（开发期占位，正式快照在 db/snapshots/）
-- ============================================================================

INSERT INTO session (user_id, title) VALUES ('local', '演示会话')
ON CONFLICT DO NOTHING;
