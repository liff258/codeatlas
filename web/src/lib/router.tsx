/**
 * 极简 hash 路由。
 *
 * 为什么不用 react-router-dom：
 * `contracts/deps.md` 是依赖白名单，CLAUDE.md 规则 5 禁止引入清单外的库。
 * 引入需要改白名单、承担版本与打包体积代价，而这里只需要「解析 hash + 监听变化」。
 *
 * 为什么用 hash 而不是 history API：
 *   1. 静态预览（vite preview / 直接开 dist/index.html）不需要 rewrite 配置，
 *      刷新深层链接不会 404
 *   2. hashchange 天然支持浏览器前进后退，不用自己维护 history 栈
 *
 * 代价是 URL 里多个 `#`，对内部演示无所谓。
 */

import { useCallback, useEffect, useState } from 'react';

export type Route =
  | { name: 'home' }
  | { name: 'subject'; subject: string }
  | { name: 'kp'; id: string }
  | { name: 'entity'; entity: string }
  | { name: 'questions' }
  | { name: 'chat' };

export interface RouteState {
  route: Route;
  query: URLSearchParams;
  /** 原始 hash，作为 effect 依赖用 */
  raw: string;
}

function decode(s: string): string {
  try {
    return decodeURIComponent(s);
  } catch {
    return s;
  }
}

export function parseHash(hash: string): RouteState {
  // "#/s/并发?type=question" → "/s/并发?type=question"
  const raw = hash.replace(/^#/, '') || '/';
  const [pathPart, queryPart = ''] = raw.split('?');
  const segs = pathPart.split('/').filter(Boolean).map(decode);

  const query = new URLSearchParams(queryPart);

  let route: Route;
  if (segs.length === 0) {
    route = { name: 'home' };
  } else if (segs[0] === 's' && segs[1]) {
    route = { name: 'subject', subject: segs[1] };
  } else if (segs[0] === 'kp' && segs[1]) {
    route = { name: 'kp', id: segs[1] };
  } else if (segs[0] === 'e' && segs[1]) {
    route = { name: 'entity', entity: segs[1] };
  } else if (segs[0] === 'questions') {
    route = { name: 'questions' };
  } else if (segs[0] === 'chat') {
    route = { name: 'chat' };
  } else {
    // 未知路径回首页，不白屏
    route = { name: 'home' };
  }

  return { route, query, raw };
}

export function useRoute(): RouteState {
  const [state, setState] = useState<RouteState>(() => parseHash(window.location.hash));

  useEffect(() => {
    const onChange = () => setState(parseHash(window.location.hash));
    window.addEventListener('hashchange', onChange);
    return () => window.removeEventListener('hashchange', onChange);
  }, []);

  return state;
}

/** 跳转。replace=true 时不产生新的历史记录（比如参数纠正） */
export function navigate(to: string, opts: { replace?: boolean } = {}): void {
  const target = to.startsWith('#') ? to : `#${to}`;
  if (window.location.hash === target) return;
  if (opts.replace) {
    const url = `${window.location.pathname}${window.location.search}${target}`;
    window.history.replaceState(null, '', url);
    // replaceState 不触发 hashchange，手动派发一次
    window.dispatchEvent(new HashChangeEvent('hashchange'));
  } else {
    window.location.hash = target;
  }
}

export function useNavigate(): (to: string, opts?: { replace?: boolean }) => void {
  return useCallback((to: string, opts?: { replace?: boolean }) => navigate(to, opts), []);
}

/** 拼查询串，忽略空值 */
export function buildQuery(params: Record<string, string | number | undefined | null>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue;
    sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : '';
}
