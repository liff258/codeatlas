/**
 * 统一的后端请求封装。
 *
 * 之前只有 libraryGraph.ts 一个文件直接 fetch，各写各的解包逻辑。
 * 页面一多，`{code,message,data}` 这套包装会在每个页面里重复一遍，
 * 错误处理也会各写各的（有人抛、有人吞）。
 *
 * 这里统一做三件事：解包、非 0 抛错、把后端的 code 带在异常上
 * （前端要按 404 和 400 区分「数据没了」和「参数错了」）。
 */

export class ApiError extends Error {
  readonly code: number;
  readonly status: number;

  constructor(message: string, code: number, status: number) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
  }

  get notFound(): boolean {
    return this.status === 404;
  }
}

interface Envelope<T> {
  code: number;
  message: string;
  data: T;
}

export async function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, { headers: { Accept: 'application/json' }, signal });
  } catch (e) {
    // 网络层失败（断网、服务没起）——和业务错误分开，提示文案不一样
    throw new ApiError('连不上服务，检查后端是否启动', -1, 0);
  }

  let body: Envelope<T> | null = null;
  try {
    body = (await res.json()) as Envelope<T>;
  } catch {
    // 非 JSON 响应（比如网关返回的 HTML 错误页）
    throw new ApiError(`服务返回了非 JSON 响应（HTTP ${res.status}）`, -1, res.status);
  }

  if (!res.ok || body.code !== 0) {
    throw new ApiError(body.message || `请求失败（HTTP ${res.status}）`, body.code, res.status);
  }
  return body.data;
}
