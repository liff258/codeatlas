/**
 * 对话流
 *
 * 助手消息底部的指标条（耗时 / 覆盖度 / 改写次数 / 成本）不是装饰：
 * 「产品透明度」是评分项，也是这个工具跟套壳聊天框最直观的区别。
 */

import { useEffect, useRef } from 'react';
import { Clock, Coins, RefreshCw, RotateCcw, ShieldAlert } from 'lucide-react';
import type { ChatMessage } from '../store/chatStore';
import type { CitationEvent } from '../types/events';
import AnswerView from './AnswerView';

const STOP_LABEL: Record<string, string> = {
  normal: '正常结束',
  step_limit: '达到步数上限',
  rewrite_limit: '达到改写上限',
  timeout: '超时',
  budget: '超出预算',
  error: '出错',
};

const ERR_HINT: Record<string, string> = {
  LLM_TIMEOUT: '模型响应超时',
  LLM_RATE_LIMIT: '模型限流，稍后再试',
  RETRIEVAL_EMPTY: '知识库里还没有相关内容，先上传文档',
  INTERNAL: '服务内部错误',
};

function UserBubble({ m }: { m: ChatMessage }) {
  return (
    <div className="mb-6 animate-fade-up">
      <div className="mb-1 text-[10.5px] font-medium uppercase tracking-wider text-ink-400">你的问题</div>
      <div className="border-l-2 border-ink-900/25 pl-3">
        <p className="text-[15px] font-medium leading-[1.7] text-ink-900">{m.content}</p>
      </div>
    </div>
  );
}

function MetaBar({ m }: { m: ChatMessage }) {
  const d = m.done;
  if (!d) return null;

  return (
    <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-1.5 border-t border-line/70 pt-2.5 text-[10.5px] text-ink-400 tabular-nums">
      <span className="flex items-center gap-1">
        <Clock size={10} />
        {(d.latency_ms / 1000).toFixed(2)}s
      </span>
      <span>
        覆盖度 <span className="text-ink-700">{(d.coverage * 100).toFixed(0)}%</span>
      </span>
      <span>
        改写 <span className="text-ink-700">{d.rewrite_count}</span> 次
      </span>
      <span className="flex items-center gap-1">
        <Coins size={10} />¥{d.usage.cost_cny.toFixed(4)}
      </span>
      <span className="text-ink-400/70">
        {d.usage.input_tokens} in / {d.usage.output_tokens} out
      </span>
      <span
        className={[
          'ml-auto chip ring-1',
          d.stop_reason === 'normal'
            ? 'bg-paper-100 text-ink-500 ring-line'
            : 'bg-amber-50 text-amber-700 ring-amber-200',
        ].join(' ')}
      >
        {STOP_LABEL[d.stop_reason] ?? d.stop_reason}
      </span>
    </div>
  );
}

function ErrorBox({ m, onRetry }: { m: ChatMessage; onRetry: () => void }) {
  if (!m.error) return null;
  return (
    <div className="mt-2 rounded-lg border border-red-200 bg-red-50/60 p-3">
      <div className="flex items-start gap-2">
        <ShieldAlert size={14} className="mt-[2px] shrink-0 text-red-600" />
        <div className="min-w-0 flex-1">
          <div className="text-[12.5px] font-medium text-red-800">
            {ERR_HINT[m.error.code] ?? '请求失败'}
          </div>
          <div className="mt-0.5 break-words text-[11.5px] leading-5 text-red-700/90">
            {m.error.message}
          </div>
          {m.error.trace_id && (
            <div className="mt-1 font-mono text-[10px] text-red-600/70">
              trace: {m.error.trace_id}
            </div>
          )}
        </div>
        {m.error.retryable && (
          <button
            type="button"
            onClick={onRetry}
            className="flex shrink-0 items-center gap-1 rounded-md border border-red-200 bg-white px-2 py-1 text-[11px] font-medium text-red-700 transition-colors hover:bg-red-100"
          >
            <RotateCcw size={10} />
            重试
          </button>
        )}
      </div>
    </div>
  );
}

export default function Conversation({
  messages,
  onCite,
  onRetry,
}: {
  messages: ChatMessage[];
  onCite: (c: CitationEvent) => void;
  onRetry: () => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const lastContent = messages[messages.length - 1]?.content ?? '';

  // 流式时跟随滚动；用 content 长度做依赖，token 批量提交时也跟得上
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages.length, lastContent.length]);

  return (
    <div ref={scrollRef} className="h-full overflow-y-auto">
      <div className="mx-auto w-full max-w-3xl px-5 py-6">
        {messages.map((m) =>
          m.role === 'user' ? (
            <UserBubble key={m.id} m={m} />
          ) : (
            <div key={m.id} className="mb-8">
              <div className="mb-1 flex items-center gap-1.5 text-[10.5px] font-medium uppercase tracking-wider text-ink-400">
                <RefreshCw size={9} className={m.phase === 'thinking' ? 'animate-spin' : ''} />
                CodeAtlas
              </div>
              <AnswerView message={m} onCite={onCite} />
              <ErrorBox m={m} onRetry={onRetry} />
              <MetaBar m={m} />
            </div>
          ),
        )}
      </div>
    </div>
  );
}
