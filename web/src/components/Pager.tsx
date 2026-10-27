import { ChevronLeft, ChevronRight } from 'lucide-react';

/**
 * 分页器。
 *
 * 只做「上一页 / 下一页 + 第几页」，不做页码跳转：
 * 知识点列表是按字数排序的，用户不会想跳到第 37 页，
 * 加一排页码反而占地方。
 */
export default function Pager({
  page,
  size,
  total,
  hasMore,
  onChange,
}: {
  page: number;
  size: number;
  total: number;
  hasMore: boolean;
  onChange: (page: number) => void;
}) {
  const totalPages = Math.max(1, Math.ceil(total / size));

  return (
    <div className="flex items-center justify-between border-t border-line pt-3 text-[11.5px] text-ink-400">
      <span>
        共 {total} 条 · 第 {page} / {totalPages} 页
      </span>
      <div className="flex items-center gap-1.5">
        <button
          type="button"
          disabled={page <= 1}
          onClick={() => onChange(page - 1)}
          className="flex items-center gap-0.5 rounded-md border border-line bg-white px-2 py-1 text-ink-500 transition-colors hover:text-ink-900 disabled:opacity-40 disabled:hover:text-ink-500"
        >
          <ChevronLeft size={11} />
          上一页
        </button>
        <button
          type="button"
          disabled={!hasMore}
          onClick={() => onChange(page + 1)}
          className="flex items-center gap-0.5 rounded-md border border-line bg-white px-2 py-1 text-ink-500 transition-colors hover:text-ink-900 disabled:opacity-40 disabled:hover:text-ink-500"
        >
          下一页
          <ChevronRight size={11} />
        </button>
      </div>
    </div>
  );
}
