/**
 * 对话状态 —— Zustand
 *
 * 设计要点：
 *   1. token 逐字到达，但**不逐字 setState**。用 rAF 把同一帧内的 token 合并成一次提交，
 *      否则真实链路下一秒钟 60 次全树重渲染，帧率直接塌。
 *   2. 思考过程（step / plan / grade / retrieval）按 seq 顺序存成一个数组，
 *      不做「按类型分组」。人看思考过程是按时间读的，分组反而看不懂。
 *   3. AbortController 放在模块作用域，不进 state —— 它不该引起任何重渲染。
 */

import { create } from 'zustand';
import type {
  AgentNode,
  CitationEvent,
  DoneEvent,
  ErrorEvent,
  GradeDecision,
  GraphEdge,
  GraphNode,
  Intent,
  RetrievalEngine,
  RetrievedChunk,
  StepStatus,
  SubQuery,
} from '../types/events';
import { postAgentStream, StreamError } from '../lib/sse';

/* ────────────────────────── 类型 ────────────────────────── */

export type ThoughtItem =
  | {
      kind: 'step';
      seq: number;
      node: AgentNode;
      status: StepStatus;
      label: string;
      detail?: string;
      closed: boolean;
    }
  | { kind: 'plan'; seq: number; intent: Intent; hops: number; subQueries: SubQuery[] }
  | {
      kind: 'grade';
      seq: number;
      coverage: number;
      threshold: number;
      decision: GradeDecision;
      rewriteN: number;
      reason: string;
      lowIds: string[];
    }
  | {
      kind: 'retrieval';
      seq: number;
      queryId: string;
      engine: RetrievalEngine;
      rewriteRound: number;
      chunks: RetrievedChunk[];
    };

export interface GraphState {
  nodes: Record<string, GraphNode>;
  edges: Record<string, GraphEdge>;
  activePath: string[];
}

export type MessagePhase = 'thinking' | 'answering' | 'done' | 'error';

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  /** user: 提问原文；assistant: 流式累积的答案 */
  content: string;
  thoughts: ThoughtItem[];
  citations: Record<number, CitationEvent>;
  graph: GraphState;
  done: DoneEvent | null;
  error: ErrorEvent | null;
  phase: MessagePhase;
  createdAt: number;
}

interface ChatStore {
  messages: ChatMessage[];
  streaming: boolean;
  /** 当前流的 trace_id，页头显示，方便排查 */
  traceId: string | null;
  ask: (question: string) => Promise<void>;
  stop: () => void;
  reset: () => void;
  retry: () => Promise<void>;
}

/* ────────────────────────── 工具 ────────────────────────── */

const emptyGraph = (): GraphState => ({ nodes: {}, edges: {}, activePath: [] });

const newAssistant = (id: string): ChatMessage => ({
  id,
  role: 'assistant',
  content: '',
  thoughts: [],
  citations: {},
  graph: emptyGraph(),
  done: null,
  error: null,
  phase: 'thinking',
  createdAt: Date.now(),
});

const edgeKey = (e: GraphEdge) => `${e.source}->${e.target}`;

/* ────────────────────────── 模块级可变状态 ────────────────────────── */

let currentAbort: AbortController | null = null;
let activeMsgId: string | null = null;
let pendingText = '';
let rafId = 0;

/* ────────────────────────── store ────────────────────────── */

export const useChatStore = create<ChatStore>((set, get) => {
  /** 只改一条消息，其余引用保持不变 */
  const patch = (id: string, fn: (m: ChatMessage) => ChatMessage) => {
    set((s) => ({ messages: s.messages.map((m) => (m.id === id ? fn(m) : m)) }));
  };

  /** 把攒下的 token 一次性写入 */
  const flushTokens = () => {
    rafId = 0;
    if (!activeMsgId || !pendingText) return;
    const chunk = pendingText;
    pendingText = '';
    patch(activeMsgId, (m) => ({
      ...m,
      content: m.content + chunk,
      phase: m.phase === 'thinking' ? 'answering' : m.phase,
    }));
  };

  const scheduleFlush = () => {
    if (rafId) return;
    rafId = requestAnimationFrame(flushTokens);
  };

  const stopFlush = () => {
    if (rafId) {
      cancelAnimationFrame(rafId);
      rafId = 0;
    }
    flushTokens();
  };

  return {
    messages: [],
    streaming: false,
    traceId: null,

    async ask(question: string) {
      const q = question.trim();
      if (!q || get().streaming) return;

      const asstId = `a_${Date.now().toString(36)}`;
      const userMsg: ChatMessage = {
        id: `u_${Date.now().toString(36)}`,
        role: 'user',
        content: q,
        thoughts: [],
        citations: {},
        graph: emptyGraph(),
        done: null,
        error: null,
        phase: 'done',
        createdAt: Date.now(),
      };

      set((s) => ({
        messages: [...s.messages, userMsg, newAssistant(asstId)],
        streaming: true,
        traceId: null,
      }));

      activeMsgId = asstId;
      pendingText = '';
      const abort = new AbortController();
      currentAbort = abort;

      try {
        for await (const evt of postAgentStream(
          { question: q },
          {
            signal: abort.signal,
            onOpen: () => set({ traceId: null }),
          },
        )) {
          // 中途被 reset / 新一轮覆盖，立刻收手
          if (activeMsgId !== asstId) return;

          switch (evt.type) {
            case 'step': {
              patch(asstId, (m) => {
                const thoughts = [...m.thoughts];
                // running → ok 配对成一条，面板里不出现两行
                // （不用 findLastIndex：tsconfig 的 lib 锁在 ES2022，它属于 ES2023）
                let idx = -1;
                for (let i = thoughts.length - 1; i >= 0; i--) {
                  const t = thoughts[i];
                  if (t.kind === 'step' && t.node === evt.node && !t.closed) {
                    idx = i;
                    break;
                  }
                }
                if (evt.status === 'running') {
                  thoughts.push({
                    kind: 'step',
                    seq: evt.seq,
                    node: evt.node,
                    status: 'running',
                    label: evt.label,
                    detail: evt.detail,
                    closed: false,
                  });
                } else if (idx >= 0) {
                  const prev = thoughts[idx] as Extract<ThoughtItem, { kind: 'step' }>;
                  thoughts[idx] = {
                    ...prev,
                    status: evt.status,
                    label: evt.label || prev.label,
                    detail: evt.detail ?? prev.detail,
                    closed: true,
                  };
                } else {
                  // 没收到 running 就直接 ok 的情况，也要显示出来
                  thoughts.push({
                    kind: 'step',
                    seq: evt.seq,
                    node: evt.node,
                    status: evt.status,
                    label: evt.label,
                    detail: evt.detail,
                    closed: true,
                  });
                }
                return { ...m, thoughts };
              });
              break;
            }

            case 'plan':
              patch(asstId, (m) => ({
                ...m,
                thoughts: [
                  ...m.thoughts,
                  {
                    kind: 'plan',
                    seq: evt.seq,
                    intent: evt.intent,
                    hops: evt.hops,
                    subQueries: evt.sub_queries,
                  },
                ],
              }));
              break;

            case 'retrieval':
              patch(asstId, (m) => ({
                ...m,
                thoughts: [
                  ...m.thoughts,
                  {
                    kind: 'retrieval',
                    seq: evt.seq,
                    queryId: evt.query_id,
                    engine: evt.engine,
                    rewriteRound: evt.rewrite_round,
                    chunks: evt.chunks,
                  },
                ],
              }));
              break;

            case 'grade':
              patch(asstId, (m) => ({
                ...m,
                thoughts: [
                  ...m.thoughts,
                  {
                    kind: 'grade',
                    seq: evt.seq,
                    coverage: evt.coverage,
                    threshold: evt.threshold,
                    decision: evt.decision,
                    rewriteN: evt.rewrite_n,
                    reason: evt.reason,
                    lowIds: evt.low_score_chunk_ids,
                  },
                ],
              }));
              break;

            case 'graph':
              patch(asstId, (m) => {
                const nodes = evt.replace ? {} : { ...m.graph.nodes };
                const edges = evt.replace ? {} : { ...m.graph.edges };
                for (const n of evt.nodes) nodes[n.id] = { ...nodes[n.id], ...n };
                for (const e of evt.edges) edges[edgeKey(e)] = e;
                return {
                  ...m,
                  graph: {
                    nodes,
                    edges,
                    activePath: evt.active_path.length ? evt.active_path : m.graph.activePath,
                  },
                };
              });
              break;

            case 'token':
              pendingText += evt.text;
              scheduleFlush();
              break;

            case 'citation':
              patch(asstId, (m) => ({
                ...m,
                citations: { ...m.citations, [evt.claim_id]: evt },
              }));
              break;

            case 'error':
              stopFlush();
              patch(asstId, (m) => ({ ...m, error: evt, phase: 'error' }));
              break;

            case 'done':
              stopFlush();
              patch(asstId, (m) => ({
                ...m,
                done: evt,
                phase: evt.stop_reason === 'error' ? 'error' : 'done',
              }));
              break;

            default:
              break;
          }
        }

        // 流意外结束（没收到 done）：不能让 UI 一直转圈
        stopFlush();
        patch(asstId, (m) =>
          m.phase === 'thinking' || m.phase === 'answering'
            ? { ...m, phase: 'done' }
            : m,
        );
      } catch (e) {
        stopFlush();
        const err: ErrorEvent =
          e instanceof StreamError
            ? {
                seq: 0,
                trace_id: get().traceId ?? '',
                ts: Date.now(),
                code: e.code === 'HTTP' ? 'INTERNAL' : 'INTERNAL',
                message: e.message,
                retryable: true,
              }
            : {
                seq: 0,
                trace_id: '',
                ts: Date.now(),
                code: 'INTERNAL',
                message: (e as Error)?.message ?? '未知错误',
                retryable: true,
              };
        patch(asstId, (m) => ({ ...m, error: err, phase: 'error' }));
      } finally {
        if (currentAbort === abort) currentAbort = null;
        activeMsgId = null;
        set({ streaming: false });
      }
    },

    stop() {
      currentAbort?.abort();
      currentAbort = null;
      stopFlush();
      set({ streaming: false });
    },

    reset() {
      currentAbort?.abort();
      currentAbort = null;
      activeMsgId = null;
      pendingText = '';
      if (rafId) {
        cancelAnimationFrame(rafId);
        rafId = 0;
      }
      set({ messages: [], streaming: false, traceId: null });
    },

    async retry() {
      const msgs = get().messages;
      const lastUser = [...msgs].reverse().find((m) => m.role === 'user');
      if (!lastUser) return;
      // 移除最后一条失败的助手消息，重新问
      set((s) => ({
        messages: s.messages.filter(
          (m) => !(m.role === 'assistant' && m.phase === 'error'),
        ),
      }));
      await get().ask(lastUser.content);
    },
  };
});

/* ────────────────────────── 派生选择器 ────────────────────────── */

export const selectLastAssistant = (s: ChatStore): ChatMessage | null => {
  for (let i = s.messages.length - 1; i >= 0; i--) {
    if (s.messages[i].role === 'assistant') return s.messages[i];
  }
  return null;
};

/** 当前活跃节点（最近一条未闭合的 step），给顶部节点轨道用 */
export const selectActiveNode = (m: ChatMessage | null): AgentNode | null => {
  if (!m) return null;
  for (let i = m.thoughts.length - 1; i >= 0; i--) {
    const t = m.thoughts[i];
    if (t.kind === 'step' && !t.closed) return t.node;
  }
  return null;
};

/** 已跑完的节点集合，轨道上点亮的依据 */
export const selectDoneNodes = (m: ChatMessage | null): Set<AgentNode> => {
  const done = new Set<AgentNode>();
  if (!m) return done;
  for (const t of m.thoughts) {
    if (t.kind === 'step' && t.closed && t.status !== 'failed') done.add(t.node);
  }
  return done;
};
