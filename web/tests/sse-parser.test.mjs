/**
 * SSE 解析器单测
 *
 * 跑法：npm test（内部用 esbuild 把 TS 打成临时 ESM 再 import，不需要额外装 tsx/ts-node）
 *
 * 为什么这些用例值得写：
 *   解析器出错的症状是「HTTP 200，但页面一片空白」，不报错、不超时。
 *   这种人眼看不出来的 bug，只能靠测试挡住。
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { mkdtemp, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const ROOT = path.resolve(import.meta.dirname, '..');

/** 把 TS 源码临时打成 ESM 再 import */
async function load(entry) {
  const dir = await mkdtemp(path.join(tmpdir(), 'codeatlas-'));
  const outfile = path.join(dir, 'mod.mjs');
  await build({
    entryPoints: [path.join(ROOT, entry)],
    outfile,
    bundle: true,
    format: 'esm',
    platform: 'neutral',
    target: 'es2022',
    logLevel: 'silent',
  });
  return import(pathToFileURL(outfile).href);
}

const parser = await load('src/lib/sse-parser.ts');

const frame = (event, payload, sep = ':') =>
  `event${sep}${sep === ':' ? ' ' : ''}${event}\ndata${sep}${sep === ':' ? ' ' : ''}${JSON.stringify(payload)}\n\n`;

const STEP = { seq: 1, trace_id: 't_test01', ts: 1761195600123, node: 'router', status: 'running', label: '判断问题意图' };

/* ────────────────────────── 冒号空格 ────────────────────────── */

test('无空格的 event:step 能解析（Java SseEmitter 的输出格式）', () => {
  const p = parser.createSSEParser();
  const evts = p.push(`event:step\ndata:${JSON.stringify(STEP)}\n\n`);
  assert.equal(evts.length, 1);
  assert.equal(evts[0].type, 'step');
  assert.equal(evts[0].node, 'router');
});

test('有空格的 event: step 能解析（Python 手写的输出格式）', () => {
  const p = parser.createSSEParser();
  const evts = p.push(frame('step', STEP));
  assert.equal(evts.length, 1);
  assert.equal(evts[0].type, 'step');
});

test('同一个流里两种写法混着来也不会漏事件', () => {
  const p = parser.createSSEParser();
  const evts = p.push(
    `event:step\ndata:${JSON.stringify(STEP)}\n\n` +
      frame('step', { ...STEP, seq: 2, status: 'ok' }),
  );
  assert.equal(evts.length, 2);
  assert.deepEqual(evts.map((e) => e.seq), [1, 2]);
});

/* ────────────────────────── 分块 ────────────────────────── */

test('\\r\\n 被 chunk 边界劈成两半时不能丢字符', () => {
  const p = parser.createSSEParser();
  const full = `event: step\r\ndata: ${JSON.stringify(STEP)}\r\n\r\n`;
  // 故意切在 \r 和 \n 之间
  const cut = full.indexOf('\r\n') + 1;

  assert.equal(p.push(full.slice(0, cut)).length, 0, '半个换行不该产出事件');
  const evts = p.push(full.slice(cut));
  assert.equal(evts.length, 1);
  assert.equal(evts[0].seq, 1);
});

test('逐字符喂入与整段喂入结果一致', () => {
  const full = frame('step', STEP) + frame('token', { ...STEP, seq: 2, text: 'G1 使用 SATB' });

  const oneShot = parser.createSSEParser().push(full);

  const p = parser.createSSEParser();
  const pieces = [];
  for (const ch of full) pieces.push(...p.push(ch));

  assert.equal(pieces.length, 2);
  assert.deepEqual(
    pieces.map((e) => [e.type, e.seq]),
    oneShot.map((e) => [e.type, e.seq]),
  );
  assert.equal(pieces[1].text, 'G1 使用 SATB', '中文不能被切坏');
});

test('多字节汉字被劈开时由调用方 TextDecoder 处理，解析器不额外截断', () => {
  const p = parser.createSSEParser();
  const evts = p.push(frame('token', { ...STEP, seq: 3, text: '快照标记' }));
  assert.equal(evts[0].text, '快照标记');
});

/* ────────────────────────── 杂项 ────────────────────────── */

test('心跳注释行被跳过，不产生事件', () => {
  const p = parser.createSSEParser();
  const evts = p.push(': ping\n\n');
  assert.equal(evts.length, 0);
});

test('多行 data 用 \\n 拼接', () => {
  const p = parser.createSSEParser();
  const evts = p.push(`event: token\ndata: {"seq":4,"trace_id":"t","ts":1,\ndata: "text":"ok"}\n\n`);
  assert.equal(evts.length, 1);
  assert.equal(evts[0].text, 'ok');
});

test('未知事件名直接丢弃，不污染流', () => {
  const p = parser.createSSEParser();
  const evts = p.push(frame('unknown_event', { seq: 5 }));
  assert.equal(evts.length, 0);
});

test('坏 JSON 只丢这一条，不抛异常', () => {
  const p = parser.createSSEParser();
  const orig = console.warn;
  console.warn = () => {};
  try {
    const evts = p.push('event: step\ndata: {不是合法 json\n\n' + frame('step', { ...STEP, seq: 6 }));
    assert.equal(evts.length, 1);
    assert.equal(evts[0].seq, 6);
  } finally {
    console.warn = orig;
  }
});

test('末尾没有空行收尾时，flush 能把最后一个事件捞出来', () => {
  const p = parser.createSSEParser();
  assert.equal(
    p.push(`event: done\ndata: ${JSON.stringify({ ...STEP, seq: 9, stop_reason: 'normal' })}`).length,
    0,
  );
  const tails = p.flush();
  assert.equal(tails.length, 1);
  assert.equal(tails[0].type, 'done');
  assert.equal(tails[0].seq, 9);
});

test('flush 之后重复调用不会吐重复事件', () => {
  const p = parser.createSSEParser();
  p.push(`event: done\ndata: ${JSON.stringify({ ...STEP, seq: 9, stop_reason: 'normal' })}`);
  assert.equal(p.flush().length, 1);
  assert.equal(p.flush().length, 0);
});

/* ────────────────────────── 真实 mock 流 ────────────────────────── */

test('mock/stream.jsonl 与契约第 5 节的顺序保证一致', async () => {
  const raw = await readFile(path.join(ROOT, 'src/mock/stream.jsonl'), 'utf8');
  const lines = raw.split('\n').filter((l) => l.trim());

  assert.ok(lines.length >= 40, `mock 事件太少：${lines.length}`);

  // 关键：把 jsonl 重新拼成 SSE 帧，走真正的解析器，而不是直接 JSON.parse。
  // 这样测的是「前端真实消费路径」，而不是「jsonl 文件本身合法」。
  const p = parser.createSSEParser();
  const evts = p.push(
    lines
      .map((l) => {
        const { event, data } = JSON.parse(l);
        return `event:${event}\ndata:${JSON.stringify(data)}\n\n`;
      })
      .join(''),
  );

  assert.equal(evts.length, lines.length, '有事件在解析过程中丢失');

  // 1. seq 从 1 连续递增
  assert.deepEqual(
    evts.map((e) => e.seq),
    Array.from({ length: evts.length }, (_, i) => i + 1),
  );

  // 2. 首尾
  assert.equal(evts[0].type, 'step');
  assert.equal(evts.at(-1).type, 'done');

  // 3. trace_id 全程一致
  assert.equal(new Set(evts.map((e) => e.trace_id)).size, 1);

  // 4. 顺序保证 2：plan 在所有 retrieval 之前
  const planIdx = evts.findIndex((e) => e.type === 'plan');
  const firstRetrieval = evts.findIndex((e) => e.type === 'retrieval');
  assert.ok(planIdx >= 0 && planIdx < firstRetrieval, 'plan 必须在首个 retrieval 之前');

  // 5. 顺序保证 3：rewrite_round=0 的 query_id 必须在 plan 里
  const planIds = new Set(evts[planIdx].sub_queries.map((q) => q.id));
  for (const e of evts.filter((x) => x.type === 'retrieval' && x.rewrite_round === 0)) {
    assert.ok(planIds.has(e.query_id), `首轮检索的 ${e.query_id} 不在 plan 里`);
  }

  // 6. 顺序保证 4：citation 在引用它的 token 之前
  const firstToken = evts.findIndex((e) => e.type === 'token');
  const firstCitation = evts.findIndex((e) => e.type === 'citation');
  assert.ok(firstCitation >= 0 && firstCitation < firstToken, 'citation 必须先于正文 token');

  // 7. 顺序保证 5：done 是最后一个
  assert.equal(evts.filter((e) => e.type === 'done').length, 1);

  // 8. 演示主线的核心证据：跨域边必须存在
  const graph = evts.find((e) => e.type === 'graph');
  assert.ok(graph, '缺少 graph 事件');
  const cross = graph.edges.filter((e) => e.cross_domain);
  assert.ok(cross.length > 0, '没有跨域边，演示主线立不住');
  for (const e of cross) {
    const a = graph.nodes.find((n) => n.id === e.source);
    const b = graph.nodes.find((n) => n.id === e.target);
    assert.notEqual(a.domain, b.domain, `跨域边 ${e.source}→${e.target} 两端 domain 相同`);
  }

  // 9. 性能硬约束：单次 graph 事件节点数 ≤ 80
  assert.ok(graph.nodes.length <= 80, `graph 节点数 ${graph.nodes.length} 超过 80，前端会卡`);
});
