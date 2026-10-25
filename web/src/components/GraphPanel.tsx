/**
 * 知识图谱面板
 *
 * 这块的**唯一目的**：让「跨域边」被看见。
 * 演示主线那道题，答案的价值不在于「RAG 怎么提召回」，而在于
 * 「B+ 树」这个词根本没出现在问题里，系统却把它连了过来。
 * 所以跨域边必须是虚线 + 琥珀色 + 粒子流动，其他边一律灰细线，不许抢。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import { Network } from 'lucide-react';
import type { GraphEdge, GraphNode } from '../types/events';
import type { GraphState } from '../store/chatStore';

const DOMAIN_COLOR: Record<string, string> = {
  backend: '#2563eb',
  ai: '#db2777',
  common: '#64748b',
};

const BRIDGE = '#d97706';

interface FGNode extends GraphNode {
  x?: number;
  y?: number;
  val: number;
}

interface FGLink {
  source: string | FGNode;
  target: string | FGNode;
  rel: string;
  weight: number;
  cross: boolean;
  onPath: boolean;
}

/** 容器尺寸，给 canvas 用（ForceGraph 不会自己撑满） */
function useSize<T extends HTMLElement>() {
  const [size, setSize] = useState({ w: 0, h: 0 });
  const roRef = useRef<ResizeObserver | null>(null);

  /**
   * 这里必须用 callback ref，不能写成 useEffect + ref 对象。
   *
   * 踩过的坑：空状态下组件会提前 return，`ref` 根本没挂到任何 DOM 上；
   * 而 `useEffect(..., [])` 在挂载时执行一次，拿到 `ref.current === null` 就 return 了，
   * 之后再也不会重跑 —— 数据到了、主分支渲染了，但永远没人来测量尺寸，
   * 结果是图谱区域一片空白，只有图例在。
   */
  const ref = useCallback((el: T | null) => {
    roRef.current?.disconnect();
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setSize({ w: Math.round(width), h: Math.round(height) });
    });
    ro.observe(el);
    roRef.current = ro;
  }, []);

  return [ref, size] as const;
}

export default function GraphPanel({ graph }: { graph: GraphState | undefined }) {
  const [boxRef, size] = useSize<HTMLDivElement>();
  const fgRef = useRef<any>(null);

  const data = useMemo(() => {
    if (!graph) return { nodes: [] as FGNode[], links: [] as FGLink[] };

    const pathSet = new Set(graph.activePath);
    // 路径上相邻两点组成的边，才算「在路径上」
    const pathEdges = new Set<string>();
    for (let i = 0; i < graph.activePath.length - 1; i++) {
      pathEdges.add(`${graph.activePath[i]}->${graph.activePath[i + 1]}`);
      pathEdges.add(`${graph.activePath[i + 1]}->${graph.activePath[i]}`);
    }

    const nodes: FGNode[] = Object.values(graph.nodes).map((n) => ({
      ...n,
      val: 2 + Math.min(6, Math.sqrt(Math.max(1, n.weight)) * 1.6),
    }));

    const links: FGLink[] = Object.values(graph.edges)
      .filter((e) => graph.nodes[e.source] && graph.nodes[e.target])
      .map((e: GraphEdge) => ({
        source: e.source,
        target: e.target,
        rel: e.rel,
        weight: e.weight,
        cross: e.cross_domain,
        onPath: pathSet.has(e.source) && pathSet.has(e.target) && pathEdges.has(`${e.source}->${e.target}`),
      }));

    return { nodes, links };
  }, [graph]);

  // 图变了就重新调一次力：默认斥力在 8 个节点时会挤成一团
  useEffect(() => {
    const fg = fgRef.current;
    if (!fg) return;
    fg.d3Force('charge')?.strength(-170);
    fg.d3Force('link')?.distance(62);
  }, [data.nodes.length]);

  /**
   * 视野适配。
   *
   * 这里踩过一个坑：只在 onEngineStop 里调一次 zoomToFit 是不够的。
   * 力导向布局在收敛过程中包围盒一直在变，早适配一次 = 缩放比例定死在错误的值上，
   * 结果要么缩成中间一小团，要么放大到节点跑出画布。
   *
   * 做法：在最初几秒里连续适配几次，最后一次一定落在布局稳定之后。
   */
  useEffect(() => {
    if (data.nodes.length < 2) return;
    const timers = [400, 1000, 1800, 2600].map((ms) =>
      setTimeout(() => fgRef.current?.zoomToFit(360, 56), ms),
    );
    return () => timers.forEach(clearTimeout);
  }, [data.nodes.length, data.links.length]);

  const nodeColor = useCallback(
    (n: FGNode) => DOMAIN_COLOR[n.domain] ?? DOMAIN_COLOR.common,
    [],
  );

  if (!graph || data.nodes.length === 0) {
    return (
      <div className="h-full grid place-items-center px-6">
        <div className="text-center">
          <Network size={18} className="mx-auto text-ink-400 mb-2" />
          <p className="text-[12.5px] text-ink-400 leading-5">
            回答后这里会长出知识图谱
            <br />
            <span className="text-bridge">虚线</span>代表跨域关联
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="relative h-full">
      <div ref={boxRef} className="absolute inset-0">
        {size.w > 0 && (
          <ForceGraph2D
            ref={fgRef}
            width={size.w}
            height={size.h}
            graphData={data}
            backgroundColor="rgba(0,0,0,0)"
            cooldownTicks={120}
            warmupTicks={0}
            nodeRelSize={1}
            nodeVal={(n: FGNode) => n.val}
            nodeColor={nodeColor as any}
            nodeLabel={(n: FGNode) => `${n.label} · ${n.subject}`}
            nodeCanvasObjectMode={() => 'replace'}
            nodeCanvasObject={(node: FGNode, ctx: CanvasRenderingContext2D, scale: number) => {
              const x = node.x ?? 0;
              const y = node.y ?? 0;

              // ⚠️ ctx 已经被 zoom 变换过，直接画 node.val 会随缩放一起变大变小。
              // 除以 scale 才是「恒定的屏幕像素半径」——否则缩放到 5 倍时节点会糊成一团。
              const r = (4.5 + node.val * 1.35) / scale;
              const onPath = graph.activePath.includes(node.id);

              ctx.beginPath();
              ctx.arc(x, y, r, 0, Math.PI * 2);
              ctx.fillStyle = nodeColor(node);
              ctx.globalAlpha = onPath ? 1 : 0.85;
              ctx.fill();
              ctx.globalAlpha = 1;

              // 路径上的节点加一圈白环，形成"亮点"
              if (onPath) {
                ctx.beginPath();
                ctx.arc(x, y, r, 0, Math.PI * 2);
                ctx.lineWidth = 1.4 / scale;
                ctx.strokeStyle = '#ffffff';
                ctx.stroke();
              }

              // 标签：缩得太小时只画路径节点，避免糊成一团。
              // 但节点总数很少（≤8）时不该藏——那个规模根本挤不着，
              // 藏起来反而让面板看起来像一堆没名字的彩色圆点。
              if (scale > 0.9 || onPath || node.weight >= 4 || data.nodes.length <= 8) {
                const fs = 10.5 / scale;
                ctx.font = `500 ${fs}px "PingFang SC", "Microsoft YaHei", sans-serif`;
                ctx.textAlign = 'center';
                ctx.textBaseline = 'top';
                const ly = y + r + 2 / scale;
                // 白描边：标签压在边上时也读得清
                ctx.lineWidth = 3 / scale;
                ctx.strokeStyle = 'rgba(251,250,248,.92)';
                ctx.lineJoin = 'round';
                ctx.strokeText(node.label, x, ly);
                ctx.fillStyle = 'rgba(23,22,20,.86)';
                ctx.fillText(node.label, x, ly);
              }
            }}
            linkColor={(l: FGLink) => (l.cross ? BRIDGE : l.onPath ? '#171614' : '#d8d2c7')}
            linkWidth={(l: FGLink) => (l.cross ? 1.6 : l.onPath ? 1.2 : 0.7)}
            linkLineDash={(l: FGLink) => (l.cross ? [4, 3] : null)}
            linkDirectionalParticles={(l: FGLink) => (l.onPath ? 3 : 0)}
            linkDirectionalParticleWidth={2}
            linkDirectionalParticleColor={() => BRIDGE}
            linkDirectionalParticleSpeed={0.006}
            linkLabel={(l: FGLink) => l.rel}
          />
        )}
      </div>

      {/* 图例：不解释的话，评委不知道虚线是什么意思 */}
      <div className="absolute left-2.5 bottom-2 flex items-center gap-2.5 text-[10px] text-ink-500 bg-white/85 backdrop-blur-sm rounded-md px-2 py-1 ring-1 ring-line">
        <span className="flex items-center gap-1">
          <span className="w-1.5 h-1.5 rounded-full" style={{ background: DOMAIN_COLOR.backend }} />
          后端
        </span>
        <span className="flex items-center gap-1">
          <span className="w-1.5 h-1.5 rounded-full" style={{ background: DOMAIN_COLOR.ai }} />
          AI
        </span>
        <span className="flex items-center gap-1">
          <svg width="14" height="6" viewBox="0 0 14 6">
            <line x1="0" y1="3" x2="14" y2="3" stroke={BRIDGE} strokeWidth="1.6" strokeDasharray="4 3" />
          </svg>
          跨域
        </span>
      </div>
    </div>
  );
}
