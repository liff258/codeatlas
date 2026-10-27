/**
 * 实体页：一个概念的关系网。
 *
 * 这是「图谱能点进去」的落点——从知识点页点概念进来，
 * 看完关系网可以再点邻居概念继续跳，形成概念之间的漫游。
 *
 * description 目前全部是原文摘录，所以必须标「摘自原文」。
 * 不标的话用户会以为这是权威定义，被追问出处就答不上来。
 */

import { ChevronLeft, Loader2, Quote } from 'lucide-react';
import GraphPanel from '../components/GraphPanel';
import { useAsync } from '../lib/useAsync';
import { getEntity, getNeighbors, type EntityDetail } from '../lib/learning';
import { navigate } from '../lib/router';
import type { GraphState } from '../store/chatStore';

export default function EntityPage({ name }: { name: string }) {
  const entity = useAsync<EntityDetail>((signal) => getEntity(name, signal), [name]);
  // 邻居图单独拉：/api/graph/neighbors 返回的是完整 GraphData，
  // 比用实体详情里的 relations 自己拼节点更可靠（那边的边没有节点元信息）
  const graph = useAsync<GraphState>((signal) => getNeighbors(name, 1, signal), [name]);

  if (entity.loading) {
    return (
      <div className="flex flex-1 items-center justify-center gap-2 text-[12.5px] text-ink-400">
        <Loader2 size={13} className="animate-spin" />
        加载中…
      </div>
    );
  }

  if (entity.error || !entity.data) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3">
        <p className="text-[13px] text-ink-500">{entity.error ?? '没有这个实体'}</p>
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

  const d = entity.data;
  const domainCls =
    d.domain === 'ai'
      ? 'bg-ai/10 text-ai'
      : d.domain === 'backend'
        ? 'bg-backend/10 text-backend'
        : 'bg-paper-100 text-ink-500';

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto flex w-full max-w-[1180px] gap-8 px-6 py-8">
        <div className="min-w-0 flex-1">
          <button
            type="button"
            onClick={() => history.back()}
            className="mb-4 flex items-center gap-1 text-[11.5px] text-ink-400 transition-colors hover:text-ink-900"
          >
            <ChevronLeft size={11} />
            返回
          </button>

          <div className="flex flex-wrap items-center gap-2">
            <h1 className="font-serif text-[26px] font-semibold tracking-tight text-ink-900">
              {d.name}
            </h1>
            <span className="chip bg-paper-100 text-ink-500">{d.entity_type}</span>
            {d.subject && <span className={`chip ${domainCls}`}>{d.subject}</span>}
          </div>

          <div className="mt-1.5 text-[11px] text-ink-400">
            出现在 {d.doc_freq} 篇文档里 · {d.relations.length} 条关系
          </div>

          {/* 描述 */}
          <div className="mt-5 rounded-lg border border-line bg-white p-4">
            <div className="mb-2 flex items-center gap-1.5 text-[10.5px] text-ink-400">
              <Quote size={10} />
              {d.description_source === 'curated' ? '知识库整理' : '摘自原文'}
            </div>
            <p className="text-[13.5px] leading-[1.85] text-ink-700">
              {d.description || '这个词在原文里没有可摘录的定义句。'}
            </p>
            {d.description_source === 'extracted' && (
              <p className="mt-2 text-[10.5px] leading-relaxed text-ink-400">
                这是从原文摘的句子，不是人工编写的定义。完整上下文见下方「原文提及」。
              </p>
            )}
          </div>

          {/* 关系网 */}
          <section className="mt-6">
            <div className="mb-2 flex items-center justify-between">
              <h2 className="font-serif text-[14px] font-semibold text-ink-900">关系网</h2>
              <span className="text-[10.5px] text-ink-400">点节点可以继续跳</span>
            </div>
            <div className="h-[380px] rounded-lg border border-line bg-white/60">
              {graph.loading && (
                <div className="grid h-full place-items-center text-[11.5px] text-ink-400">
                  加载关系网…
                </div>
              )}
              {graph.error && (
                <div className="grid h-full place-items-center text-[11.5px] text-ink-400">
                  {graph.error}
                </div>
              )}
              {graph.data && (
                <GraphPanel
                  graph={graph.data}
                  highlightIds={[d.name]}
                  onNodeClick={(n) => navigate(`/e/${encodeURIComponent(n.label || n.id)}`)}
                />
              )}
            </div>
          </section>

          {/* 原文提及 */}
          {d.mentions.length > 0 && (
            <section className="mt-6">
              <h2 className="mb-2 font-serif text-[14px] font-semibold text-ink-900">原文提及</h2>
              <div className="space-y-2">
                {d.mentions.map((m, i) => (
                  <div key={`${m.chunk_id}-${i}`} className="rounded-lg border border-line bg-white p-3">
                    {m.kp_id && (
                      <button
                        type="button"
                        onClick={() => navigate(`/kp/${encodeURIComponent(m.kp_id!)}`)}
                        className="mb-1 block text-left text-[12px] font-medium text-ink-900 transition-colors hover:text-bridge"
                      >
                        {m.kp_title}
                      </button>
                    )}
                    <p className="line-clamp-3 text-[12px] leading-[1.75] text-ink-500">
                      {m.snippet}
                    </p>
                  </div>
                ))}
              </div>
            </section>
          )}
        </div>

        <aside className="hidden w-[250px] shrink-0 lg:block">
          <div className="rounded-lg border border-line bg-white p-3">
            <div className="text-[11px] font-medium text-ink-500">怎么用这个页面</div>
            <ul className="mt-2 space-y-1.5 text-[11px] leading-relaxed text-ink-400">
              <li>· 点关系网里的节点，跳到相邻概念</li>
              <li>· 点「原文提及」里的标题，看完整知识点</li>
              <li>· 虚线代表两端属于不同学科域</li>
            </ul>
          </div>
        </aside>
      </div>
    </div>
  );
}
