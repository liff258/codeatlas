/**
 * 全局外壳：顶栏 + 内容区 + 全库图谱浮层。
 *
 * 和改造前的区别：顶栏从「对话页的工具栏」变成了「全局导航」。
 * 这是这次产品调整的核心——agent 不再是入口，知识和题库才是。
 *
 * 全库图谱放在外壳而不是某个页面：它是「整个知识库长什么样」的视角，
 * 任何页面都可能想看一眼。
 */

import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { BookOpen, HelpCircle, MessageSquare, Minimize2, Network } from 'lucide-react';
import GraphPanel from './GraphPanel';
import AssistantDock from './AssistantDock';
import { navigate, useRoute } from '../lib/router';
import { fetchLibraryGraph } from '../lib/libraryGraph';
import type { GraphState } from '../store/chatStore';

interface NavItem {
  key: string;
  label: string;
  icon: typeof BookOpen;
  to: string;
  /** 哪些路由算「在这个栏目里」，用于高亮 */
  match: (name: string) => boolean;
}

const NAV: NavItem[] = [
  { key: 'home', label: '板块', icon: BookOpen, to: '/', match: (n) => n === 'home' || n === 'subject' || n === 'kp' || n === 'entity' },
  { key: 'questions', label: '面试题库', icon: HelpCircle, to: '/questions', match: (n) => n === 'questions' },
  { key: 'chat', label: '对话', icon: MessageSquare, to: '/chat', match: (n) => n === 'chat' },
];

export default function AppShell({ children }: { children: ReactNode }) {
  const { route } = useRoute();
  const [libOpen, setLibOpen] = useState(false);
  const [libGraph, setLibGraph] = useState<GraphState | null>(null);
  const [libStats, setLibStats] = useState<{
    nodes: number;
    edges: number;
    cross: number;
    truncated: boolean;
  } | null>(null);
  const [libLoading, setLibLoading] = useState(false);
  const [libError, setLibError] = useState<string | null>(null);

  const openLibrary = useCallback(async () => {
    setLibOpen(true);
    if (libGraph || libLoading) return;
    setLibLoading(true);
    setLibError(null);
    try {
      // 200 个节点：再多在 1920 宽下会糊成一团，再少 AI 域的概念就进不来
      // （语料里后端占 95%，按度数排序时 AI 概念天然靠后）
      const g = await fetchLibraryGraph(200);
      setLibGraph(g.state);
      setLibStats(g.stats);
    } catch (e) {
      setLibError((e as Error)?.message ?? '加载失败');
    } finally {
      setLibLoading(false);
    }
  }, [libGraph, libLoading]);

  useEffect(() => {
    if (!libOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setLibOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [libOpen]);

  return (
    <div className="flex h-full flex-col bg-paper-50">
      <header className="z-10 shrink-0 border-b border-line bg-paper-50/85 backdrop-blur-md">
        <div className="mx-auto flex h-14 w-full max-w-[1560px] items-center gap-6 px-5">
          <button
            type="button"
            onClick={() => navigate('/')}
            className="shrink-0 text-left"
          >
            <div className="font-serif text-[15px] font-semibold leading-none tracking-tight text-ink-900">
              CodeAtlas
            </div>
            <div className="mt-1 text-[10px] leading-none tracking-wide text-ink-400">
              后端与 AI 知识图谱
            </div>
          </button>

          <nav className="flex items-center gap-1">
            {NAV.map((item) => {
              const active = item.match(route.name);
              return (
                <button
                  key={item.key}
                  type="button"
                  onClick={() => navigate(item.to)}
                  className={[
                    'flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[12.5px] transition-colors',
                    active
                      ? 'bg-ink-900 text-paper-50'
                      : 'text-ink-500 hover:bg-paper-100 hover:text-ink-900',
                  ].join(' ')}
                >
                  <item.icon size={12} />
                  {item.label}
                </button>
              );
            })}
          </nav>

          <div className="ml-auto flex shrink-0 items-center gap-2">
            <button
              type="button"
              onClick={() => void openLibrary()}
              title="看整个知识库的概念关联"
              className="flex items-center gap-1 rounded-md border border-line bg-white/70 px-2 py-1 text-[11px] text-ink-500 transition-colors hover:border-ink-400/40 hover:text-ink-900"
            >
              <Network size={11} />
              全库图谱
            </button>
          </div>
        </div>
      </header>

      <main className="flex min-h-0 flex-1">{children}</main>

      {/* 助手在对话页不显示——那里本来就是全屏对话，再挂一个浮层是重复 */}
      {route.name !== 'chat' && <AssistantDock />}

      {libOpen && (
        <div className="fixed inset-0 z-40 flex flex-col bg-paper-50">
          <div className="flex h-11 shrink-0 items-center justify-between border-b border-line px-5">
            <div className="flex items-center gap-2">
              <span className="text-[13px] font-semibold text-ink-900">全库知识图谱</span>
              {libStats && (
                <span className="text-[11px] text-ink-400">
                  {libStats.nodes} 个概念 · {libStats.edges} 条关系 ·{' '}
                  <span className="text-bridge">{libStats.cross} 条跨域</span>
                  {libStats.truncated && ' · 仅展示核心节点'}
                </span>
              )}
            </div>
            <button
              type="button"
              onClick={() => setLibOpen(false)}
              className="flex items-center gap-1 rounded-md border border-line bg-white px-2 py-1 text-[11px] text-ink-500 transition-colors hover:text-ink-900"
            >
              <Minimize2 size={11} />
              退出全屏
            </button>
          </div>
          <div className="relative min-h-0 flex-1">
            {libLoading && (
              <div className="absolute inset-0 grid place-items-center text-[12.5px] text-ink-400">
                正在加载全库图谱…
              </div>
            )}
            {libError && (
              <div className="absolute inset-0 grid place-items-center text-[12.5px] text-red-600">
                {libError}
              </div>
            )}
            <GraphPanel
              graph={libGraph ?? undefined}
              onNodeClick={(n) => {
                setLibOpen(false);
                navigate(`/e/${encodeURIComponent(n.label || n.id)}`);
              }}
            />
          </div>
        </div>
      )}
    </div>
  );
}
