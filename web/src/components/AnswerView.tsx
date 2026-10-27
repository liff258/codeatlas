/**
 * 答案渲染
 *
 * 真正的 Markdown 解析在 lib/markdown.tsx（知识点详情页也要用）。
 * 这里只负责「答案」特有的三件事：
 *   1. 证据不足横幅（诚实性要求，也是评测指标）
 *   2. 流式光标
 *   3. 还没出字时的等待动画
 */

import { motion } from 'framer-motion';
import { AlertTriangle } from 'lucide-react';
import type { ChatMessage } from '../store/chatStore';
import type { CitationEvent } from '../types/events';
import { MarkdownBody } from '../lib/markdown';

export default function AnswerView({
  message,
  onCite,
}: {
  message: ChatMessage;
  onCite: (c: CitationEvent) => void;
}) {
  const streaming = message.phase === 'answering' || message.phase === 'thinking';

  return (
    <div className="relative">
      {/* 证据不足时必须在顶部说明，这是诚实性要求，也是评测指标 */}
      {message.done?.insufficient_evidence && (
        <div className="mb-3 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50/70 px-3 py-2">
          <AlertTriangle size={13} className="mt-[2px] shrink-0 text-amber-600" />
          <p className="text-[12.5px] leading-5 text-amber-800">
            知识库里的证据不足，以下内容包含模型推断，请谨慎采信。
          </p>
        </div>
      )}

      {message.content ? (
        <div className={streaming ? 'streaming-caret' : ''}>
          <MarkdownBody
            content={message.content}
            ctx={{ citations: message.citations, onCite, citationsEnabled: true }}
          />
        </div>
      ) : (
        message.phase === 'thinking' && (
          <div className="flex items-center gap-2 py-1">
            <span className="text-[13.5px] text-ink-400">正在检索并组织答案</span>
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
          </div>
        )
      )}
    </div>
  );
}
