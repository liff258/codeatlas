/**
 * 知识点详情。
 *
 * 三块：正文、涉及概念、相关知识点。
 *
 * 正文用 MarkdownBody 但关掉引用角标——语料里的 `[1]` 可能只是原文编号，
 * 开着的话每个角标都会渲染成红色「无出处」，看起来像整篇文章都没依据。
 */

import { ChevronLeft, ChevronRight, Loader2, Network, MessageSquare } from 'lucide-react';
import KnowledgePointCard from '../components/KnowledgePointCard';
import { MarkdownBody } from '../lib/markdown';
import { useAsync } from '../lib/useAsync';
import { getKnowledgePoint, type KnowledgePointDetail } from '../lib/learning';
import { navigate } from '../lib/router';

const NOOP_CITE = () => {};

export default function KnowledgePointPage({ id }: { id: string }) {
  const { data, loading, error } = useAsync<KnowledgePointDetail>(
    (signal) => getKnowledgePoint(id, signal),
    [id],
  );

  if (loading) {
    return (
      <div className="flex flex-1 items-center justify-center gap-2 text-[12.5px] text-ink-400">
        <Loader2 size={13} className="animate-spin" />
        加载中…
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3">
        <p className="text-[13px] text-ink-500">{error ?? '知识点不存在'}</p>
        <button
          type="button"
          onClick={() => navigate('/')}
          className="rounded-md border border-line bg-white px-3 py-1.5 text-[12px] text-ink-600 hover:text-ink-900"
        >
          回首页
        </button>
      </div>
    );
  }

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto flex w-full max-w-[1180px] gap-8 px-6 py-8">
        {/* 正文 */}
        <article className="min-w-0 flex-1">
          <div className="flex items-center gap-1 text-[11.5px] text-ink-400">
            <button
              type="button"
              onClick={() => navigate('/')}
              className="transition-colors hover:text-ink-900"
            >
              板块
            </button>
            {data.subject && (
              <>
                <span>/</span>
                <button
                  type="button"
                  onClick={() => navigate(`/s/${encodeURIComponent(data.subject!)}`)}
                  className="transition-colors hover:text-ink-900"
                >
                  {data.subject}
                </button>
              </>
            )}
            {data.breadcrumb && (
              <>
                <span>/</span>
                <span className="truncate text-ink-400">{data.breadcrumb}</span>
              </>
            )}
          </div>

          <h1 className="mt-3 font-serif text-[25px] leading-[1.4] tracking-tight text-ink-900">
            {data.title}
          </h1>

          <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-ink-400">
            {data.is_question && (
              <span className="chip bg-bridge/10 text-bridge">面试题</span>
            )}
            <span>{data.char_count} 字</span>
            <span>{data.chunk_count} 段原文</span>
            {data.doc_name && <span>来源：{data.doc_name}</span>}
          </div>

          <div className="mt-6 border-t border-line pt-5">
            <MarkdownBody
              content={data.answer}
              ctx={{ citations: {}, onCite: NOOP_CITE, citationsEnabled: false }}
            />
          </div>

          {/* 前后篇 */}
          <div className="mt-8 grid grid-cols-2 gap-2.5 border-t border-line pt-4">
            {[data.prev, data.next].map((item, i) => {
              if (!item) return <div key={i} />;
              return (
                <button
                  key={i}
                  type="button"
                  onClick={() => navigate(`/kp/${encodeURIComponent(item.id)}`)}
                  className={[
                    'group rounded-lg border border-line bg-white p-3 text-left transition-all hover:border-ink-400/40 hover:shadow-card',
                    i === 1 ? 'text-right' : '',
                  ].join(' ')}
                >
                  <div className="flex items-center gap-1 text-[10.5px] text-ink-400">
                    {i === 0 ? <ChevronLeft size={10} /> : null}
                    {i === 0 ? '上一篇' : '下一篇'}
                    {i === 1 ? <ChevronRight size={10} /> : null}
                  </div>
                  <div className="mt-1 line-clamp-2 text-[12.5px] leading-5 text-ink-700 group-hover:text-ink-900">
                    {item.title}
                  </div>
                </button>
              );
            })}
          </div>
        </article>

        {/* 右栏：概念 + 相关 */}
        <aside className="hidden w-[290px] shrink-0 space-y-5 lg:block">
          <section>
            <div className="mb-2 flex items-center gap-1.5 text-[11px] font-medium text-ink-500">
              <Network size={11} />
              涉及概念
            </div>
            {data.entities.length === 0 ? (
              <p className="text-[11.5px] text-ink-400">这篇没有抽到概念。</p>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {data.entities.map((e) => (
                  <button
                    key={e.id}
                    type="button"
                    onClick={() => navigate(`/e/${encodeURIComponent(e.label || e.id)}`)}
                    title={`${e.type} · ${e.subject}`}
                    className={[
                      'rounded-md border px-2 py-1 text-[11.5px] transition-colors',
                      e.domain === 'ai'
                        ? 'border-ai/25 bg-ai/5 text-ai hover:bg-ai/10'
                        : e.domain === 'backend'
                          ? 'border-backend/25 bg-backend/5 text-backend hover:bg-backend/10'
                          : 'border-line bg-white text-ink-600 hover:text-ink-900',
                    ].join(' ')}
                  >
                    {e.label}
                  </button>
                ))}
              </div>
            )}
            <p className="mt-2 text-[10.5px] leading-relaxed text-ink-400">
              点概念能看它的关系网和相关知识点。
            </p>
          </section>

          {data.related.length > 0 && (
            <section>
              <div className="mb-2 text-[11px] font-medium text-ink-500">相关知识点</div>
              <div className="space-y-2">
                {data.related.slice(0, 5).map((r) => (
                  <KnowledgePointCard key={r.id} kp={r} />
                ))}
              </div>
            </section>
          )}

          <section className="rounded-lg border border-line bg-white p-3">
            <div className="flex items-center gap-1.5 text-[11.5px] font-medium text-ink-700">
              <MessageSquare size={11} />
              没看懂？
            </div>
            <p className="mt-1.5 text-[11px] leading-relaxed text-ink-400">
              可以带着这篇的上下文去对话里追问，答案会标注原文出处。
            </p>
            <button
              type="button"
              onClick={() => navigate(`/chat?q=${encodeURIComponent(data.title)}`)}
              className="mt-2 w-full rounded-md bg-ink-900 px-2 py-1.5 text-[11.5px] text-paper-50 transition-opacity hover:opacity-90"
            >
              就这个提问
            </button>
          </section>
        </aside>
      </div>
    </div>
  );
}
