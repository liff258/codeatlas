"""诊断：扩容后 Hit@1 掉了，是「检索变差」还是「金标变窄」？

背景：补了 14 篇 AI 笔记后，rerank 的 Hit@1 从 78.4% 掉到 70.3%，
但 Recall@5 只掉了 2.7 个点。这个组合通常意味着：
**正确答案还在前 5，只是不再排第 1——被新的同主题内容挤下去了。**

关键问题是：挤上去的那条，到底是不是也是正确答案？
- 是 → 金标的关键词条件太窄（它只认旧文档的措辞），指标低估了系统。
- 否 → 真的被无关内容干扰了，是质量问题。

这个脚本对每道题打印：金标条件、top1 的标题和开头、以及 top1 是否满足金标。

用法：
    python scripts/diagnose_hit1.py --subject ai
    python scripts/diagnose_hit1.py --all
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "services" / "python-agent"))

import yaml  # noqa: E402

from app.rag.retrieve import get_retriever  # noqa: E402


def load_gold() -> list[dict]:
    data = yaml.safe_load((ROOT / "eval" / "gold_set.yaml").read_text(encoding="utf-8"))
    return data["cases"]


def matches(heading: str, content: str, case: dict) -> bool:
    """直接复用评测脚本的判定，不自己写一套。

    第一版自己实现了「must_have 全中 且 any_of 中一个」，两处错了：
    1. 语义题（kind=semantic）根本不看内容，看的是标题是否含 expect_heading；
    2. 评测里是大小写不敏感的（.lower()），我写成了敏感匹配。
    结果诊断出 22/37，和评测的 26/37 对不上——两套尺子量同一个东西，
    数字不一致就说明有一把是错的。
    """
    from eval_retrieval import is_relevant

    return is_relevant((heading, content), case)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--subject", default=None, help="只看某个学科")
    ap.add_argument("--all", action="store_true", help="不看学科，跑全部")
    ap.add_argument("--top-n", type=int, default=12,
                    help="重排窗口大小（默认 12，和线上一致）")
    args = ap.parse_args()

    cases = load_gold()
    if args.subject and not args.all:
        cases = [c for c in cases if c.get("subject") == args.subject]

    retriever = get_retriever()
    print(f"诊断 {len(cases)} 道题（rerank 模式，重排窗口 {args.top_n}）\n")

    rank1_ok = 0
    rank1_wrong = 0
    for c in cases:
        hits = retriever.search(c["question"], top_k=20, top_n=args.top_n, rerank=True)
        if not hits:
            print(f"[{c['id']}] {c['question']}  → 无结果")
            continue

        top = hits[0]
        ok = matches(top.heading_path or "", top.content, c)
        if ok:
            rank1_ok += 1
            continue

        # 前 5 里有没有合格的
        gold_rank = next(
            (i + 1 for i, h in enumerate(hits[:5])
             if matches(h.heading_path or "", h.content, c)), None
        )
        rank1_wrong += 1
        print(f"[{c['id']}] {c['question']}")
        cond = (f"标题含 {c['expect_heading']}" if c.get("kind") == "semantic"
                else f"must={c.get('must_have')} any={c.get('any_of')}")
        print(f"  金标条件：{cond}")
        print(f"  top1 来自：{(top.heading_path or '')[:70]}")
        print(f"  top1 开头：{' '.join(top.content.split())[:90]}")
        print(f"  前 5 里是否有合格答案：{'有，排第 ' + str(gold_rank) if gold_rank else '没有'}")
        print()

    print("=" * 60)
    print(f"top1 合格：{rank1_ok} / {len(cases)}")
    print(f"top1 不合格：{rank1_wrong}（其中前 5 有合格答案的算「金标过窄」）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
