"""容器健康检查入口。

单独成文件，避免在 Dockerfile / compose 里写超长单行。
健康检查也要带 token —— 内部接口一律鉴权，不开口子。
"""

from __future__ import annotations

import os
import sys
import urllib.request

URL = "http://127.0.0.1:8000/internal/health"


def main() -> int:
    req = urllib.request.Request(
        URL,
        headers={"X-Internal-Token": os.environ.get("INTERNAL_TOKEN", "")},
    )
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            return 0 if resp.status == 200 else 1
    except Exception:  # noqa: BLE001
        return 1


if __name__ == "__main__":
    sys.exit(main())
