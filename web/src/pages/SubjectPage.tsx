/**
 * 学科页：某个板块下的知识点列表。
 *
 * 两种视图共用一套分页：全部 / 面试题。
 * 切 tab 时把 page 重置为 1——否则从第 5 页切到面试题会得到空列表，
 * 用户会以为"这个学科没有题"。
 */

import { useMemo } from 'react';
import { ChevronLeft, Loader2 } from 'lucide-react';
import KnowledgePointCard from '../components/KnowledgePointCard';
import Pager from '../components/Pager';
import { useAsync } from '../lib/useAsync';
import { getSubjects, listKnowledgePoints, type KnowledgePointBrief, type PageResult, type Subject } from '../lib/learning';
import { buildQuery, navigate, useRoute } from '../lib/router';

const PAGE_SIZE = 20;

export default function SubjectPage({ subject }: { subject: string }) {
  const { query } = useRoute();
  const type = query.get('type') === 'question' ? 'question' : 'all';
  const page = Math.max(1, Number(query.get('page') ?? 1) || 1);

  const subjects = useAsync<Subject[]>((signal) => getSubjects(signal), []);
  const meta = useMemo(
    () => subjects.data?.find((s) => s.code === subject) ?? null,
    [subjects.data, subject],
  );

  const list = useAsync<PageResult<KnowledgePointBrief>>(
    (signal) =>
      listKnowledgePoints({ subject, type, page, size: PAGE_SIZE }, signal),
    [subject, type, page],
  );

  const go = (nextType: 'all' | 'question', nextPage = 1) => {
    navigate(`/s/${encodeURIComponent(subject)}${buildQuery({ type: nextType === 'all' ? undefined : nextType, page: nextPage > 1 ? nextPage : undefined })}`);
  };

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto w-full max-w-[900px] px-6 py-8">
        <button
          type="button"
          onClick={() => navigate('/')}
          className="mb-4 flex items-center gap-1 text-[11.5px] text-ink-400 transition-colors hover:text-ink-900"
        >
          <ChevronLeft size={11} />
          全部板块
        </button>

        <div className="flex items-end justify-between gap-4">
          <div>
            <h1 className="font-serif text-[24px] font-semibold tracking-tight text-ink-900">
              {meta?.display_name ?? subject}
            </h1>
            <p className="mt-1.5 text-[11.5px] text-ink-400">
              {meta
                ? `${meta.kp_count} 个知识点 · ${meta.question_count} 道面试题 · ${meta.chunk_count} 个切片`
                : '加载中…'}
            </p>
          </div>
        </div>

        <div className="mt-5 flex items-center gap-1.5">
          {([
            { key: 'all', label: '全部知识点', count: meta?.kp_count },
            { key: 'question', label: '面试题', count: meta?.question_count },
          ] as const).map((t) => {
            const active = type === t.key;
            return (
              <button
                key={t.key}
                type="button"
                onClick={() => go(t.key)}
                className={[
                  'rounded-md px-2.5 py-1.5 text-[12px] transition-colors',
                  active
                    ? 'bg-ink-900 text-paper-50'
                    : 'border border-line bg-white text-ink-500 hover:text-ink-900',
                ].join(' ')}
              >
                {t.label}
                {typeof t.count === 'number' && (
                  <span className={active ? 'ml-1 text-paper-50/70' : 'ml-1 text-ink-400'}>
                    {t.count}
                  </span>
                )}
              </button>
            );
          })}
        </div>

        <div className="mt-4 space-y-2">
          {list.loading && (
            <div className="flex items-center gap-2 py-6 text-[12.5px] text-ink-400">
              <Loader2 size={13} className="animate-spin" />
              加载中…
            </div>
          )}

          {list.error && (
            <div className="rounded-lg border border-red-200 bg-red-50/60 px-4 py-3 text-[12.5px] text-red-700">
              {list.error}
            </div>
          )}

          {list.data?.items.length === 0 && !list.loading && (
            <div className="rounded-lg border border-dashed border-line px-4 py-8 text-center text-[12.5px] text-ink-400">
              这个学科还没有{type === 'question' ? '面试题' : '知识点'}。
              <br />
              素材补齐后会出现在这里——不会用别的学科的内容凑数。
            </div>
          )}

          {list.data?.items.map((kp) => (
            <KnowledgePointCard key={kp.id} kp={kp} />
          ))}
        </div>

        {list.data && list.data.total > PAGE_SIZE && (
          <div className="mt-4">
            <Pager
              page={list.data.page}
              size={list.data.size}
              total={list.data.total}
              hasMore={list.data.has_more}
              onChange={(p) => go(type, p)}
            />
          </div>
        )}
      </div>
    </div>
  );
}
