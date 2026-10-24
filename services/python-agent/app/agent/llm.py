"""对话模型客户端（智谱 GLM-4.5-Flash）。

三个设计决定：

1. **不依赖 `response_format={"type":"json_object"}`**
   智谱文档没有明确承诺这个参数，而且小模型即使接口支持，输出也经常不严格遵守
   （多一句"好的，以下是 JSON："、尾部多逗号、用中文引号）。所以自己解析 + 修。

2. **JSON 解析失败不抛异常，而是返回 `degraded=True`**
   节点拿到 None 就走自己的降级分支。这条规则很重要——如果这里抛异常，
   整条 SSE 流会断在半路，前端永远停在"正在思考"。宁可给一个粗糙的答案，
   也不能让界面卡死。

3. **用量在客户端内累计**
   `done` 事件要报 input/output tokens 和成本。每个节点各自统计会很乱，
   统一在这里累加，编排层结束时读一次即可。
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass

from app.agent.events import Usage
from app.config import settings

# 模型偶尔会把 JSON 包在 markdown 围栏里，甚至带一句中文前缀
_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)
# 中文全角引号 → 半角（模型经常在 JSON 里用 “” 包字符串）
_SMART_QUOTES = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'"})
# 尾部多余逗号：{"a":1,} 或 [1,2,]
_TRAILING_COMMA = re.compile(r",\s*([}\]])")


class LLMError(RuntimeError):
    """带契约错误码的异常，编排层据此决定发哪种 error 事件。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class LLMResult:
    text: str
    data: dict | None
    degraded: bool = False
    detail: str = ""


@dataclass
class _UsageCounter:
    input_tokens: int = 0
    output_tokens: int = 0

    def add(self, inp: int, out: int) -> None:
        self.input_tokens += inp
        self.output_tokens += out

    def snapshot(self) -> Usage:
        # GLM-4.5-Flash 免费，成本恒为 0。但 token 数照报——
        # 换到收费模型时这个字段就直接有用了，不用改协议。
        return Usage(
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            cost_cny=0.0,
        )


def extract_json(text: str) -> dict | None:
    """从任意文本里抠出第一个 JSON 对象。抠不出来返回 None。

    步骤：去围栏 → 括号配对扫描（容忍前后有废话）→ 修中文引号和尾逗号 → 解析。

    为什么用括号配对而不是 `find('{')` + `rfind('}')`：
    后者在模型输出两个对象、或者字符串里含 `}` 时会截错。
    """
    if not text or not text.strip():
        return None

    cleaned = _FENCE.sub("", text.strip())

    start = cleaned.find("{")
    if start == -1:
        return None

    depth = 0
    in_str = False
    escape = False
    end = -1

    for i in range(start, len(cleaned)):
        ch = cleaned[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break

    # 括号没闭合（输出被 max_tokens 截断）→ 直接放弃，不要猜
    if end == -1:
        return None

    candidate = cleaned[start : end + 1]

    for attempt in (candidate, _TRAILING_COMMA.sub(r"\1", candidate.translate(_SMART_QUOTES))):
        try:
            parsed = json.loads(attempt)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(parsed, dict):
            return parsed

    return None


class LLMClient:
    """对话模型封装。一个请求内复用一个实例，用量自动累计。"""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
    ) -> None:
        key = (api_key if api_key is not None else settings.llm_api_key).strip()
        if not key:
            raise LLMError("INTERNAL", "LLM_API_KEY 未配置，无法调用模型")

        # 延迟导入：没装 openai 或没配 key 时，模块本身仍可被 import（测试友好）
        from openai import AsyncOpenAI

        self.model = model or settings.agent_model
        self._timeout = timeout or settings.llm_timeout_seconds
        self._client = AsyncOpenAI(
            api_key=key,
            base_url=base_url or settings.llm_base_url,
            timeout=self._timeout,
            max_retries=0,  # 重试由我们自己控，避免和 SDK 的重试叠加
        )
        self._usage = _UsageCounter()

    @property
    def usage(self) -> Usage:
        return self._usage.snapshot()

    async def _post(
        self, messages: list[dict], *, stream: bool, temperature: float, max_tokens: int
    ):
        """统一处理异常映射。SDK 的异常类型太细，上层只关心三类。"""
        try:
            return await self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=stream,
            )
        except asyncio.TimeoutError as e:
            raise LLMError("LLM_TIMEOUT", f"模型响应超时（{self._timeout}s）") from e
        except Exception as e:  # noqa: BLE001
            name = type(e).__name__
            status = getattr(e, "status_code", None)
            if status == 429 or "RateLimit" in name:
                raise LLMError("LLM_RATE_LIMIT", "模型限流，请稍后再试") from e
            if "Timeout" in name:
                raise LLMError("LLM_TIMEOUT", f"模型响应超时（{self._timeout}s）") from e
            raise LLMError("INTERNAL", f"模型调用失败：{name}") from e

    async def json_call(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.1,
        max_tokens: int = 1200,
    ) -> LLMResult:
        """要一个 JSON 对象。解析失败不抛异常，返回 degraded=True。"""
        resp = await self._post(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            stream=False,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        if resp.usage:
            self._usage.add(resp.usage.prompt_tokens or 0, resp.usage.completion_tokens or 0)

        text = (resp.choices[0].message.content or "").strip() if resp.choices else ""
        data = extract_json(text)

        if data is None:
            return LLMResult(
                text=text,
                data=None,
                degraded=True,
                detail=f"JSON 解析失败，原始输出前 40 字：{text[:40]!r}",
            )

        return LLMResult(text=text, data=data)

    async def stream_call(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.3,
        max_tokens: int = 2000,
    ) -> AsyncIterator[str]:
        """流式生成。逐个 delta 吐文本。

        用量在流结束后一次性累加——GLM 的流式响应默认不带 usage，
        只能按字符数粗估（中文约 1 字 1 token），够用。
        """
        stream = await self._post(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            stream=True,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        produced = 0
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            piece = getattr(delta, "content", None)
            if piece:
                produced += len(piece)
                yield piece

        # 输入侧按 prompt 长度粗估，输出侧按实际产出字符数
        self._usage.add((len(system) + len(user)) // 2, produced // 2)

    async def close(self) -> None:
        await self._client.close()


def build_client() -> LLMClient:
    return LLMClient()
