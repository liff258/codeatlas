import { HelpCircle, FileText } from 'lucide-react';
import type { KnowledgePointBrief } from '../lib/learning';
import { navigate } from '../lib/router';

/**
 * 知识点卡片（列表页用）。
 *
 * 面试题和普通知识点用不同的图标和底色区分：
 * 用户逛板块时应该一眼看出「这条是题」还是「这条是正文」，
 * 否则点进去才发现是道题，预期落空。
 */
export default function KnowledgePointCard({ kp }: { kp: KnowledgePointBrief }) {
  const go = () => navigate(`/kp/${encodeURIComponent(kp.id)}`);

  return (
    <button
      type="button"
      onClick={go}
      className="group w-full rounded-lg border border-line bg-white p-3.5 text-left transition-all hover:border-ink-400/40 hover:shadow-card"
    >
      <div className="flex items-start gap-2">
        <span
          className={[
            'mt-[2px] shrink-0 rounded p-1',
            kp.is_question ? 'bg-bridge/10 text-bridge' : 'bg-paper-100 text-ink-500',
          ].join(' ')}
        >
          {kp.is_question ? <HelpCircle size={11} /> : <FileText size={11} />}
        </span>

        <div className="min-w-0 flex-1">
          <div className="text-[13.5px] font-medium leading-6 text-ink-900 group-hover:text-ink-900">
            {kp.title}
          </div>

          {kp.breadcrumb && (
            <div className="mt-0.5 truncate text-[10.5px] text-ink-400">{kp.breadcrumb}</div>
          )}

          {kp.preview && (
            <p className="mt-1.5 line-clamp-2 text-[12px] leading-[1.7] text-ink-500">
              {kp.preview}
            </p>
          )}

          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10.5px] text-ink-400">
            <span>{kp.char_count} 字</span>
            <span>{kp.chunk_count} 段</span>
            {kp.subject && <span className="chip bg-paper-100 text-ink-500">{kp.subject}</span>}
            {kp.doc_name && <span className="truncate">来源：{kp.doc_name}</span>}
          </div>
        </div>
      </div>
    </button>
  );
}
