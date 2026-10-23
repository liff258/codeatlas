/**
 * 思考面板
 *
 * 这是「思考可视化」这个得分点最集中的地方，所以每一项都要能被人读懂，
 * 而不是把 JSON 打印出来。三类信息给三种不同的视觉重量：
 *   step      → 一行，轻
 *   plan      → 卡片，中
 *   grade     → 最重的卡片，带覆盖度标尺（自评-决策是整个 Agent 的"大脑时刻"）
 *   retrieval → 卡片，带分数条（分数条能直接看出重排前后的差别）
 */

import { useEffect, useRef } from 'react';
import { motion } from 'framer-motion';
import {
  ArrowRight,
  CircleDashed,
  GitBranch,
  Search,
  Sparkles,
  Target,
} from 'lucide-react';
import type { ChatMessage, ThoughtItem } from '../store/chatStore';

/* ────────────────────────── 小工具 ────────────────────────── */

const INTENT_LABEL: Record<string, string> = {
  concept: '概念解释',
  compare: '对比辨析',
  debug: '问题排查',
  quiz: '出题自测',
  chitchat: '闲聊',
};

const DECISION: Record<string, { text: string; cls: string }> = {
  proceed: { text: '证据足够 · 直接生成', cls: 'bg-emerald-50 text-emerald-700 ring-emerald-200' },
  rewrite: { text: '证据不足 · 改写重查', cls: 'bg-amber-50 text-amber-700 ring-amber-200' },
  give_up: { text: '重查用尽 · 降级作答', cls: 'bg-red-50 text-red-700 ring-red-200' },
};

function pct(v: number) {
  return `${Math.round(v * 100)}%`;
}

/* ────────────────────────── 单项渲染 ────────────────────────── */

function StepRow({ t }: { t: Extract<ThoughtItem, { kind: 'step' }> }) {
  const color =
    t.status === 'running'
      ? 'text-ink-900'
      : t.status === 'degraded'
        ? 'text-bridge'
        : t.status === 'failed'
          ? 'text-red-600'
          : 'text-ink-500';

  return (
    <div className="flex items-start gap-2 py-[3px]">
      {t.status === 'running' ? (
        <CircleDashed size={12} className="mt-[3px] shrink-0 animate-spin text-ink-900" />
      ) : (
        <span
          className={[
            'mt-[6px] shrink-0 w-1.5 h-1.5 rounded-full',
            t.status === 'ok'
              ? 'bg-ink-400'
              : t.status === 'degraded'
                ? 'bg-bridge'
                : 'bg-red-600',
          ].join(' ')}
        />
      )}
      <div className="min-w-0">
        <span className={`text-[12.5px] leading-5 ${color}`}>{t.label}</span>
        {t.detail && (
          <span
            className={[
              'ml-1.5 chip align-[1px]',
              t.status === 'degraded'
                ? 'bg-amber-50 text-amber-700 ring-1 ring-amber-200'
                : 'bg-red-50 text-red-700 ring-1 ring-red-200',
            ].join(' ')}
          >
            {t.detail}
          </span>
        )}
      </div>
    </div>
  );
}

function PlanCard({ t }: { t: Extract<ThoughtItem, { kind: 'plan' }> }) {
  return (
    <div className="rounded-lg border border-line bg-white/70 p-2.5 my-1">
      <div className="flex items-center gap-1.5 mb-2">
        <GitBranch size={12} className="text-ink-500" />
        <span className="text-[12px] font-medium text-ink-700">拆成 {t.subQueries.length} 个子查询</span>
        <span className="chip bg-paper-100 text-ink-500 ring-1 ring-line">
          {INTENT_LABEL[t.intent] ?? t.intent}
        </span>
        <span className="chip bg-paper-100 text-ink-500 ring-1 ring-line">{t.hops} 跳</span>
      </div>
      <div className="space-y-1">
        {t.subQueries.map((q) => (
          <div key={q.id} className="flex items-baseline gap-1.5">
            <span className="font-mono text-[10px] text-ink-400 shrink-0 w-4">{q.id}</span>
            <span className="text-[12px] text-ink-700 leading-5">{q.text}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function RetrievalCard({ t }: { t: Extract<ThoughtItem, { kind: 'retrieval' }> }) {
  const top = t.chunks.slice(0, 4);
  const rest = t.chunks.length - top.length;

  return (
    <div className="rounded-lg border border-line bg-white/70 p-2.5 my-1">
      <div className="flex items-center gap-1.5 mb-2">
        <Search size={12} className="text-ink-500" />
        <span className="text-[12px] font-medium text-ink-700">
          召回 {t.chunks.length} 条
        </span>
        <span className="font-mono text-[10px] text-ink-400">{t.queryId}</span>
        <span className="chip bg-paper-100 text-ink-500 ring-1 ring-line">{t.engine}</span>
        {t.rewriteRound > 0 && (
          <span className="chip bg-amber-50 text-amber-700 ring-1 ring-amber-200">
            第 {t.rewriteRound} 轮补检索
          </span>
        )}
      </div>

      <div className="space-y-[5px]">
        {top.map((c) => (
          <div key={c.id} className="group">
            <div className="flex items-center gap-1.5">
              <span className="text-[11px] text-ink-700 truncate flex-1 min-w-0" title={c.heading_path}>
                {c.heading_path}
              </span>
              <span className="font-mono text-[10px] text-ink-400 shrink-0 tabular-nums">
                {c.score.toFixed(2)}
              </span>
            </div>
            {/* 分数条：一眼看出重排后的差距 */}
            <div className="h-[3px] mt-[3px] rounded-full bg-paper-200 overflow-hidden">
              <div
                className="h-full rounded-full bg-ink-400/70 transition-[width] duration-500 ease-out"
                style={{ width: `${Math.max(3, Math.min(100, c.score * 100))}%` }}
              />
            </div>
          </div>
        ))}
      </div>
      {rest > 0 && <div className="mt-1 text-[10.5px] text-ink-400">还有 {rest} 条未展开</div>}
    </div>
  );
}

function GradeCard({ t }: { t: Extract<ThoughtItem, { kind: 'grade' }> }) {
  const d = DECISION[t.decision] ?? DECISION.proceed;
  const ratio = Math.max(0, Math.min(1, t.coverage));

  return (
    <div className="rounded-lg border border-ink-900/12 bg-white p-3 my-1.5 shadow-card">
      <div className="flex items-center gap-1.5 mb-2">
        <Target size={13} className="text-ink-700" />
        <span className="text-[12.5px] font-semibold text-ink-900">证据自评</span>
        <span className={`chip ring-1 ${d.cls}`}>{d.text}</span>
      </div>

      {/* 覆盖度标尺：阈值那根竖线是重点，它解释了"为什么"要重查 */}
      <div className="relative h-1.5 rounded-full bg-paper-200 overflow-visible mb-2">
        <div
          className={[
            'h-full rounded-full transition-[width] duration-500 ease-out',
            t.decision === 'proceed' ? 'bg-emerald-500' : t.decision === 'rewrite' ? 'bg-bridge' : 'bg-red-500',
          ].join(' ')}
          style={{ width: `${ratio * 100}%` }}
        />
        <div
          className="absolute top-[-3px] bottom-[-3px] w-[2px] bg-ink-900/70 rounded-full"
          style={{ left: `${Math.min(100, t.threshold * 100)}%` }}
          title={`阈值 ${pct(t.threshold)}`}
        />
      </div>

      <div className="flex items-center justify-between text-[10.5px] text-ink-400 tabular-nums mb-1.5">
        <span>
          覆盖度 <span className="text-ink-900 font-medium">{pct(t.coverage)}</span>
        </span>
        <span>阈值 {pct(t.threshold)}</span>
      </div>

      <div className="text-[12px] text-ink-700 leading-5">{t.reason}</div>

      {t.lowIds.length > 0 && (
        <div className="mt-1.5 flex items-center gap-1 flex-wrap">
          <span className="text-[10.5px] text-ink-400">低分片段</span>
          {t.lowIds.map((id) => (
            <span key={id} className="chip bg-red-50 text-red-600 ring-1 ring-red-100 font-mono">
              {id}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

/* ────────────────────────── 主体 ────────────────────────── */

export default function ThinkingPanel({ message }: { message: ChatMessage | null }) {
  const scrollRef = useRef<HTMLDivElement>(null);

  // 直接改 scrollTop，不用 scrollIntoView：
  // 后者会把祖先滚动容器一起带着滚，而且 smooth 在事件高频到达时根本追不上
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [message?.thoughts.length, message?.content.length]);

  if (!message || message.thoughts.length === 0) {
    return (
      <div className="h-full grid place-items-center px-6">
        <div className="text-center">
          <Sparkles size={18} className="mx-auto text-ink-400 mb-2" />
          <p className="text-[12.5px] text-ink-400 leading-5">
            提问后，这里会实时显示
            <br />
            Agent 的每一步判断
          </p>
        </div>
      </div>
    );
  }

  return (
    <div ref={scrollRef} className="h-full overflow-y-auto px-4 py-3">
      <div className="relative pl-3">
        {/* 时间轴脊线 */}
        <div className="absolute left-[5px] top-2 bottom-2 w-px bg-line" />

        {/* 入场用 CSS 动画而不是 framer-motion：
            内容可见性不该依赖 JS 动画是否跑起来（截图、低端机、动画被打断都会白屏） */}
        {message.thoughts.map((t) => (
          <div key={`${t.kind}-${t.seq}`} className="relative animate-fade-up">
            {/* 轴上的点 */}
            <span
              className={[
                'absolute left-[-11px] top-[7px] w-[7px] h-[7px] rounded-full ring-2 ring-white',
                t.kind === 'grade' ? 'bg-ink-900' : 'bg-paper-300',
              ].join(' ')}
            />

            {t.kind === 'step' && <StepRow t={t} />}
            {t.kind === 'plan' && <PlanCard t={t} />}
            {t.kind === 'retrieval' && <RetrievalCard t={t} />}
            {t.kind === 'grade' && <GradeCard t={t} />}
          </div>
        ))}

        {message.phase === 'thinking' && (
          <div className="flex items-center gap-2 py-1.5 pl-0.5">
            <span className="flex gap-0.5">
              {[0, 1, 2].map((i) => (
                <motion.span
                  key={i}
                  className="w-1 h-1 rounded-full bg-ink-400"
                  animate={{ opacity: [0.25, 1, 0.25] }}
                  transition={{ duration: 1.1, repeat: Infinity, delay: i * 0.16 }}
                />
              ))}
            </span>
            <span className="text-[11px] text-ink-400">推理中…</span>
          </div>
        )}

      </div>

      {message.thoughts.length > 0 && message.phase !== 'thinking' && (
        <div className="mt-2 pl-3 flex items-center gap-1 text-[10.5px] text-ink-400">
          <ArrowRight size={10} />
          共 {message.thoughts.length} 个推理步骤
        </div>
      )}
    </div>
  );
}
