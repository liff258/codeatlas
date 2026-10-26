import type { GraphEdge, GraphNode } from '../types/events';
import type { GraphState } from '../store/chatStore';

/**
 * 全库图谱。
 *
 * 和单题图谱用同一个渲染组件（GraphPanel），数据结构也一样——
 * 两个界面长得一样、判定规则也一样，评委才不会觉得"这两个图是一回事吗"。
 *
 * 数据来自 GET /api/graph/overview，服务端按度数取前 N 个节点。
 */

interface ApiNode {
  id: string;
  label: string;
  type: string;
  subject: string;
  domain: string;
  weight: number;
}

interface ApiEdge {
  source: string;
  target: string;
  rel: string;
  weight: number;
  cross_domain: boolean;
}

interface ApiGraph {
  nodes: ApiNode[];
  edges: ApiEdge[];
  truncated: boolean;
}

export interface LibraryGraph {
  state: GraphState;
  stats: { nodes: number; edges: number; cross: number; truncated: boolean };
}

export async function fetchLibraryGraph(limit = 160, subject?: string): Promise<LibraryGraph> {
  const qs = new URLSearchParams({ limit: String(limit) });
  if (subject) qs.set('subject', subject);

  const res = await fetch(`/api/graph/overview?${qs.toString()}`, {
    headers: { Accept: 'application/json' },
  });
  if (!res.ok) {
    throw new Error(`图谱接口返回 ${res.status}`);
  }

  const body = (await res.json()) as { code: number; message: string; data: ApiGraph };
  if (body.code !== 0 || !body.data) {
    throw new Error(body.message || '图谱数据为空');
  }

  const nodes: Record<string, GraphNode> = {};
  for (const n of body.data.nodes) {
    nodes[n.id] = {
      id: n.id,
      label: n.label || n.id,
      // 契约里 type 是五个固定值，服务端已经收敛过，这里只做兜底
      type: (n.type as GraphNode['type']) ?? '概念',
      subject: n.subject ?? 'common',
      domain: (n.domain as GraphNode['domain']) ?? 'common',
      weight: n.weight ?? 1,
    };
  }

  const edges: Record<string, GraphEdge> = {};
  let cross = 0;
  for (const e of body.data.edges) {
    // 两端有一端不在节点集合里就丢掉——悬空边会让力导向图把节点甩到画布外
    if (!nodes[e.source] || !nodes[e.target]) continue;
    if (e.cross_domain) cross += 1;
    edges[`${e.source}->${e.target}`] = {
      source: e.source,
      target: e.target,
      rel: e.rel,
      weight: e.weight,
      cross_domain: e.cross_domain,
    };
  }

  return {
    state: { nodes, edges, activePath: [] },
    stats: {
      nodes: Object.keys(nodes).length,
      edges: Object.keys(edges).length,
      cross,
      truncated: body.data.truncated,
    },
  };
}
