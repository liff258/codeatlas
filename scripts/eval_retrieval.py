"""检索评测：BM25 / 向量 / 混合三种模式的横向对比。

这是整个 P1 最该做的一件事——没有数字，就没法回答
「加了向量到底有没有用」「RRF 融合是不是真的比单路好」。

指标：
    Hit@1    第一条就命中相关 chunk 的比例
    Recall@5 前 5 条里至少有一条相关的比例
    MRR@10   第一条相关结果的排名倒数的均值（越接近 1 越好）

判相关的标准来自 eval/gold_set.yaml 的关键词条件（见该文件的说明）。

用法：
    python scripts/eval_retrieval.py                # 三种模式全跑
    python scripts/eval_retrieval.py --mode bm25    # 只跑一种（不用加载模型，很快）
    python scripts/eval_retrieval.py --show-miss    # 打印没命中的题，便于调优
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "services" / "python-agent"))

TOP_K = 10


def load_gold() -> list[dict]:
    data = yaml.safe_load((ROOT / "eval" / "gold_set.yaml").read_text(encoding="utf-8"))
    return data["cases"]


def is_relevant(chunk: tuple[str, str], case: dict) -> bool:
    """两种判定方式，对应两类题。

    关键词型（默认）：内容里 must_have 全中 且 any_of 至少中一个。
    语义型（kind=semantic）：标题里包含 expect_heading 之一。
        语义题的正确文档往往不含问题里的原词（问"怎么不被压垮"，文档写的是"限流熔断"），
        用内容关键词判会系统性判错向量检索，所以改成看标题。
    """
    heading, content = chunk

    if case.get("kind") == "semantic":
        h = heading.lower()
        return any(w.lower() in h for w in case["expect_heading"])

    low = content.lower()
    if not all(w.lower() in low for w in case["must_have"]):
        return False
    return any(w.lower() in low for w in case["any_of"])


def load_contents() -> dict[int, tuple[str, str]]:
    from sqlalchemy import text

    from app.infra.db import SessionLocal

    with SessionLocal() as db:
        rows = db.execute(
            text("SELECT id, heading_path, content FROM chunk WHERE level = 'child'")
        ).all()
    return {r[0]: (r[1] or "", r[2]) for r in rows}


def score(
    ranked_ids: list[int], contents: dict[int, tuple[str, str]], case: dict
) -> tuple[bool, bool, float]:
    """返回 (hit@1, recall@5, reciprocal_rank)。"""
    hit1 = bool(ranked_ids) and is_relevant(contents.get(ranked_ids[0], ("", "")), case)
    rec5 = any(is_relevant(contents.get(cid, ("", "")), case) for cid in ranked_ids[:5])

    rr = 0.0
    for i, cid in enumerate(ranked_ids[:TOP_K], start=1):
        if is_relevant(contents.get(cid, ("", "")), case):
            rr = 1.0 / i
            break
    return hit1, rec5, rr


def run_mode(mode: str, cases: list[dict], contents: dict[int, tuple[str, str]], *, show_miss: bool) -> dict:
    from app.rag.bm25_index import build_from_db
    from app.rag.retrieve import rrf_fuse
    from app.rag.vector_index import search as vec_search

    print(f"\n{'='*64}\n模式：{mode}\n{'='*64}")

    t0 = time.time()
    bm25 = build_from_db() if mode in ("bm25", "hybrid", "rerank") else None
    provider = None
    if mode in ("vector", "hybrid", "rerank"):
        from app.rag.embedding import LocalBGEEmbedding

        provider = LocalBGEEmbedding()

    reranker = None
    if mode == "rerank":
        from app.rag.rerank import Reranker

        reranker = Reranker()
    print(f"准备耗时 {time.time()-t0:.1f}s（{len(bm25) if bm25 else 0} 条 BM25 文档）\n")

    hits1 = rec5 = 0
    rrs: list[float] = []
    misses: list[tuple[str, str]] = []
    # 按题型分开统计：关键词题和语义题考的完全是两种能力，混在一起看会互相掩盖
    by_kind: dict[str, dict] = {}
    by_domain: dict[str, dict] = {}

    for case in cases:
        q = case["question"]
        t = time.time()

        if mode == "bm25":
            ranked = [h.chunk_id for h in bm25.search(q, top_k=TOP_K)]
        elif mode == "vector":
            qvec = provider.encode([q], is_query=True)[0]
            ranked = [h.chunk_id for h in vec_search(qvec, top_k=TOP_K)]
        elif mode == "hybrid":
            b = bm25.search(q, top_k=TOP_K)
            qvec = provider.encode([q], is_query=True)[0]
            v = vec_search(qvec, top_k=TOP_K)
            ranked = [h.chunk_id for h in rrf_fuse(b, v, top_n=TOP_K)]
        else:  # rerank：融合出更多候选，再重排取前 TOP_K
            b = bm25.search(q, top_k=TOP_K)
            qvec = provider.encode([q], is_query=True)[0]
            v = vec_search(qvec, top_k=TOP_K)
            fused = rrf_fuse(b, v, top_n=max(TOP_K, 20))
            ids = [h.chunk_id for h in fused]
            # 重排只看内容，不需要 heading，这里用空 heading 占位
            pairs = [(contents.get(i, ("", ""))[0], contents.get(i, ("", ""))[1]) for i in ids]
            scores = reranker.score(q, [c for _, c in pairs])
            order = sorted(range(len(ids)), key=lambda k: -scores[k])
            ranked = [ids[k] for k in order][:TOP_K]

        h1, r5, rr = score(ranked, contents, case)
        hits1 += h1
        rec5 += r5
        rrs.append(rr)

        kind = "semantic" if case.get("kind") == "semantic" else "keyword"
        st = by_kind.setdefault(kind, {"n": 0, "hit1": 0, "rec5": 0, "rr": 0.0})
        # 按知识域分组：后端题和 AI 题考的素材完全不同，
        # 混在一起看会掩盖「某个域的素材太薄」这种问题。
        dom = case.get("domain", "backend")
        ds = by_domain.setdefault(dom, {"n": 0, "hit1": 0, "rec5": 0, "rr": 0.0})
        ds["n"] += 1
        ds["hit1"] += int(h1)
        ds["rec5"] += int(r5)
        ds["rr"] += rr
        st["n"] += 1
        st["hit1"] += int(h1)
        st["rec5"] += int(r5)
        st["rr"] += rr

        mark = "✓" if h1 else ("·" if r5 else "✗")
        print(f"  {mark} {case['id']}  rr={rr:.2f}  {q[:34]}  ({time.time()-t:.2f}s)")

        if show_miss and not r5:
            top1 = (
                " ".join(contents.get(ranked[0], ("", ""))[1].split())[:70] if ranked else "(空)"
            )
            misses.append((case["id"], f"{q} → top1: {top1}"))

    n = len(cases)
    result = {
        "mode": mode,
        "hit1": hits1 / n,
        "recall5": rec5 / n,
        "mrr": sum(rrs) / n,
        "by_kind": by_kind,
        "by_domain": by_domain,
    }

    print(f"\n  合计   Hit@1 {result['hit1']*100:5.1f}%   Recall@5 {result['recall5']*100:5.1f}%   MRR {result['mrr']:.3f}")
    for kind in ("keyword", "semantic"):
        st = by_kind.get(kind)
        if not st or not st["n"]:
            continue
        print(
            f"  {kind:<7} Hit@1 {st['hit1']/st['n']*100:5.1f}%   "
            f"Recall@5 {st['rec5']/st['n']*100:5.1f}%   MRR {st['rr']/st['n']:.3f}"
            f"   (n={st['n']})"
        )
    for dom in ("backend", "ai"):
        ds = by_domain.get(dom)
        if not ds or not ds["n"]:
            continue
        print(
            f"  {dom:<7} Hit@1 {ds['hit1']/ds['n']*100:5.1f}%   "
            f"Recall@5 {ds['rec5']/ds['n']*100:5.1f}%   MRR {ds['rr']/ds['n']:.3f}"
            f"   (n={ds['n']})"
        )

    if misses:
        print("\n  未命中：")
        for cid, info in misses:
            print(f"    {cid}  {info}")

    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--mode", choices=["bm25", "vector", "hybrid", "rerank"], action="append"
    )
    ap.add_argument("--show-miss", action="store_true")
    args = ap.parse_args()

    cases = load_gold()
    contents = load_contents()
    print(f"评测集：{len(cases)} 题；候选池：{len(contents)} 个 child chunk")

    modes = args.mode or ["bm25", "vector", "hybrid", "rerank"]
    results = [run_mode(m, cases, contents, show_miss=args.show_miss) for m in modes]

    if len(results) > 1:
        print(f"\n{'='*72}\n汇总\n{'='*72}")
        print(f"{'模式':<10}{'题型':<10}{'Hit@1':>9}{'Recall@5':>11}{'MRR@10':>10}")
        print("-" * 72)
        for r in results:
            for kind in ("all", "keyword", "semantic", "backend", "ai"):
                if kind == "all":
                    print(
                        f"{r['mode']:<10}{'合计':<10}{r['hit1']*100:>8.1f}%"
                        f"{r['recall5']*100:>10.1f}%{r['mrr']:>10.3f}"
                    )
                else:
                    bucket = r["by_kind"].get(kind) or r["by_domain"].get(kind)
                    if not bucket or not bucket["n"]:
                        continue
                    print(
                        f"{'':<10}{kind:<10}{bucket['hit1']/bucket['n']*100:>8.1f}%"
                        f"{bucket['rec5']/bucket['n']*100:>10.1f}%{bucket['rr']/bucket['n']:>10.3f}"
                    )
            print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
