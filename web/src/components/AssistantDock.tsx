/**
 * 全局助手：右下角浮层。
 *
 * 定位：它是「学到一半想追问」的出口，不是入口。
 * 所以默认收起，只有一个圆形按钮；打开后是 480px 的抽屉，不抢页面主体。
 *
 * 会话独立：用 assistantStore（createChatStore 造的第二个实例，不持久化）。
 * 这点很重要——如果复用主对话 store，两边会互相 abort、互相覆盖快照。
 */

import { useEffect, useState } from 'react';
import { MessageSquare, Sparkles, X } from 'lucide-react';
import Conversation from './Conversation';
import Composer from './Composer';
import SourceCard from './SourceCard';
import { useAssistantStore } from '../store/assistantStore';
import type { CitationEvent } from '../types/events';

const HINTS = [
  '这个知识点和哪些概念有关？',
  '面试时这块一般怎么问？',
  '给我一个能跑的例子',
];

export default function AssistantDock() {
  const [open, setOpen] = useState(false);
  const [cite, setCite] = useState<CitationEvent | null>(null);

  const messages = useAssistantStore((s) => s.messages);
  const streaming = useAssistantStore((s) => s.streaming);
  const ask = useAssistantStore((s) => s.ask);
  const stop = useAssistantStore((s) => s.stop);
  const reset = useAssistantStore((s) => s.reset);
  const retry = useAssistantStore((s) => s.retry);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open]);

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        title="问助手（不会打断主对话）"
        className="fixed bottom-5 right-5 z-30 flex h-11 w-11 items-center justify-center rounded-full bg-ink-900 text-paper-50 shadow-lift transition-transform hover:scale-105"
      >
        <MessageSquare size={17} />
      </button>
    );
  }

  return (
    <>
      <div className="fixed bottom-0 right-0 z-30 flex h-[72vh] w-full flex-col border-l border-line bg-paper-50 shadow-lift sm:w-[480px]">
        <div className="flex h-11 shrink-0 items-center justify-between border-b border-line px-3">
          <div className="flex items-center gap-1.5">
            <Sparkles size={12} className="text-bridge" />
            <span className="text-[12.5px] font-medium text-ink-900">助手</span>
            <span className="text-[10.5px] text-ink-400">独立会话 · 不影响主对话</span>
          </div>
          <div className="flex items-center gap-1">
            {messages.length > 0 && (
              <button
                type="button"
                onClick={reset}
                className="rounded px-1.5 py-1 text-[11px] text-ink-400 transition-colors hover:text-ink-900"
              >
                清空
              </button>
            )}
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="rounded p-1 text-ink-400 transition-colors hover:bg-paper-100 hover:text-ink-900"
              title="收起（Esc）"
            >
              <X size={13} />
            </button>
          </div>
        </div>

        <div className="min-h-0 flex-1">
          {messages.length === 0 ? (
            <div className="flex h-full flex-col justify-center px-6">
              <p className="text-[12.5px] leading-relaxed text-ink-500">
                在这里追问不会打断你正在看的内容。答案同样标注原文出处。
              </p>
              <div className="mt-3 space-y-1.5">
                {HINTS.map((h) => (
                  <button
                    key={h}
                    type="button"
                    onClick={() => void ask(h)}
                    className="block w-full rounded-md border border-line bg-white px-2.5 py-1.5 text-left text-[12px] text-ink-600 transition-colors hover:border-ink-400/40 hover:text-ink-900"
                  >
                    {h}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <Conversation messages={messages} onCite={setCite} onRetry={retry} />
          )}
        </div>

        <Composer streaming={streaming} onSend={ask} onStop={stop} />
      </div>

      <SourceCard citation={cite} onClose={() => setCite(null)} />
    </>
  );
}
