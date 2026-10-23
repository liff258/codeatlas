/**
 * SSE 客户端 —— fetch + ReadableStream
 *
 * 为什么不用 EventSource：
 *   1. 只支持 GET，问题文本塞不进 URL（长问题会超长）
 *   2. 不能带自定义 Header（trace_id / 鉴权都传不了）
 *   3. 出错后会自动重连，我们没有幂等的重放能力
 *
 * 协议解析在 ./sse-parser.ts（纯函数，有单测）。
 * 契约见 contracts/sse-events.md
 */

import type { AgentEvent } from '../types/events';
import { createSSEParser, toAgentEvent } from './sse-parser';

/* ────────────────────────── 错误类型 ────────────────────────── */

export class StreamError extends Error {
  code: 'HTTP' | 'PARSE' | 'NETWORK' | 'EMPTY_BODY';

  constructor(code: StreamError['code'], message: string) {
    super(message);
    this.name = 'StreamError';
    this.code = code;
  }
}

/* ────────────────────────── 请求体 ────────────────────────── */

export interface ChatRequestBody {
  question: string;
  session_id?: string | null;
  history?: { role: 'user' | 'assistant'; content: string }[];
}

export interface StreamOptions {
  signal?: AbortSignal;
  /** 断线续传：从哪个 seq 之后继续 */
  lastEventId?: number;
  /** 收到响应头时回调，用于把 UI 从「连接中」切到「已连接」 */
  onOpen?: () => void;
}

/* ────────────────────────── Mock 回放 ────────────────────────── */

export function isMockMode(): boolean {
  // 兜底：没有后端也能演示，这是 README 里 10 分钟复现路径的一环
  return import.meta.env.VITE_MOCK === '1';
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(new DOMException('aborted', 'AbortError'));
    const t = setTimeout(resolve, ms);
    signal?.addEventListener(
      'abort',
      () => {
        clearTimeout(t);
        reject(new DOMException('aborted', 'AbortError'));
      },
      { once: true },
    );
  });
}

/**
 * 回放 mock/stream.jsonl。
 *
 * 这份文件由 scripts/gen_mock_stream.py 从 Python 的 mock_runner 直接导出，
 * 所以事件顺序与真实链路**逐字节一致**——手工编一份假流，演示时一定会露馅。
 */
async function* replayMock(opts: StreamOptions): AsyncGenerator<AgentEvent> {
  const { default: raw } = await import('../mock/stream.jsonl?raw');
  const lines = String(raw)
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean);

  opts.onOpen?.();

  for (const line of lines) {
    let rec: { event: string; data: unknown };
    try {
      rec = JSON.parse(line);
    } catch {
      continue;
    }
    const evt = toAgentEvent({ event: rec.event, data: JSON.stringify(rec.data) });
    if (!evt) continue;
    if (opts.lastEventId !== undefined && evt.seq <= opts.lastEventId) continue;

    // 按事件类型给不同的节奏，模拟真实流的手感
    const delay =
      evt.type === 'token' ? 16 : evt.type === 'step' ? 90 : evt.type === 'retrieval' ? 140 : 60;
    await sleep(delay, opts.signal);
    yield evt;
  }
}

/* ────────────────────────── 主入口 ────────────────────────── */

const ENDPOINT = '/api/chat/stream';

/**
 * 发起一次问答并逐条产出事件。
 *
 * 用法：
 *   for await (const evt of postAgentStream({ question }, { signal })) { ... }
 *
 * 中断：调用方 abort(signal)，生成器会安静地结束，不抛错。
 */
export async function* postAgentStream(
  body: ChatRequestBody,
  opts: StreamOptions = {},
): AsyncGenerator<AgentEvent> {
  if (isMockMode()) {
    yield* replayMock(opts);
    return;
  }

  let res: Response;
  try {
    res = await fetch(ENDPOINT, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
        // 防止中间层（部分代理）做 gzip 缓冲
        'Cache-Control': 'no-cache',
        ...(opts.lastEventId !== undefined
          ? { 'Last-Event-ID': String(opts.lastEventId) }
          : {}),
      },
      body: JSON.stringify(body),
      signal: opts.signal,
    });
  } catch (e) {
    if ((e as Error).name === 'AbortError') return;
    throw new StreamError('NETWORK', '无法连接到服务，请确认后端已启动');
  }

  if (!res.ok) {
    // 后端出错时返回的是 JSON 而不是事件流，这里要读出来给人看
    const text = await res.text().catch(() => '');
    throw new StreamError('HTTP', `服务返回 ${res.status}${text ? `：${text.slice(0, 200)}` : ''}`);
  }
  if (!res.body) {
    throw new StreamError('EMPTY_BODY', '浏览器不支持流式响应（response.body 为空）');
  }

  opts.onOpen?.();

  const reader = res.body.getReader();
  const decoder = new TextDecoder('utf-8');
  const parser = createSSEParser();
  let lastSeq = opts.lastEventId ?? 0;

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;

      // stream: true 让多字节汉字被劈开时也能正确拼回来
      for (const evt of parser.push(decoder.decode(value, { stream: true }))) {
        // 契约 §6：重连会重发，用 seq 去重
        if (evt.seq <= lastSeq) continue;
        lastSeq = evt.seq;
        yield evt;
      }
    }

    // 流正常结束但最后一个事件没有以空行收尾（部分实现会这样）
    for (const tail of parser.flush()) {
      if (tail.seq > lastSeq) yield tail;
    }
  } catch (e) {
    if ((e as Error).name === 'AbortError') return;
    throw new StreamError('NETWORK', `流式读取中断：${(e as Error).message}`);
  } finally {
    // 无论是正常结束还是提前 return，都要释放 reader，否则连接会挂着
    reader.cancel().catch(() => {});
  }
}
