/**
 * 30 行的数据加载 hook。
 *
 * 不引 TanStack Query：白名单里没有，而这个项目的页面都是「进页面拉一次数据」，
 * 不需要缓存、失效、重试那套。真正需要的是三件事：
 *   1. loading / error / data 三态
 *   2. 组件卸载后不再 setState（否则控制台一堆警告）
 *   3. 依赖变化时重新拉
 */

import { useEffect, useState } from 'react';

export interface AsyncState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

export function useAsync<T>(
  loader: (signal: AbortSignal) => Promise<T>,
  deps: unknown[],
): AsyncState<T> {
  const [state, setState] = useState<AsyncState<T>>({ data: null, loading: true, error: null });

  useEffect(() => {
    const ctrl = new AbortController();
    let alive = true;

    setState((s) => ({ ...s, loading: true, error: null }));

    loader(ctrl.signal)
      .then((data) => {
        if (alive) setState({ data, loading: false, error: null });
      })
      .catch((e: unknown) => {
        // 主动取消不算错误——那是用户切走了，不该在界面上闪红
        if (!alive || ctrl.signal.aborted) return;
        setState({ data: null, loading: false, error: (e as Error)?.message ?? '加载失败' });
      });

    return () => {
      alive = false;
      ctrl.abort();
    };
    // loader 每次渲染都是新函数，故意不进依赖；由调用方用 deps 控制时机
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return state;
}
