/**
 * SSE 协议解析（纯函数，零运行时依赖）
 *
 * 单独拆出来是为了能直接跑单测：解析器一旦有 bug，表现是
 * 「HTTP 200 但一个事件都收不到」，静默失败，肉眼根本看不出来。
 * 这种代码必须可测。
 *
 * 契约：contracts/sse-events.md §2、§4
 */

import type { AgentEvent, AgentEventType, EventPayloadMap } from '../types/events';
import { KNOWN_EVENTS } from '../types/events';

export interface RawMessage {
  event: string;
  data: string;
  id?: string;
}

/**
 * 从缓冲区里切出完整行，返回剩余不完整的尾巴。
 *
 * 两个容易写错的地方：
 *   1. `\r\n` 会被 chunk 边界劈成两半 —— 末尾孤立的 `\r` 必须留在 buffer 里等下一个 chunk
 *   2. 不能用 `split(/\r?\n/)` 了事，SSE 规范里单独的 `\r` 也是合法换行
 */
export function drainLines(buf: string): { lines: string[]; rest: string } {
  let rest = buf;
  let hold = '';
  if (rest.endsWith('\r')) {
    hold = '\r';
    rest = rest.slice(0, -1);
  }
  const normalized = rest.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
  const parts = normalized.split('\n');
  const tail = parts.pop() ?? '';
  return { lines: parts, rest: tail + hold };
}

/**
 * 解析单行，写入当前消息的累积状态。
 *
 * ⚠️ 这是整个前端最容易静默失效的地方：
 *    Java 的 SseEmitter 输出 `event:step`（无空格）
 *    Python 手写输出     `event: step`（有空格）
 *    两者都符合规范。只认一种的解析器会「HTTP 200 但一个事件都收不到」。
 */
export function applyLine(line: string, cur: RawMessage): 'continue' | 'dispatch' {
  // 空行 = 一条消息结束
  if (line === '') return 'dispatch';

  // 注释行（心跳 `: ping`），直接丢弃
  if (line.startsWith(':')) return 'continue';

  const idx = line.indexOf(':');
  // 没有冒号的行，按规范整个作为字段名，值为空
  const field = idx === -1 ? line : line.slice(0, idx);
  let value = idx === -1 ? '' : line.slice(idx + 1);
  // 规范：值若以一个空格开头，去掉这一个空格（只去一个）
  if (value.startsWith(' ')) value = value.slice(1);

  switch (field) {
    case 'event':
      cur.event = value;
      break;
    case 'data':
      // 多行 data 用 \n 拼接
      cur.data = cur.data ? `${cur.data}\n${value}` : value;
      break;
    case 'id':
      cur.id = value;
      break;
    case 'retry':
      // 我们自己做退避，忽略服务端的 retry 建议
      break;
    default:
      // 未知字段按规范忽略
      break;
  }
  return 'continue';
}

/** 把一条原始消息转成带类型的事件对象，解析失败返回 null 而不是抛异常 */
export function toAgentEvent(msg: RawMessage): AgentEvent | null {
  if (!msg.event || !KNOWN_EVENTS.has(msg.event)) return null;
  if (!msg.data) return null;

  let payload: unknown;
  try {
    payload = JSON.parse(msg.data);
  } catch {
    // 单条事件坏了不该拖垮整条流，记一条警告继续
    console.warn('[sse] 无法解析的 data，已跳过：', msg.event, msg.data.slice(0, 120));
    return null;
  }
  if (typeof payload !== 'object' || payload === null) return null;

  const type = msg.event as AgentEventType;
  return { type, ...(payload as EventPayloadMap[typeof type]) } as AgentEvent;
}

/**
 * 增量解析器：喂 chunk，吐事件。
 *
 * 把「切行 + 累积字段 + 派发」三件事封在一起，调用方不用自己维护 buffer 状态。
 */
export function createSSEParser() {
  let buffer = '';
  let cur: RawMessage = { event: '', data: '' };

  return {
    /** 喂一段原始文本，返回这段里完整的事件 */
    push(chunk: string): AgentEvent[] {
      const out: AgentEvent[] = [];
      buffer += chunk;

      const { lines, rest } = drainLines(buffer);
      buffer = rest;

      for (const line of lines) {
        if (applyLine(line, cur) === 'dispatch') {
          const evt = toAgentEvent(cur);
          cur = { event: '', data: '' };
          if (evt) out.push(evt);
        }
      }
      return out;
    },

    /**
     * 流结束时调用。
     *
     * 两种收尾情况都要兜住：
     *   1. buffer 里还卡着没有换行结尾的最后一行（部分服务端就这样，写完 data 直接关连接）
     *   2. 最后一条消息字段都齐了，但没有那个空行来触发 dispatch
     */
    flush(): AgentEvent[] {
      const out: AgentEvent[] = [];

      if (buffer) {
        const rest = buffer;
        buffer = '';
        for (const line of rest.replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n')) {
          if (applyLine(line, cur) === 'dispatch') {
            const evt = toAgentEvent(cur);
            cur = { event: '', data: '' };
            if (evt) out.push(evt);
          }
        }
      }

      if (cur.event && cur.data) {
        const evt = toAgentEvent(cur);
        cur = { event: '', data: '' };
        if (evt) out.push(evt);
      }

      return out;
    },
  };
}
