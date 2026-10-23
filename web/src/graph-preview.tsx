/**
 * 图谱预览页（开发用）
 *
 * 打开 http://localhost:5173/graph-preview.html 可以单独看图谱的渲染效果，
 * 不用每次跑完整条问答流。调样式时省时间。
 *
 * 数据取自 mock 流里那一帧 graph 事件，保证和真实链路一致。
 */

import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import GraphPanel from './components/GraphPanel';
import type { GraphState } from './store/chatStore';
import raw from './mock/stream.jsonl?raw';
import './index.css';

function loadGraph(): GraphState {
  const lines = String(raw)
    .split('\n')
    .filter((l) => l.trim());

  for (const line of lines) {
    const rec = JSON.parse(line) as { event: string; data: any };
    if (rec.event !== 'graph') continue;
    const nodes: GraphState['nodes'] = {};
    const edges: GraphState['edges'] = {};
    for (const n of rec.data.nodes) nodes[n.id] = n;
    for (const e of rec.data.edges) edges[`${e.source}->${e.target}`] = e;
    return { nodes, edges, activePath: rec.data.active_path ?? [] };
  }
  return { nodes: {}, edges: {}, activePath: [] };
}

const graph = loadGraph();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <div className="flex h-full flex-col bg-paper-50">
      <div className="flex h-8 items-center justify-between border-b border-line px-4">
        <span className="text-[11px] font-medium text-ink-500">知识图谱 · 预览</span>
        <span className="text-[10px] text-ink-400">
          {Object.keys(graph.nodes).length} 节点 /{' '}
          {Object.values(graph.edges).filter((e) => e.cross_domain).length} 跨域边
        </span>
      </div>
      <div className="min-h-0 flex-1">
        <GraphPanel graph={graph} />
      </div>
    </div>
  </StrictMode>,
);
