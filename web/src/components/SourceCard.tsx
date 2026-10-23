/**
 * 出处卡片
 *
 * 点角标弹出。要回答的就三件事：这句话出自哪份文档的哪一节、原文怎么写的、属于哪个学科。
 * 不跳转、不打开新页面——演示时弹窗最省事，也最容易讲。
 */

import { useEffect } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { FileText, X } from 'lucide-react';
import type { CitationEvent } from '../types/events';

export default function SourceCard({
  citation,
  onClose,
}: {
  citation: CitationEvent | null;
  onClose: () => void;
}) {
  useEffect(() => {
    if (!citation) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [citation, onClose]);

  return (
    <AnimatePresence>
      {citation && (
        <motion.div
          className="fixed inset-0 z-50 grid place-items-center bg-ink-900/25 p-6 backdrop-blur-[2px]"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.16 }}
          onClick={onClose}
        >
          <motion.div
            className="w-full max-w-lg rounded-xl border border-line bg-white p-5 shadow-lift"
            initial={{ opacity: 0, y: 8, scale: 0.985 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 6, scale: 0.99 }}
            transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-3 flex items-start justify-between gap-3">
              <div className="flex items-center gap-2">
                <span className="grid h-6 w-6 place-items-center rounded-md bg-paper-100 ring-1 ring-line">
                  <FileText size={12} className="text-ink-700" />
                </span>
                <div>
                  <div className="text-[13px] font-semibold text-ink-900">
                    {citation.source.doc_name}
                  </div>
                  <div className="text-[11px] text-ink-400">{citation.source.heading_path}</div>
                </div>
              </div>
              <button
                type="button"
                onClick={onClose}
                className="rounded p-1 text-ink-400 transition-colors hover:bg-paper-100 hover:text-ink-900"
              >
                <X size={14} />
              </button>
            </div>

            <blockquote className="border-l-2 border-ink-900/20 pl-3 font-serif text-[13.5px] leading-[1.8] text-ink-700">
              {citation.quote}
            </blockquote>

            <div className="mt-3 flex items-center gap-2 text-[10.5px] text-ink-400">
              <span className="chip bg-paper-100 text-ink-500 ring-1 ring-line">
                论点 {citation.claim_id}
              </span>
              {citation.chunk_ids.map((id) => (
                <span key={id} className="font-mono chip bg-paper-100 text-ink-500 ring-1 ring-line">
                  {id}
                </span>
              ))}
              <span className="ml-auto">doc #{citation.source.doc_id}</span>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
