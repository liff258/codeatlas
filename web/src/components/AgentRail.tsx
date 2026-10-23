/**
 * Agent 节点轨道
 *
 * 整个界面的视觉锚点：8 个节点横排，随流式事件依次点亮。
 * 评委扫一眼就知道这个系统是「有结构的流程」，不是一个套壳对话框。
 */

import { motion } from 'framer-motion';
import { Check, Minus, TriangleAlert, X } from 'lucide-react';
import type { AgentNode, StepStatus } from '../types/events';
import type { ChatMessage } from '../store/chatStore';
import { selectActiveNode, selectDoneNodes } from '../store/chatStore';

const RAIL: { node: AgentNode; label: string; short: string }[] = [
  { node: 'router', label: '意图路由', short: '路由' },
  { node: 'planner', label: '查询规划', short: '规划' },
  { node: 'retriever', label: '混合检索', short: '检索' },
  { node: 'grader', label: '证据自评', short: '自评' },
  { node: 'rewriter', label: '查询改写', short: '改写' },
  { node: 'tool', label: '工具调用', short: '工具' },
  { node: 'citation', label: '引用绑定', short: '引用' },
  { node: 'generator', label: '生成答案', short: '生成' },
];

/** 某节点的最终状态（failed / degraded 要单独显示，别被 ok 盖掉） */
function statusOf(msg: ChatMessage | null, node: AgentNode): StepStatus | 'idle' {
  if (!msg) return 'idle';
  let st: StepStatus | 'idle' = 'idle';
  for (const t of msg.thoughts) {
    if (t.kind !== 'step' || t.node !== node) continue;
    if (t.status === 'failed') return 'failed';
    if (t.status === 'degraded') st = 'degraded';
    else if (t.status === 'ok' && st === 'idle') st = 'ok';
    else if (t.status === 'running') st = 'running';
  }
  return st;
}

const DOT: Record<string, string> = {
  idle: 'bg-paper-200 text-ink-400 ring-line',
  running: 'bg-white text-ink-900 ring-ink-900',
  ok: 'bg-ink-900 text-paper-50 ring-ink-900',
  degraded: 'bg-bridge text-white ring-bridge',
  failed: 'bg-red-600 text-white ring-red-600',
};

function NodeIcon({ st }: { st: string }) {
  if (st === 'ok') return <Check size={11} strokeWidth={3} />;
  if (st === 'degraded') return <TriangleAlert size={11} strokeWidth={2.6} />;
  if (st === 'failed') return <X size={11} strokeWidth={3} />;
  if (st === 'running') return <span className="w-1.5 h-1.5 rounded-full bg-ink-900" />;
  return <Minus size={10} strokeWidth={2.4} className="opacity-50" />;
}

export default function AgentRail({ message }: { message: ChatMessage | null }) {
  const active = selectActiveNode(message);
  const done = selectDoneNodes(message);

  return (
    <div className="flex items-center gap-0">
      {RAIL.map((item, i) => {
        const st = statusOf(message, item.node);
        const isActive = active === item.node;
        const prevDone = i === 0 || done.has(RAIL[i - 1].node);

        return (
          <div key={item.node} className="flex items-center">
            {/* 连接线：前一个节点跑完了才点亮 */}
            {i > 0 && (
              <div className="relative w-6 h-px bg-line overflow-hidden">
                <motion.div
                  className="absolute inset-y-0 left-0 bg-ink-900"
                  initial={false}
                  animate={{ width: prevDone ? '100%' : '0%' }}
                  transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
                />
              </div>
            )}

            <div className="flex flex-col items-center gap-1.5 group" title={item.label}>
              <div className="relative">
                {/* 运行中的脉冲环 */}
                {isActive && (
                  <span className="absolute inset-0 rounded-full ring-2 ring-ink-900/30 animate-pulse-ring" />
                )}
                <motion.div
                  layout
                  initial={false}
                  animate={{ scale: isActive ? 1.12 : 1 }}
                  transition={{ type: 'spring', stiffness: 420, damping: 26 }}
                  className={[
                    'w-6 h-6 rounded-full grid place-items-center ring-1 transition-colors duration-300',
                    DOT[st],
                    st === 'idle' ? 'opacity-70' : '',
                  ].join(' ')}
                >
                  <NodeIcon st={st} />
                </motion.div>
              </div>
              <span
                className={[
                  'text-[10.5px] leading-none tracking-tight transition-colors duration-300 whitespace-nowrap',
                  st === 'idle' ? 'text-ink-400/70' : 'text-ink-700 font-medium',
                ].join(' ')}
              >
                {item.short}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
