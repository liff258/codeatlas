/**
 * 主布局
 *
 * 三块：顶部节点轨道（看流程）、左侧对话（看结果）、右侧思考 + 图谱（看过程）。
 * 右侧上下分栏是刻意的——录屏时「推理步骤」和「跨域边」必须同框，
 * 否则剪视频还得来回切镜头。
 */

import { useEffect, useMemo, useState } from 'react';
import { Layers, Maximize2, Minimize2, Network, RotateCcw, ScanEye, Sparkles } from 'lucide-react';
import AgentRail from './components/AgentRail';
import Conversation from './components/Conversation';
import Composer from './components/Composer';
import ThinkingPanel from './components/ThinkingPanel';
import GraphPanel from './components/GraphPanel';
import SourceCard from './components/SourceCard';
import { useChatStore } from './store/chatStore';import { isMockMode } from './lib/sse';
import type { CitationEvent } from './types/events';

/* ────────────────────────── 首屏 ────────────────────────── */

const HERO = [
  {
    icon: Network,
    title: '跨域检索',
    desc: '后端与 AI 两个学科的知识，靠「跨域边」连起来',
  },
  {
    icon: ScanEye,
    title: '自评改写',
    desc: '先判断证据够不够，不够就自己改写查询再查一轮',
  },
  {
    icon: Layers,
    title: '过程可回放',
    desc: '每一步判断都落库，随时能翻出来看为什么这么答',
  },
];

/**
 * 跨域边示意
 *
 * 与其用文字解释「什么叫跨域」，不如直接把它画出来。
 * 这是整个产品的核心卖点，首屏就该看见。
 */
function CrossDomainSketch() {
  return (
    <svg
      viewBox="0 0 460 86"
      className="w-full max-w-[460px]"
      role="img"
      aria-label="RAG 与 B+ 树索引之间的跨域边示意"
    >
      <defs>
        <marker id="bridge-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="5" markerHeight="5" orient="auto">
          <path d="M0,0 L8,4 L0,8 z" fill="#d97706" />
        </marker>
      </defs>

      {/* 左：AI 域 */}
      <rect x="0.5" y="30" width="104" height="32" rx="9" fill="#fff" stroke="#db2777" strokeOpacity="0.45" />
      <circle cx="17" cy="46" r="3" fill="#db2777" />
      <text x="62" y="50" textAnchor="middle" fontSize="12" fontWeight="600" fill="#171614">
        RAG
      </text>
      <text x="52" y="78" textAnchor="middle" fontSize="10" fill="#8f8981">
        AI 域
      </text>

      {/* 右：后端域 */}
      <rect x="355.5" y="30" width="104" height="32" rx="9" fill="#fff" stroke="#2563eb" strokeOpacity="0.45" />
      <circle cx="372" cy="46" r="3" fill="#2563eb" />
      <text x="418" y="50" textAnchor="middle" fontSize="12" fontWeight="600" fill="#171614">
        B+ 树索引
      </text>
      <text x="407" y="78" textAnchor="middle" fontSize="10" fill="#8f8981">
        后端域
      </text>

      {/* 跨域边：虚线 + 琥珀色，与图谱面板里的样式一致 */}
      <path
        d="M108,46 C176,16 288,16 352,46"
        fill="none"
        stroke="#d97706"
        strokeWidth="1.6"
        strokeDasharray="5 4"
        markerEnd="url(#bridge-arrow)"
      />
      <text x="230" y="20" textAnchor="middle" fontSize="10" fontWeight="600" fill="#d97706">
        跨域边
      </text>
    </svg>
  );
}

function Hero() {
  return (
    <div className="flex h-full items-center justify-center px-8">
      <div className="w-full max-w-2xl">
        <div className="animate-fade-up">
          <div className="mb-3 inline-flex items-center gap-1.5 rounded-full border border-line bg-white/60 px-2.5 py-1 text-[11px] text-ink-500">
            <Sparkles size={11} className="text-bridge" />
            双域知识库 · 可解释检索智能体
          </div>

          <h1 className="font-serif text-[32px] leading-[1.3] tracking-tight text-ink-900">
            把「后端」和「AI」
            <br />
            连成一张网
          </h1>

          <p className="mt-3 max-w-lg text-[13.5px] leading-[1.85] text-ink-500">
            它不只是检索。它会先规划查询、再自评证据够不够，
            不够就改写重查——然后把整个判断过程摊开给你看。
          </p>
        </div>

        <div className="mt-6">
          <CrossDomainSketch />
          <p className="mt-1 text-[11px] text-ink-400">
            问题里没有「B+ 树」三个字，是系统自己连过去的。
          </p>
        </div>

        <div className="mt-7 grid grid-cols-3 gap-2.5">
          {HERO.map((h) => (
            <div
              key={h.title}
              className="animate-fade-up rounded-lg border border-line bg-white p-3 shadow-card"
            >
              <h.icon size={14} className="mb-1.5 text-ink-700" />
              <div className="text-[12.5px] font-semibold text-ink-900">{h.title}</div>
              <div className="mt-1 text-[11px] leading-[1.65] text-ink-500">{h.desc}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ────────────────────────── App ────────────────────────── */

export default function App() {
  const messages = useChatStore((s) => s.messages);
  const streaming = useChatStore((s) => s.streaming);
  const traceId = useChatStore((s) => s.traceId);
  const ask = useChatStore((s) => s.ask);
  const stop = useChatStore((s) => s.stop);
  const reset = useChatStore((s) => s.reset);
  const retry = useChatStore((s) => s.retry);

  const [cite, setCite] = useState<CitationEvent | null>(null);
  const [graphFull, setGraphFull] = useState(false);

  const lastAssistant = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === 'assistant') return messages[i];
    }
    return null;
  }, [messages]);

  // 支持 ?q=xxx 直接带问题打开，方便分享与演示（也方便自动化截图）
  useEffect(() => {
    const q = new URLSearchParams(window.location.search).get('q');
    if (q) void ask(q);
    // 只在挂载时读一次
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 全屏图谱按 Esc 退出
  useEffect(() => {
    if (!graphFull) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setGraphFull(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [graphFull]);

  return (
    <div className="flex h-full flex-col bg-paper-50">
      {/* ── 顶栏 ── */}
      <header className="z-10 shrink-0 border-b border-line bg-paper-50/85 backdrop-blur-md">
        <div className="mx-auto flex h-14 w-full max-w-[1560px] items-center gap-6 px-5">
          <div className="shrink-0">
            <div className="font-serif text-[15px] font-semibold leading-none tracking-tight text-ink-900">
              CodeAtlas
            </div>
            <div className="mt-1 text-[10px] leading-none tracking-wide text-ink-400">
              计算机知识库智能体
            </div>
          </div>

          <div className="hidden min-w-0 flex-1 justify-center md:flex">
            <AgentRail message={lastAssistant} />
          </div>

          <div className="ml-auto flex shrink-0 items-center gap-2">
            {isMockMode() && (
              <span className="chip bg-amber-50 text-amber-700 ring-1 ring-amber-200">
                Mock 流
              </span>
            )}
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
      </header>

      {/* ── 主体 ── */}
      <main className="flex min-h-0 flex-1">
        {/* 左：对话 */}
        <section className="flex min-w-0 flex-1 flex-col">
          <div className="min-h-0 flex-1">
            {messages.length === 0 ? (
              <Hero />
            ) : (
              <Conversation messages={messages} onCite={setCite} onRetry={retry} />
            )}
          </div>
          <Composer streaming={streaming} onSend={ask} onStop={stop} />
        </section>

        {/*
          右：过程
          首屏不显示，让 Hero 占满整宽——空面板会白白吃掉 40% 的版面。
          提问后滑入，顺带成为一个「界面开始工作」的视觉信号。
        */}
        {messages.length > 0 && (
          <aside className="hidden w-[392px] shrink-0 animate-fade-up flex-col border-l border-line bg-white/35 lg:flex">
            <div className="flex h-9 shrink-0 items-center justify-between border-b border-line/70 px-4">
              <span className="text-[11px] font-medium tracking-wide text-ink-500">推理过程</span>
              <span className="text-[10px] text-ink-400">
                {lastAssistant ? `${lastAssistant.thoughts.length} 步` : '待提问'}
              </span>
            </div>

            <div className="min-h-0 flex-1">
              <ThinkingPanel message={lastAssistant} />
            </div>

            <div className="h-[38%] min-h-[190px] shrink-0 border-t border-line/70">
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
      </main>

      {/* 图谱全屏：演示时放大讲「跨域边」用 */}
      {graphFull && (
        <div className="fixed inset-0 z-40 flex flex-col bg-paper-50/97 backdrop-blur-sm">
          <div className="flex h-11 shrink-0 items-center justify-between border-b border-line px-5">
            <div>
              <span className="text-[13px] font-semibold text-ink-900">知识图谱</span>
              <span className="ml-2 text-[11px] text-ink-400">
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
