/**
 * 答案渲染
 *
 * 没用 react-markdown，原因是这里有个特殊需求：正文里的 [1] [2] 角标
 * 要替换成可交互的引用按钮，并且**找不到出处的角标要显式标成「无出处」**。
 * 用通用 Markdown 渲染器反而要在 AST 上打补丁，不如手写一个只认
 * 「段落 / 小标题 / 列表 / 粗体 / 行内代码 / 角标」的轻量渲染器，40 行搞定。
 */

import { Fragment, type ReactNode } from 'react';
import { motion } from 'framer-motion';
import { AlertTriangle } from 'lucide-react';
import type { ChatMessage } from '../store/chatStore';
import type { CitationEvent } from '../types/events';

/* ────────────────────────── 行内 ────────────────────────── */

const INLINE = /(\*\*[^*]+\*\*|`[^`]+`|\[\d+\])/g;

function renderInline(
  text: string,
  citations: Record<number, CitationEvent>,
  onCite: (c: CitationEvent) => void,
): ReactNode {
  const parts = text.split(INLINE).filter((p) => p !== '');

  return parts.map((p, i) => {
    if (p.startsWith('**') && p.endsWith('**')) {
      return (
        <strong key={i} className="font-semibold text-ink-900">
          {p.slice(2, -2)}
        </strong>
      );
    }
    if (p.startsWith('`') && p.endsWith('`')) {
      return (
        <code
          key={i}
          className="mx-[1px] rounded bg-paper-100 px-1 py-[1px] font-mono text-[0.88em] text-ink-700 ring-1 ring-line"
        >
          {p.slice(1, -1)}
        </code>
      );
    }
    const m = /^\[(\d+)\]$/.exec(p);
    if (m) {
      const id = Number(m[1]);
      const cite = citations[id];
      if (!cite) {
        // 契约：找不到支撑就不发 citation 事件，前端必须显式标注
        return (
          <sup key={i} className="ml-[1px]">
            <span
              title="该论点没有找到原文出处"
              className="inline-flex items-center gap-[1px] rounded bg-red-50 px-[3px] text-[9.5px] font-medium text-red-600 ring-1 ring-red-100 align-super"
            >
              无出处
            </span>
          </sup>
        );
      }
      return (
        <sup key={i} className="ml-[1px]">
          <button
            type="button"
            onClick={() => onCite(cite)}
            title={cite.quote}
            className="rounded bg-paper-200/80 px-[3.5px] text-[9.5px] font-medium text-ink-700 ring-1 ring-line align-super transition-colors hover:bg-ink-900 hover:text-paper-50"
          >
            {id}
          </button>
        </sup>
      );
    }
    return <Fragment key={i}>{p}</Fragment>;
  });
}

/* ────────────────────────── 表格 ────────────────────────── */

/** 把 `| a | b |` 拆成 ['a', 'b']。首尾的竖线去掉，单元格去空白。 */
function splitRow(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((c) => c.trim());
}

/**
 * 是不是一张 Markdown 表格。
 *
 * 判据：第一行以 | 开头，第二行是分隔行（只含 - : | 和空白）。
 * 只认这两条是因为流式输出时表格可能只到了表头，那时候先按段落渲染，
 * 等分隔行到了再切成表格——不需要额外的"可能变表格"状态。
 */
function isTableBlock(lines: string[]): boolean {
  if (lines.length < 2) return false;
  if (!/^\s*\|/.test(lines[0])) return false;
  return /^\s*\|[\s:|-]+\|\s*$/.test(lines[1]) && lines[1].includes('-');
}

function renderTable(
  lines: string[],
  key: number,
  citations: Record<number, CitationEvent>,
  onCite: (c: CitationEvent) => void,
): ReactNode {
  const header = splitRow(lines[0]);
  const rows = lines.slice(2).filter((l) => l.trim() !== '').map(splitRow);

  return (
    <div key={key} className="my-3 overflow-x-auto">
      <table className="w-full border-collapse text-[13.5px]">
        <thead>
          <tr>
            {header.map((cell, i) => (
              <th
                key={i}
                className="border-b border-line bg-paper-100/70 px-2.5 py-1.5 text-left font-semibold text-ink-900"
              >
                {renderInline(cell, citations, onCite)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, ri) => (
            <tr key={ri}>
              {row.map((cell, ci) => (
                <td
                  key={ci}
                  className="border-b border-line/60 px-2.5 py-1.5 align-top leading-[1.7] text-ink-700"
                >
                  {renderInline(cell, citations, onCite)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ────────────────────────── 块级 ────────────────────────── */

function renderBlocks(
  content: string,
  citations: Record<number, CitationEvent>,
  onCite: (c: CitationEvent) => void,
): ReactNode {
  // 尾部多余空白去掉，避免流式过程中出现空段落跳动
  const blocks = content.replace(/\s+$/, '').split(/\n{2,}/);

  return blocks.map((block, bi) => {
    const lines = block.split('\n');

    // 小标题。
    // 注意不能要求「整块只有一行」：模型经常写 `## 标题` 后紧跟列表、中间不留空行，
    // 那样整块是多行的，会掉到段落分支渲染成字面的 `## 标题`。
    // 正确处理是：首行当标题，剩下的递归当新块渲染。
    const h = /^(#{1,4})\s+(.*)$/.exec(lines[0]);
    if (h) {
      const rest = lines.slice(1).join('\n').trim();
      return (
        <Fragment key={bi}>
          <h3 className="mt-4 mb-1.5 font-serif text-[15px] font-semibold text-ink-900">
            {renderInline(h[2], citations, onCite)}
          </h3>
          {rest !== '' && renderBlocks(rest, citations, onCite)}
        </Fragment>
      );
    }

    // 表格要放在列表判断之前：表格行的开头是 |，不会被列表正则命中，
    // 但如果不先拦下来，会掉进最后的段落分支渲染成一堆竖线文本。
    if (isTableBlock(lines)) {
      return renderTable(lines, bi, citations, onCite);
    }

    // 列表
    const isUl = lines.every((l) => /^[-*]\s+/.test(l.trim()) || l.trim() === '');
    const isOl = lines.every((l) => /^\d+[.)]\s+/.test(l.trim()) || l.trim() === '');
    if ((isUl || isOl) && lines.some((l) => l.trim() !== '')) {
      const items = lines.filter((l) => l.trim() !== '');
      const Tag = isUl ? 'ul' : 'ol';
      return (
        <Tag
          key={bi}
          className={`my-2 space-y-1 pl-4 ${isUl ? 'list-disc' : 'list-decimal'} marker:text-ink-400`}
        >
          {items.map((l, li) => (
            <li key={li} className="text-[14.5px] leading-[1.78] text-ink-700">
              {renderInline(l.replace(/^[-*]\s+/, '').replace(/^\d+[.)]\s+/, ''), citations, onCite)}
            </li>
          ))}
        </Tag>
      );
    }

    return (
      <p key={bi} className="my-2 text-[14.5px] leading-[1.78] text-ink-700 first:mt-0">
        {lines.map((l, li) => (
          <Fragment key={li}>
            {li > 0 && <br />}
            {renderInline(l, citations, onCite)}
          </Fragment>
        ))}
      </p>
    );
  });
}

/* ────────────────────────── 主体 ────────────────────────── */

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
          {renderBlocks(message.content, message.citations, onCite)}
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
