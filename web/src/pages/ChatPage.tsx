/**
 * 对话页（从改造前的 App.tsx 迁过来）。
 *
 * 变化只有两处：
 *   1. 顶栏从「全局导航」变成页面内的工具栏（AgentRail + traceId + 新对话）
 *   2. 空状态从大 Hero 换成轻量引导——现在首页才是入口，
 *      对话页不该再抢「第一眼」
 *
 * 其余交互（流式、思考面板、引用角标、图谱）完全没动，
 * 这样改造风险最小：聊天是已经验证过的链路，不能因为改布局而回归。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Maximize2, Minimize2, RotateCcw, Sparkles } from 'lucide-react';
import AgentRail from '../components/AgentRail';
import Conversation from '../components/Conversation';
import Composer from '../components/Composer';
import ThinkingPanel from '../components/ThinkingPanel';
import GraphPanel from '../components/GraphPanel';
import SourceCard from '../components/SourceCard';
import { useChatStore } from '../store/chatStore';
import { useRoute } from '../lib/router';
import type { CitationEvent } from '../types/events';

/** 示例问题。放几个"能体现跨域"的，比空着好——用户不知道该问什么 */
const EXAMPLES = [
  '向量检索为什么不能用 B+ 树加速？',
  'G1 的 SATB 是什么，为什么需要它',
  'Redis 的持久化会不会阻塞主线程',
];

function ChatIntro({ onAsk }: { onAsk: (q: string) => void }) {
  return (
    <div className="flex h-full items-center justify-center px-8">
      <div className="w-full max-w-xl animate-fade-up">
        <div className="mb-3 inline-flex items-center gap-1.5 rounded-full border border-line bg-white/60 px-2.5 py-1 text-[11px] text-ink-500">
          <Sparkles size={11} className="text-bridge" />
          可解释检索智能体
        </div>
        <h1 className="font-serif text-[26px] leading-[1.4] tracking-tight text-ink-900">
          直接问，答案里每个结论都能点开看原文
        </h1>
        <p className="mt-2.5 max-w-md text-[12.5px] leading-[1.85] text-ink-500">
          它会先规划查询、再自评证据够不够，不够就改写重查——整个过程摊在右栏给你看。
        </p>

        <div className="mt-5 space-y-1.5">
          {EXAMPLES.map((q) => (
            <button
              key={q}
              type="button"
              onClick={() => onAsk(q)}
              className="block w-full rounded-md border border-line bg-white px-3 py-2 text-left text-[12.5px] text-ink-600 transition-colors hover:border-ink-400/40 hover:text-ink-900"
            >
              {q}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

export default function ChatPage() {
  const messages = useChatStore((s) => s.messages);
  const streaming = useChatStore((s) => s.streaming);
  const traceId = useChatStore((s) => s.traceId);
  const ask = useChatStore((s) => s.ask);
  const stop = useChatStore((s) => s.stop);
  const reset = useChatStore((s) => s.reset);
  const restore = useChatStore((s) => s.restore);
  const retry = useChatStore((s) => s.retry);

  const { query } = useRoute();
  const [cite, setCite] = useState<CitationEvent | null>(null);
  const [graphFull, setGraphFull] = useState(false);

  const lastAssistant = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === 'assistant') return messages[i];
    }
    return null;
  }, [messages]);

  // 刷新后恢复上一次的对话
  useEffect(() => {
    restore();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // #/chat?q=xxx 直接发起一轮。用 ref 记已处理的 q，
  // 否则同一句话在组件重渲染时会重复提问。
  const handledQ = useRef<string | null>(null);
  useEffect(() => {
    const q = query.get('q');
    if (!q || handledQ.current === q) return;
    handledQ.current = q;
    void ask(q);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query.toString()]);

  useEffect(() => {
    if (!graphFull) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setGraphFull(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [graphFull]);

  const onAsk = useCallback((q: string) => void ask(q), [ask]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* 工具栏：只在对话页出现，全局导航在 AppShell */}
      <div className="flex h-11 shrink-0 items-center gap-3 border-b border-line/70 px-5">
        <div className="hidden min-w-0 flex-1 justify-center md:flex">
          <AgentRail message={lastAssistant} />
        </div>
        <div className="ml-auto flex shrink-0 items-center gap-2">
          {traceId && (
            <span className="hidden font-mono text-[10px] text-ink-400 lg:inline">{traceId}</span>
          )}
          <button
            type="button"
            onClick={reset}
            title="新对话"
            className="flex items-center gap-1 rounded-md border border-line bg-white/70 px-2 py-1 text-[11px] text-ink-500 transition-colors hover:border-ink-400/40 hover:text-ink-900"
          >
            <RotateCcw size={11} />
            新对话
          </button>
        </div>
      </div>

      <div className="flex min-h-0 flex-1">
        <section className="flex min-w-0 flex-1 flex-col">
          <div className="min-h-0 flex-1">
            {messages.length === 0 ? (
              <ChatIntro onAsk={onAsk} />
            ) : (
              <Conversation messages={messages} onCite={setCite} onRetry={retry} />
            )}
          </div>
          <Composer streaming={streaming} onSend={ask} onStop={stop} />
        </section>

        {/* 右栏：思考 + 图谱。首屏不显示，让引导占满整宽 */}
        {messages.length > 0 && (
          <aside className="hidden w-[392px] shrink-0 animate-fade-up flex-col border-l border-line bg-white/35 lg:flex">
            <div className="flex h-9 shrink-0 items-center justify-between border-b border-line/70 px-4">
              <span className="text-[11px] font-medium tracking-wide text-ink-500">推理过程</span>
              <span className="text-[10px] text-ink-400">
                {lastAssistant ? `${lastAssistant.thoughts.length} 步` : '待提问'}
              </span>
            </div>

            {/* 高度用 flex-grow 比例（3:2）分配，不用百分比：
                百分比高度在这个 flex 列里解析不出来，图谱会被压成一条窄带 */}
            <div className="min-h-0 flex-[3]">
              <ThinkingPanel message={lastAssistant} />
            </div>

            <div className="flex-[2] min-h-[240px] overflow-hidden border-t border-line/70">
              <div className="flex h-8 items-center justify-between px-4">
                <span className="text-[11px] font-medium tracking-wide text-ink-500">知识图谱</span>
                <div className="flex items-center gap-1.5">
                  <span className="text-[10px] text-ink-400">
                    {lastAssistant
                      ? `${Object.keys(lastAssistant.graph.nodes).length} 节点 / ${
                          Object.values(lastAssistant.graph.edges).filter((e) => e.cross_domain).length
                        } 跨域边`
                      : '—'}
                  </span>
                  <button
                    type="button"
                    onClick={() => setGraphFull(true)}
                    title="全屏查看"
                    disabled={!lastAssistant || Object.keys(lastAssistant.graph.nodes).length === 0}
                    className="rounded p-[2px] text-ink-400 transition-colors hover:bg-paper-100 hover:text-ink-900 disabled:opacity-30"
                  >
                    <Maximize2 size={11} />
                  </button>
                </div>
              </div>
              <div className="h-[calc(100%-2rem)]">
                <GraphPanel graph={lastAssistant?.graph} />
              </div>
            </div>
          </aside>
        )}
      </div>

      {graphFull && (
        <div className="fixed inset-0 z-40 flex flex-col bg-paper-50">
          <div className="flex h-11 shrink-0 items-center justify-between border-b border-line px-5">
            <div className="flex items-center gap-2">
              <span className="text-[13px] font-semibold text-ink-900">知识图谱</span>
              <span className="text-[11px] text-ink-400">
                虚线 = 跨域边（两端属于不同学科域）
              </span>
            </div>
            <button
              type="button"
              onClick={() => setGraphFull(false)}
              className="flex items-center gap-1 rounded-md border border-line bg-white px-2 py-1 text-[11px] text-ink-500 transition-colors hover:text-ink-900"
            >
              <Minimize2 size={11} />
              退出全屏
            </button>
          </div>
          <div className="min-h-0 flex-1">
            <GraphPanel graph={lastAssistant?.graph} />
          </div>
        </div>
      )}

      <SourceCard citation={cite} onClose={() => setCite(null)} />
    </div>
  );
}
