/**
 * 首页：知识板块。
 *
 * 这是产品形态调整的核心页面——用户进来看到的是「有哪些东西可学」，
 * 而不是一个等着被提问的输入框。
 *
 * 按 domain 分两组（后端 / AI），因为这两块的学习路径不同，
 * 而且「跨域」这个卖点需要一个视觉上的对照：两个域各自成组，
 * 中间的连接才是它区别于普通知识库的地方。
 */

import { ArrowRight, Loader2 } from 'lucide-react';
import { useAsync } from '../lib/useAsync';
import { getSubjects, type Subject } from '../lib/learning';
import { navigate } from '../lib/router';

const DOMAIN_META: Record<string, { title: string; desc: string; accent: string }> = {
  backend: {
    title: '后端',
    desc: 'Java 基础、并发、JVM、MySQL、Redis、Spring、分布式、网络、消息队列',
    accent: 'text-backend',
  },
  ai: {
    title: 'AI',
    desc: 'RAG、向量检索、LLM 基础、Agent、Prompt 工程',
    accent: 'text-ai',
  },
  common: {
    title: '通用',
    desc: '跨领域的工程实践',
    accent: 'text-ink-500',
  },
};

function SubjectCard({ s }: { s: Subject }) {
  const empty = s.kp_count === 0;

  return (
    <button
      type="button"
      disabled={empty}
      onClick={() => navigate(`/s/${encodeURIComponent(s.code)}`)}
      className={[
        'group relative flex flex-col rounded-lg border p-3.5 text-left transition-all',
        empty
          ? 'cursor-default border-dashed border-line bg-paper-50/60'
          : 'border-line bg-white hover:-translate-y-[1px] hover:border-ink-400/40 hover:shadow-card',
      ].join(' ')}
    >
      <div className="flex items-start justify-between gap-2">
        <span
          className="text-[13.5px] font-semibold text-ink-900"
          style={{ color: empty ? undefined : s.color }}
        >
          {s.display_name}
        </span>
        {empty ? (
          <span className="chip bg-paper-100 text-ink-400">建设中</span>
        ) : (
          <ArrowRight
            size={12}
            className="mt-1 shrink-0 text-ink-300 transition-transform group-hover:translate-x-0.5 group-hover:text-ink-500"
          />
        )}
      </div>

      <div className="mt-2 flex items-baseline gap-1.5">
        <span className="font-serif text-[20px] font-semibold leading-none text-ink-900">
          {s.kp_count}
        </span>
        <span className="text-[10.5px] text-ink-400">个知识点</span>
      </div>

      <div className="mt-1.5 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[10.5px] text-ink-400">
        {s.question_count > 0 ? (
          <span className="text-bridge">{s.question_count} 道面试题</span>
        ) : (
          <span>暂无面试题</span>
        )}
        <span>{s.chunk_count} 个切片</span>
      </div>
    </button>
  );
}

export default function HomePage() {
  const { data, loading, error } = useAsync<Subject[]>((signal) => getSubjects(signal), []);

  const groups = ['backend', 'ai', 'common'] as const;

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto w-full max-w-[1100px] px-6 py-10">
        <div className="animate-fade-up">
          <div className="mb-2 inline-flex items-center gap-1.5 rounded-full border border-line bg-white/60 px-2.5 py-1 text-[11px] text-ink-500">
            计算机知识库 · 后端与 AI
          </div>
          <h1 className="font-serif text-[30px] leading-[1.35] tracking-tight text-ink-900">
            从一个板块开始，
            <br />
            顺着概念往下走
          </h1>
          <p className="mt-3 max-w-xl text-[13px] leading-[1.9] text-ink-500">
            14 个学科、两千多个知识点、七百多道面试题。每个知识点都能点开看原文，
            也能顺着概念跳到相邻的知识——不确定该问什么的时候，从左边挑一个开始就行。
          </p>
        </div>

        {loading && (
          <div className="mt-12 flex items-center gap-2 text-[12.5px] text-ink-400">
            <Loader2 size={13} className="animate-spin" />
            正在加载板块…
          </div>
        )}

        {error && (
          <div className="mt-10 rounded-lg border border-red-200 bg-red-50/60 px-4 py-3 text-[12.5px] text-red-700">
            加载失败：{error}
          </div>
        )}

        {data && (
          <div className="mt-9 space-y-8">
            {groups.map((g) => {
              const items = data.filter((s) => s.domain === g);
              if (items.length === 0) return null;
              const meta = DOMAIN_META[g];
              return (
                <section key={g}>
                  <div className="mb-3 flex items-baseline gap-2">
                    <h2 className={`font-serif text-[15px] font-semibold ${meta.accent}`}>
                      {meta.title}
                    </h2>
                    <span className="text-[11px] text-ink-400">{items.length} 个学科</span>
                  </div>
                  <p className="mb-3 text-[11.5px] leading-relaxed text-ink-400">{meta.desc}</p>
                  <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-4">
                    {items.map((s) => (
                      <SubjectCard key={s.code} s={s} />
                    ))}
                  </div>
                </section>
              );
            })}
          </div>
        )}

        <div className="mt-12 border-t border-line pt-5 text-[11px] text-ink-400">
          不知道从哪开始？点右上角「对话」，直接问一个问题，答案里每个结论都能点开看原文。
        </div>
      </div>
    </div>
  );
}
