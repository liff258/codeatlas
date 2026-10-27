/**
 * 面试题库：全库题目，可按学科筛。
 *
 * 和学科页的区别是「横向」——这里是所有学科的题放在一起，
 * 适合"考前刷一遍"的场景。筛选走 URL 参数，链接可分享。
 */

import { useMemo } from 'react';
import { Loader2 } from 'lucide-react';
import KnowledgePointCard from '../components/KnowledgePointCard';
import Pager from '../components/Pager';
import { useAsync } from '../lib/useAsync';
import {
  getSubjects,
  listKnowledgePoints,
  type KnowledgePointBrief,
  type PageResult,
  type Subject,
} from '../lib/learning';
import { buildQuery, navigate, useRoute } from '../lib/router';

const PAGE_SIZE = 20;

export default function QuestionsPage() {
  const { query } = useRoute();
  const subject = query.get('subject') ?? undefined;
  const page = Math.max(1, Number(query.get('page') ?? 1) || 1);

  const subjects = useAsync<Subject[]>((signal) => getSubjects(signal), []);
  const list = useAsync<PageResult<KnowledgePointBrief>>(
    (signal) => listKnowledgePoints({ subject, type: 'question', page, size: PAGE_SIZE }, signal),
    [subject, page],
  );

  // 只显示有题的学科——筛选器里出现"0 道题"的选项只会让人困惑
  const withQuestions = useMemo(
    () => (subjects.data ?? []).filter((s) => s.question_count > 0),
    [subjects.data],
  );

  const go = (nextSubject?: string, nextPage = 1) => {
    navigate(
      `/questions${buildQuery({
        subject: nextSubject,
        page: nextPage > 1 ? nextPage : undefined,
      })}`,
    );
  };

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto w-full max-w-[900px] px-6 py-8">
        <h1 className="font-serif text-[24px] font-semibold tracking-tight text-ink-900">
          面试题库
        </h1>
        <p className="mt-1.5 text-[11.5px] leading-relaxed text-ink-400">
          标题是问题、正文是答案，全部从知识库原文自动抽取。
          点开能看到完整回答和出处——<span className="text-ink-500">不是背题，是能追到原文的题</span>。
        </p>

        <div className="mt-5 flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            onClick={() => go(undefined)}
            className={[
              'rounded-md px-2.5 py-1.5 text-[12px] transition-colors',
              !subject
                ? 'bg-ink-900 text-paper-50'
                : 'border border-line bg-white text-ink-500 hover:text-ink-900',
            ].join(' ')}
          >
            全部
          </button>
          {withQuestions.map((s) => {
            const active = subject === s.code;
            return (
              <button
                key={s.code}
                type="button"
                onClick={() => go(s.code)}
                className={[
                  'rounded-md px-2.5 py-1.5 text-[12px] transition-colors',
                  active
                    ? 'bg-ink-900 text-paper-50'
                    : 'border border-line bg-white text-ink-500 hover:text-ink-900',
                ].join(' ')}
              >
                {s.display_name}
                <span className={active ? 'ml-1 text-paper-50/70' : 'ml-1 text-ink-400'}>
                  {s.question_count}
                </span>
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
          {list.data?.items.map((kp) => (
            <KnowledgePointCard key={kp.id} kp={kp} />
          ))}
          {list.data?.items.length === 0 && !list.loading && (
            <div className="rounded-lg border border-dashed border-line px-4 py-8 text-center text-[12.5px] text-ink-400">
              这个学科还没有面试题。
            </div>
          )}
        </div>

        {list.data && list.data.total > PAGE_SIZE && (
          <div className="mt-4">
            <Pager
              page={list.data.page}
              size={list.data.size}
              total={list.data.total}
              hasMore={list.data.has_more}
              onChange={(p) => go(subject, p)}
            />
          </div>
        )}
      </div>
    </div>
  );
}
