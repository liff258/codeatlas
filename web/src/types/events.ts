/**
 * SSE 事件类型定义
 *
 * 唯一真相：contracts/sse-events.md
 * 改这里之前先改契约，否则两侧实现会静默漂移。
 */

/* ────────────────────────── 通用信封 ────────────────────────── */

/** 每个事件 data 都带的三个字段 */
export interface Envelope {
  /** 单调递增，从 1 开始。断线续传与去重的唯一依据 */
  seq: number;
  /** 本次问答链路 ID，形如 t_8f2a1c */
  trace_id: string;
  /** 服务端毫秒时间戳 */
  ts: number;
}

/* ────────────────────────── 4.1 step ────────────────────────── */

export type AgentNode =
  | 'router'
  | 'planner'
  | 'retriever'
  | 'grader'
  | 'rewriter'
  | 'tool'
  | 'citation'
  | 'generator';

/**
 * running  → 节点开始
 * ok       → 正常结束
 * degraded → 降级后继续跑（正常路径，不是错误，用黄色不用红色）
 * failed   → 失败
 */
export type StepStatus = 'running' | 'ok' | 'degraded' | 'failed';

export interface StepEvent extends Envelope {
  node: AgentNode;
  status: StepStatus;
  label: string;
  /** 降级/失败时的原因，如「解析失败，降级为单查询」 */
  detail?: string;
}

/* ────────────────────────── 4.2 plan ────────────────────────── */

export type Intent = 'concept' | 'compare' | 'debug' | 'quiz' | 'chitchat';

export interface SubQuery {
  id: string;
  text: string;
  entities: string[];
}

export interface PlanEvent extends Envelope {
  intent: Intent;
  /** 预期跳数，1–3 */
  hops: number;
  sub_queries: SubQuery[];
}

/* ────────────────────────── 4.3 retrieval ────────────────────────── */

export type RetrievalEngine = 'vector' | 'bm25' | 'hybrid';

export interface RetrievedChunk {
  id: string;
  doc_id: number;
  /** 归一化后 0–1，重排后的最终分 */
  score: number;
  vec_rank?: number;
  bm25_rank?: number;
  rrf_score?: number;
  heading_path: string;
  /** 前 80 字 */
  preview: string;
}

export interface RetrievalEvent extends Envelope {
  query_id: string;
  engine: RetrievalEngine;
  /** 0 = 首轮检索；1、2 = 第几次改写后的补检索 */
  rewrite_round: number;
  chunks: RetrievedChunk[];
}

/* ────────────────────────── 4.4 grade ────────────────────────── */

export type GradeDecision = 'proceed' | 'rewrite' | 'give_up';

export interface GradeEvent extends Envelope {
  /** 0–1 证据覆盖度 */
  coverage: number;
  threshold: number;
  decision: GradeDecision;
  rewrite_n: number;
  low_score_chunk_ids: string[];
  reason: string;
}

/* ────────────────────────── 4.5 graph ────────────────────────── */

export type Domain = 'backend' | 'ai' | 'common';
export type NodeType = '概念' | '组件' | '算法' | '参数' | '问题';

export interface GraphNode {
  id: string;
  label: string;
  type: NodeType;
  subject: string;
  domain: Domain;
  /** 度数，决定节点大小 */
  weight: number;
}

export interface GraphEdge {
  source: string;
  target: string;
  rel: string;
  weight: number;
  /** 两端 domain 不同。前端必须虚线 + 琥珀色 */
  cross_domain: boolean;
}

export interface GraphEvent extends Envelope {
  nodes: GraphNode[];
  edges: GraphEdge[];
  /** 本次推理路径，前端高亮 */
  active_path: string[];
  /** false = 增量合并；true = 清空重画 */
  replace: boolean;
}

/* ────────────────────────── 4.6 token ────────────────────────── */

export interface TokenEvent extends Envelope {
  /** 增量文本，前端直接 buffer += text */
  text: string;
}

/* ────────────────────────── 4.7 citation ────────────────────────── */

export interface CitationSource {
  doc_id: number;
  doc_name: string;
  heading_path: string;
}

export interface CitationEvent extends Envelope {
  /** 第几个论点，从 1 开始 */
  claim_id: number;
  /** 正文里的角标文本，如 "[2]" */
  marker: string;
  chunk_ids: string[];
  quote: string;
  source: CitationSource;
}

/* ────────────────────────── 4.8 done ────────────────────────── */

export type StopReason =
  | 'normal'
  | 'step_limit'
  | 'rewrite_limit'
  | 'timeout'
  | 'budget'
  | 'error';

export interface Usage {
  input_tokens: number;
  output_tokens: number;
  /** 单次成本估算（元），产品透明度加分项 */
  cost_cny: number;
}

export interface DoneEvent extends Envelope {
  /** 仅 Java 侧有，Python 侧为 null */
  message_id: number | null;
  stop_reason: StopReason;
  coverage: number;
  rewrite_count: number;
  latency_ms: number;
  usage: Usage;
  /** true 时答案顶部显示「证据不足，以下为模型推断」 */
  insufficient_evidence: boolean;
}

/* ────────────────────────── 4.9 error ────────────────────────── */

export type ErrorCode =
  | 'LLM_TIMEOUT'
  | 'LLM_RATE_LIMIT'
  | 'RETRIEVAL_EMPTY'
  | 'INTERNAL';

export interface ErrorEvent extends Envelope {
  code: ErrorCode;
  message: string;
  retryable: boolean;
}

/* ────────────────────────── 联合类型 ────────────────────────── */

export type AgentEvent =
  | ({ type: 'step' } & StepEvent)
  | ({ type: 'plan' } & PlanEvent)
  | ({ type: 'retrieval' } & RetrievalEvent)
  | ({ type: 'grade' } & GradeEvent)
  | ({ type: 'graph' } & GraphEvent)
  | ({ type: 'token' } & TokenEvent)
  | ({ type: 'citation' } & CitationEvent)
  | ({ type: 'done' } & DoneEvent)
  | ({ type: 'error' } & ErrorEvent);

export type AgentEventType = AgentEvent['type'];

/** 事件名 → 联合类型的映射，给解析器做类型收窄用 */
export interface EventPayloadMap {
  step: StepEvent;
  plan: PlanEvent;
  retrieval: RetrievalEvent;
  grade: GradeEvent;
  graph: GraphEvent;
  token: TokenEvent;
  citation: CitationEvent;
  done: DoneEvent;
  error: ErrorEvent;
}

export const KNOWN_EVENTS: ReadonlySet<string> = new Set<AgentEventType>([
  'step',
  'plan',
  'retrieval',
  'grade',
  'graph',
  'token',
  'citation',
  'done',
  'error',
]);
