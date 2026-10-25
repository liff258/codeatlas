"""通过 GitHub API 推送提交（git 协议被阻断时的备用通道）。

背景：
    这台机器上 github.com:443 连不上（git push 直接失败），但 api.github.com 是通的。
    SSH 的 22 端口不通，ssh.github.com:443 能连但没有密钥、token 也没有 admin:public_key 权限。

    所以走 Git Data API 把本地提交「重放」到远端：
        每个 commit → 为改动文件建 blob → 建 tree → 建 commit → 移动 ref

    这样历史是完整保留的，不是压成一个 squash 提交。

用法：
    python scripts/push_via_api.py --dry-run    # 只看要推哪些提交
    python scripts/push_via_api.py              # 真推
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = "liff258/codeatlas"
BRANCH = "master"


def git(*args: str) -> str:
    # core.quotepath=false：否则中文路径会被转义成 \347\237\245 这种八进制串
    return subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout.strip()


def gh_api(path: str, *, method: str = "GET", body: dict | None = None) -> dict:
    cmd = ["gh", "api", path, "--method", method]
    if body is not None:
        cmd += ["--input", "-"]
    r = subprocess.run(
        cmd,
        input=json.dumps(body) if body is not None else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if r.returncode != 0:
        raise RuntimeError(f"API 失败 {path}: {r.stderr.strip()[:300]}")
    return json.loads(r.stdout) if r.stdout.strip() else {}


def changed_files(sha: str) -> list[tuple[str, str]]:
    """返回 [(状态, 路径)]，状态是 A/M/D。"""
    out = git("diff-tree", "--no-commit-id", "--name-status", "-r", sha)
    rows = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            status = parts[0][0]  # R100 之类的取首字母
            rows.append((status, parts[-1]))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--since",
        help="只重放这个本地 SHA 之后的提交。用于「本地有影子提交、远端已存在同内容」的情况——"
        "不指定的话会把已经推过的提交再重放一遍。",
    )
    args = ap.parse_args()

    remote_sha = gh_api(f"repos/{REPO}/git/ref/heads/{BRANCH}")["object"]["sha"]
    base = args.since or remote_sha
    local_commits = git("rev-list", "--reverse", f"{base}..HEAD").split()

    if not local_commits:
        print("✓ 远端已是最新，无需推送")
        return 0

    print(f"远端 {BRANCH} 当前：{remote_sha[:8]}")
    print(f"待推送 {len(local_commits)} 个提交\n")

    parent = remote_sha
    for i, sha in enumerate(local_commits, 1):
        msg = git("log", "-1", "--pretty=%B", sha)
        files = changed_files(sha)
        print(f"[{i}/{len(local_commits)}] {sha[:8]} {msg.splitlines()[0]}")
        print(f"          {len(files)} 个文件")

        if args.dry_run:
            for st, p in files[:5]:
                print(f"            {st} {p}")
            if len(files) > 5:
                print(f"            …还有 {len(files)-5} 个")
            continue

        entries = []
        for status, path in files:
            if status == "D":
                entries.append({"path": path, "mode": "100644", "type": "blob", "sha": None})
                continue

            fpath = ROOT / path
            if not fpath.exists():
                print(f"            ⚠ 文件不存在，跳过：{path}")
                continue

            data = fpath.read_bytes()
            blob = gh_api(
                f"repos/{REPO}/git/blobs",
                method="POST",
                body={"content": base64.b64encode(data).decode(), "encoding": "base64"},
            )
            mode = "100755" if git("ls-files", "-s", path).startswith("100755") else "100644"
            entries.append({"path": path, "mode": mode, "type": "blob", "sha": blob["sha"]})

        tree = gh_api(
            f"repos/{REPO}/git/trees",
            method="POST",
            body={"base_tree": gh_api(f"repos/{REPO}/git/commits/{parent}")["tree"]["sha"],
                  "tree": entries},
        )
        commit = gh_api(
            f"repos/{REPO}/git/commits",
            method="POST",
            body={"message": msg, "tree": tree["sha"], "parents": [parent]},
        )
        gh_api(
            f"repos/{REPO}/git/refs/heads/{BRANCH}",
            method="PATCH",
            body={"sha": commit["sha"], "force": False},
        )

        print(f"          → {commit['sha'][:8]}")
        parent = commit["sha"]

    if args.dry_run:
        print("\n（dry-run，未实际推送）")
        return 0

    # 让本地 origin/master 指向远端真实状态，避免下次 push 时重复推
    git("fetch", "origin", BRANCH, "--depth=1") if False else None
    print(f"\n✓ 完成，远端 {BRANCH} → {parent[:8]}")
    print("提示：本地 origin/master 的引用可能还是旧的，下次网络恢复时 git fetch 一下即可。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
