/**
 * 轻量 Markdown 渲染器（从 AnswerView 抽出）。
 *
 * 为什么手写而不引 react-markdown：
 *   正文里的 `[1]` 要变成可点击的引用按钮，找不到出处的还要显式标「无出处」。
 *   用通用渲染器得在 AST 上打补丁，反而不如只认「标题/列表/表格/粗体/行内代码/角标」
 *   这几种结构来得直接。
 *
 * 为什么要抽出来：
 *   知识点详情页的正文也是 markdown，但它**没有引用**——
 *   语料里的 `[1]` 可能只是原文的编号。如果照搬答案渲染器，
 *   每个角标都会变成红色的「无出处」，看起来像整篇文章都没依据。
 *   所以这里加一个 citationsEnabled 开关：关掉时 [n] 按普通文本渲染。
 */

import { Fragment, type ReactNode } from 'react';
import type { CitationEvent } from '../types/events';

export interface MarkdownCtx {
  citations: Record<number, CitationEvent>;
  onCite: (c: CitationEvent) => void;
  /** false 时 [n] 当普通文本，不渲染成角标 */
  citationsEnabled: boolean;
}

const INLINE = /(\*\*[^*]+\*\*|`[^`]+`|\[\d+\])/g;

function renderInline(text: string, ctx: MarkdownCtx): ReactNode {
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
    if (m && ctx.citationsEnabled) {
      const id = Number(m[1]);
      const cite = ctx.citations[id];
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
            onClick={() => ctx.onCite(cite)}
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

function renderTable(lines: string[], key: number, ctx: MarkdownCtx, keyPrefix = ''): ReactNode {
  const header = splitRow(lines[0]);
  const rows = lines.slice(2).filter((l) => l.trim() !== '').map(splitRow);

  return (
    <div key={`${keyPrefix}${key}`} className="my-3 overflow-x-auto">
      <table className="w-full border-collapse text-[13.5px]">
        <thead>
          <tr>
            {header.map((cell, i) => (
              <th
                key={i}
                className="border-b border-line bg-paper-100/70 px-2.5 py-1.5 text-left font-semibold text-ink-900"
              >
                {renderInline(cell, ctx)}
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
                  {renderInline(cell, ctx)}
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

/**
 * 先按 ``` 围栏切段，再对普通文本按空行分块。
 *
 * 顺序不能反：代码块内部经常有空行，如果先按 \n{2,} 切，
 * 一段代码会被拆成好几块，围栏也对不上，最后整段代码都渲染成普通文本。
 */
type Segment = { type: 'code'; lang: string; text: string } | { type: 'text'; text: string };

function splitSegments(content: string): Segment[] {
  const lines = content.split('\n');
  const out: Segment[] = [];
  let buf: string[] = [];

  const flush = () => {
    if (buf.length > 0) {
      out.push({ type: 'text', text: buf.join('\n') });
      buf = [];
    }
  };

  for (let i = 0; i < lines.length; i++) {
    const fence = /^```([\w+#-]*)\s*$/.exec(lines[i].trim());
    if (fence) {
      flush();
      const body: string[] = [];
      i++;
      while (i < lines.length && !/^```\s*$/.test(lines[i].trim())) {
        body.push(lines[i]);
        i++;
      }
      out.push({ type: 'code', lang: fence[1] || '', text: body.join('\n') });
      continue;
    }
    buf.push(lines[i]);
  }
  flush();
  return out;
}

function renderCode(text: string, lang: string, key: string): ReactNode {
  return (
    <div key={key} className="my-3 overflow-hidden rounded-lg border border-line bg-paper-100/70">
      {lang && (
        <div className="border-b border-line/70 px-3 py-1 font-mono text-[10px] uppercase tracking-wide text-ink-400">
          {lang}
        </div>
      )}
      <pre className="overflow-x-auto px-3 py-2.5">
        <code className="font-mono text-[12px] leading-[1.7] text-ink-800">{text}</code>
      </pre>
    </div>
  );
}

function renderBlocks(content: string, ctx: MarkdownCtx, keyPrefix = ''): ReactNode {
  // 尾部多余空白去掉，避免流式过程中出现空段落跳动
  const blocks = content.replace(/\s+$/, '').split(/\n{2,}/);

  return blocks.map((block, bi) => {
    const lines = block.split('\n');

    // 小标题。
    // 不能要求「整块只有一行」：模型经常写 `## 标题` 后紧跟列表、中间不留空行，
    // 那样整块是多行的，会掉到段落分支渲染成字面的 `## 标题`。
    // 正确处理是：首行当标题，剩下的递归当新块渲染。
    const h = /^(#{1,4})\s+(.*)$/.exec(lines[0]);
    if (h) {
      const rest = lines.slice(1).join('\n').trim();
      return (
        <Fragment key={`${keyPrefix}${bi}`}>
          <h3 className="mt-4 mb-1.5 font-serif text-[15px] font-semibold text-ink-900">
            {renderInline(h[2], ctx)}
          </h3>
          {rest !== '' && renderBlocks(rest, ctx)}
        </Fragment>
      );
    }

    // 表格要在列表之前判断：表格行开头是 |，不会被列表正则命中，
    // 但不先拦下来会掉进段落分支渲染成一堆竖线文本。
    if (isTableBlock(lines)) {
      return renderTable(lines, bi, ctx, keyPrefix);
    }

    const isUl = lines.every((l) => /^[-*]\s+/.test(l.trim()) || l.trim() === '');
    const isOl = lines.every((l) => /^\d+[.)]\s+/.test(l.trim()) || l.trim() === '');
    if ((isUl || isOl) && lines.some((l) => l.trim() !== '')) {
      const items = lines.filter((l) => l.trim() !== '');
      const Tag = isUl ? 'ul' : 'ol';
      return (
        <Tag
          key={`${keyPrefix}${bi}`}
          className={`my-2 space-y-1 pl-4 ${isUl ? 'list-disc' : 'list-decimal'} marker:text-ink-400`}
        >
          {items.map((l, li) => (
            <li key={li} className="text-[14.5px] leading-[1.78] text-ink-700">
              {renderInline(l.replace(/^[-*]\s+/, '').replace(/^\d+[.)]\s+/, ''), ctx)}
            </li>
          ))}
        </Tag>
      );
    }

    return (
      <p key={`${keyPrefix}${bi}`} className="my-2 text-[14.5px] leading-[1.78] text-ink-700 first:mt-0">
        {lines.map((l, li) => (
          <Fragment key={li}>
            {li > 0 && <br />}
            {renderInline(l, ctx)}
          </Fragment>
        ))}
      </p>
    );
  });
}

export function MarkdownBody({ content, ctx }: { content: string; ctx: MarkdownCtx }) {
  const segments = splitSegments(content.replace(/\s+$/, ''));

  return (
    <>
      {segments.map((seg, i) =>
        seg.type === 'code'
          ? renderCode(seg.text, seg.lang, `c${i}`)
          : <Fragment key={`t${i}`}>{renderBlocks(seg.text, ctx, `t${i}-`)}</Fragment>,
      )}
    </>
  );
}
