/**
 * 输入区
 *
 * Enter 发送 / Shift+Enter 换行 / 输入框随内容长高 / 流式期间变成「停止」按钮。
 * 这些都是小事，但演示时按一下 Enter 就出结果，比找按钮点要顺得多。
 */

import { useEffect, useRef, useState } from 'react';
import { ArrowUp, CornerDownLeft, Square } from 'lucide-react';

const DEMO_QUESTION = '向量检索为什么不能用 B+ 树加速？那 RAG 的召回率该怎么提？';

const EXAMPLES = [
  DEMO_QUESTION,
  'G1 的 SATB 为什么要配写屏障？漏标了会怎样？',
  'Spring 的循环依赖三级缓存，和 Agent 的记忆管理有什么相通之处？',
];

export default function Composer({
  streaming,
  onSend,
  onStop,
}: {
  streaming: boolean;
  onSend: (q: string) => void;
  onStop: () => void;
}) {
  const [value, setValue] = useState('');
  const taRef = useRef<HTMLTextAreaElement>(null);

  // 自适应高度：最高 5 行，再多就内部滚动
  useEffect(() => {
    const el = taRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 132)}px`;
  }, [value]);

  const submit = () => {
    const q = value.trim();
    if (!q || streaming) return;
    onSend(q);
    setValue('');
  };

  return (
    <div className="border-t border-line bg-paper-50/80 backdrop-blur-sm">
      <div className="mx-auto w-full max-w-3xl px-5 py-3">
        {/* 示例问题：降低第一次使用的门槛，也是演示时的提词器 */}
        {!streaming && (
          <div className="mb-2 flex flex-wrap gap-1.5">
            {EXAMPLES.map((ex) => (
              <button
                key={ex}
                type="button"
                onClick={() => {
                  setValue(ex);
                  taRef.current?.focus();
                }}
                className="max-w-full truncate rounded-full border border-line bg-white/70 px-2.5 py-1 text-[11px] text-ink-500 transition-colors hover:border-ink-400/40 hover:text-ink-900"
              >
                {ex}
              </button>
            ))}
          </div>
        )}

        <div
          className={[
            'flex items-end gap-2 rounded-xl border bg-white px-3 py-2 transition-shadow',
            streaming ? 'border-line' : 'border-line focus-within:border-ink-400/50 focus-within:shadow-lift',
          ].join(' ')}
        >
          <textarea
            ref={taRef}
            rows={1}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                submit();
              }
            }}
            placeholder="问一个跨后端与 AI 的问题，比如：向量检索为什么不能用 B+ 树加速？"
            className="max-h-[132px] flex-1 resize-none bg-transparent py-[5px] text-[14px] leading-6 text-ink-900 outline-none placeholder:text-ink-400/80"
          />

          {streaming ? (
            <button
              type="button"
              onClick={onStop}
              title="停止生成"
              className="mb-[1px] grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-ink-900 text-paper-50 transition-opacity hover:opacity-85"
            >
              <Square size={12} fill="currentColor" />
            </button>
          ) : (
            <button
              type="button"
              onClick={submit}
              disabled={!value.trim()}
              title="发送（Enter）"
              className="mb-[1px] grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-ink-900 text-paper-50 transition-all hover:opacity-85 disabled:bg-paper-300 disabled:text-ink-400"
            >
              <ArrowUp size={15} strokeWidth={2.6} />
            </button>
          )}
        </div>

        <div className="mt-1.5 flex items-center justify-between text-[10.5px] text-ink-400">
          <span className="flex items-center gap-1">
            <CornerDownLeft size={10} />
            Enter 发送 · Shift + Enter 换行
          </span>
          <span>回答均来自本地知识库，附原文出处</span>
        </div>
      </div>
    </div>
  );
}
