#!/usr/bin/env python
"""全库知识图谱构建（离线批处理）。

为什么是"每篇文档调一次模型"而不是"每个 chunk 调一次"：
    5484 个 chunk 逐个抽，成本和时间都不可接受（按 3 秒一次算要 4.5 小时）。
    按文档抽是同一个语义粒度的合理近似——一篇文档讲的核心概念，
    和它每个段落讲的概念高度重合，而调用量从 5484 降到 143。

为什么不用"章节标题当概念"的确定性做法（试过，放弃了）：
    标题里混着大量非概念：「完整代码以及测试」「按准备时间安排复习」「参考」。
    抽出来的图全是这种节点，比没有图更糟——评委一眼就看出是噪声。

断点续跑：
    每篇的结果落在 data/graph/<doc_id>.json，重跑时跳过已存在的。
    调模型要十几分钟，中途挂掉不该从头再来。

用法：
    python scripts/build_graph.py --limit 3        # 先试 3 篇看质量
    python scripts/build_graph.py                  # 全量
    python scripts/build_graph.py --load-only      # 只把已有 JSON 灌进库，不调模型
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "services" / "python-agent"))

import yaml  # noqa: E402

from app.agent.llm import LLMClient, LLMError, extract_json  # noqa: E402
from app.config import settings  # noqa: E402
from app.infra.db import SessionLocal  # noqa: E402

CACHE_DIR = ROOT / "data" / "graph"
VALID_TYPES = ("概念", "组件", "算法", "参数", "问题")
VALID_RELS = ("依赖", "属于", "对比", "导致", "解决", "使用")

SYSTEM = """你是技术知识图谱抽取器。读一篇技术文档的标题和章节结构，抽出核心概念和它们的关系。

规则：
1. 概念必须是**文档里真实出现的名词**，不要自己造，不要抽"总结/概述/参考/实战"这类泛词
2. 概念名控制在 2~18 个字，用文档里的原始写法（如「B+ 树」不要写成「B+树」）
3. 抽 5~8 个概念，类型只能是：概念 / 组件 / 算法 / 参数 / 问题
4. 关系只能从这六个里选：依赖 / 属于 / 对比 / 导致 / 解决 / 使用
5. 只抽**文档里确实讲了**的关系，不要凭常识补充。宁缺勿滥，没有关系就返回空数组

只输出 JSON，不要任何解释：
{"concepts": [{"name": "HNSW", "type": "算法"}],
 "edges": [{"source": "RAG", "target": "HNSW", "rel": "使用"}]}
"""


def norm(s: str) -> str:
    """归一化用于匹配：去空白、转小写。"""
    return re.sub(r"\s+", "", s).lower()


def load_docs() -> list[dict]:
    """把文档、正文、主导学科一次读出来。"""
    from sqlalchemy import text

    with SessionLocal() as db:
        docs = db.execute(
            text(
                """
                SELECT d.id, d.filename, count(c.id) AS n
                FROM document d
                JOIN chunk c ON c.document_id = d.id AND c.level = 'child'
                GROUP BY d.id, d.filename
                ORDER BY d.id
                """
            )
        ).all()

        subjects = {
            r[0]: r[1]
            for r in db.execute(
                text(
                    """
                    SELECT document_id, subject
                    FROM (
                        SELECT document_id, subject, row_number() OVER (
                            PARTITION BY document_id ORDER BY count(*) DESC
                        ) AS rn
                        FROM chunk
                        WHERE level = 'child' AND subject IS NOT NULL
                        GROUP BY document_id, subject
                    ) t WHERE rn = 1
                    """
                )
            )
        }

        out = []
        for doc_id, filename, _n in docs:
            rows = db.execute(
                text(
                    """
                    SELECT heading_path, content FROM chunk
                    WHERE document_id = :d AND level = 'child'
                    ORDER BY ordinal
                    """
                ),
                {"d": doc_id},
            ).all()
            headings = []
            for hp, _c in rows:
                seg = (hp or "").split(">")[-1].strip()
                if seg and seg not in headings:
                    headings.append(seg)
            text_all = "\n".join(c for _h, c in rows)
            out.append(
                {
                    "id": doc_id,
                    "filename": filename,
                    "subject": subjects.get(doc_id),
                    "headings": headings[:14],
                    "text": text_all,
                }
            )
        return out


def build_prompt(doc: dict) -> str:
    heads = "\n".join(f"- {h}" for h in doc["headings"]) or "（无小标题）"
    # 正文只给开头 700 字：够判断主题，又不至于把上下文撑爆
    return (
        f"文档标题：{doc['filename']}\n"
        f"学科：{doc['subject'] or '未知'}\n\n"
        f"章节结构：\n{heads}\n\n"
        f"正文开头：\n{doc['text'][:700]}\n\n"
        "请按规则抽取概念与关系。"
    )


def validate(doc: dict, data: dict | None) -> dict:
    """把模型输出收紧成可入库的结构。

    两道校验，都是防幻觉：
    - 概念必须在正文里真实出现（归一化后子串匹配）
    - 边的两端必须都在保留下来的概念里
    """
    if not isinstance(data, dict):
        return {"concepts": [], "edges": []}

    body = norm(doc["text"])
    concepts: list[dict] = []
    seen: set[str] = set()

    raw = data.get("concepts")
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not (2 <= len(name) <= 18):
            continue
        if norm(name) not in body:
            continue  # 文档里没有这个词，模型编的
        if norm(name) in seen:
            continue
        seen.add(norm(name))
        ctype = str(item.get("type", "概念"))
        concepts.append({"name": name, "type": ctype if ctype in VALID_TYPES else "概念"})

    keep = {norm(c["name"]): c["name"] for c in concepts}
    edges: list[dict] = []
    for item in (data.get("edges") if isinstance(data.get("edges"), list) else []):
        if not isinstance(item, dict):
            continue
        src = keep.get(norm(str(item.get("source", ""))))
        dst = keep.get(norm(str(item.get("target", ""))))
        rel = str(item.get("rel", ""))
        if not src or not dst or src == dst or rel not in VALID_RELS:
            continue
        edges.append({"source": src, "target": dst, "rel": rel})

    return {"concepts": concepts, "edges": edges}


async def extract(llm: LLMClient, doc: dict) -> dict:
    result = await llm.json_call(SYSTEM, build_prompt(doc), max_tokens=900, timeout=60)
    if result.degraded or not result.data:
        # 模型没给出合法 JSON 时再兜一次：直接从原文里抠
        return validate(doc, extract_json(result.text or ""))
    return validate(doc, result.data)


# 并发数。单条链路要 10 秒左右（免费额度下模型本身慢），
# 顺序跑 145 篇要半小时；4 并发能把总时间压到 8 分钟以内。
# 实测 4 并发时 145 篇里有 78 篇撞 429 直接失败（重试两次仍失败），
# 降到 2 并发后基本能跑完。免费额度的限流是按分钟计的，
# 并发越高越容易整批失败——失败的那些还得重跑，反而更慢。
CONCURRENCY = 2


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 篇（调试用）")
    ap.add_argument("--load-only", action="store_true", help="只灌库，不调模型")
    ap.add_argument("--reset", action="store_true", help="清空已有缓存重跑")
    args = ap.parse_args()

    if not settings.has_llm_key and not args.load_only:
        print("没有 LLM_API_KEY，只能 --load-only")
        return 1

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if args.reset:
        for f in CACHE_DIR.glob("*.json"):
            f.unlink()
        print("已清空缓存")

    docs = load_docs()
    if args.limit:
        docs = docs[: args.limit]
    print(f"文档 {len(docs)} 篇")

    llm: LLMClient | None = None
    if not args.load_only:
        llm = LLMClient()

    done = skipped = failed = 0
    sem = asyncio.Semaphore(CONCURRENCY)
    lock = asyncio.Lock()

    async def one(idx: int, doc: dict) -> None:
        nonlocal done, failed
        cache = CACHE_DIR / f"{doc['id']}.json"
        if cache.exists():
            return
        assert llm is not None
        async with sem:
            try:
                result = await extract(llm, doc)
            except LLMError as e:
                async with lock:
                    failed += 1
                    print(f"  [{idx}/{len(docs)}] {doc['filename'][:40]} 失败：{e}", flush=True)
                return
            result["doc_id"] = doc["id"]
            result["subject"] = doc["subject"]
            cache.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
            async with lock:
                done += 1
                print(
                    f"  [{idx}/{len(docs)}] {doc['filename'][:40]:<42}"
                    f" 概念 {len(result['concepts']):2d} 关系 {len(result['edges']):2d}",
                    flush=True,
                )

    try:
        todo = [d for d in docs if not (CACHE_DIR / f"{d['id']}.json").exists()]
        skipped = len(docs) - len(todo)
        print(f"待抽取 {len(todo)} 篇（已缓存 {skipped} 篇），并发 {CONCURRENCY}")
        await asyncio.gather(*(one(i, d) for i, d in enumerate(todo, 1)))
    finally:
        if llm is not None:
            await llm.close()

    print(f"\n抽取完成：新增 {done}，跳过 {skipped}，失败 {failed}")
    return load_into_db()


def load_into_db() -> int:
    """把缓存灌进 entity / relation。

    学科归属用**全库众数**而不是"第一次遇到的"：同一个概念可能被多个学科提到，
    出现最多的那个才代表它本质属于哪里。这和请求时图谱的判定规则保持一致——
    两处用不同规则的话，全库图和单题图会对不上，那比没有全库图更糟。
    """
    from sqlalchemy import text

    files = sorted(CACHE_DIR.glob("*.json"))
    if not files:
        print("没有可灌入的缓存")
        return 1

    concept_docs: dict[str, set[int]] = defaultdict(set)
    concept_subject: dict[str, Counter] = defaultdict(Counter)
    display: dict[str, str] = {}
    types: dict[str, Counter] = defaultdict(Counter)
    edge_weight: Counter = Counter()
    edge_rel: dict[tuple[str, str], str] = {}

    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        doc_id = data.get("doc_id")
        subject = data.get("subject")
        for c in data.get("concepts", []):
            key = norm(c["name"])
            display.setdefault(key, c["name"])
            concept_docs[key].add(doc_id)
            types[key][c["type"]] += 1
            if subject:
                concept_subject[key][subject] += 1
        for e in data.get("edges", []):
            a, b = norm(e["source"]), norm(e["target"])
            if a == b:
                continue
            pair = (a, b) if a < b else (b, a)
            edge_weight[pair] += 1
            edge_rel.setdefault(pair, e["rel"])

    subjects_map = _subject_domains()
    with SessionLocal() as db:
        # 概念 → entity（canonical_name 唯一，冲突时更新统计字段）
        #
        # 学科优先用**全库 chunk 统计**（和请求时图谱同一个函数），
        # 拿不到才退回"文档众数"。这个顺序很重要：
        # 请求时的图谱用 _resolve_subject 判学科，如果这里用别的规则，
        # 同一批概念在「单题图」和「全库图」里会落到不同域，
        # 跨域边的数量对不上，演示时被问"为什么两边不一样"就答不上来。
        from app.agent.nodes import _resolve_subject

        for key, name in display.items():
            subject = _resolve_subject(name)
            if not subject and concept_subject[key]:
                subject = concept_subject[key].most_common(1)[0][0]
            etype = types[key].most_common(1)[0][0] if types[key] else "概念"
            db.execute(
                text(
                    """
                    INSERT INTO entity (name, canonical_name, entity_type, subject, doc_freq)
                    VALUES (:name, :canon, :type, :subject, :freq)
                    ON CONFLICT (canonical_name) DO UPDATE SET
                        doc_freq = EXCLUDED.doc_freq,
                        entity_type = EXCLUDED.entity_type,
                        subject = COALESCE(EXCLUDED.subject, entity.subject)
                    """
                ),
                {
                    "name": name,
                    "canon": key,
                    "type": etype,
                    "subject": subject,
                    "freq": len(concept_docs[key]),
                },
            )
        db.commit()

        ids = {
            r[0]: r[1]
            for r in db.execute(text("SELECT canonical_name, id FROM entity"))
        }

        inserted = 0
        for (a, b), w in edge_weight.items():
            if a not in ids or b not in ids:
                continue
            rel = edge_rel.get((a, b), "使用")
            db.execute(
                text(
                    """
                    INSERT INTO relation (src_entity_id, dst_entity_id, rel_type, weight, inferred_by)
                    VALUES (:src, :dst, :rel, :w, 'extracted')
                    ON CONFLICT (src_entity_id, dst_entity_id, rel_type)
                    DO UPDATE SET weight = EXCLUDED.weight
                    """
                ),
                {"src": ids[a], "dst": ids[b], "rel": rel, "w": min(5.0, 1.0 + w * 0.5)},
            )
            inserted += 1
        db.commit()

        total_e = db.execute(text("SELECT count(*) FROM entity")).scalar()
        total_r = db.execute(text("SELECT count(*) FROM relation")).scalar()
        cross = db.execute(
            text(
                """
                SELECT count(*) FROM relation r
                JOIN entity a ON a.id = r.src_entity_id
                JOIN entity b ON b.id = r.dst_entity_id
                LEFT JOIN subject_taxonomy sa ON sa.code = a.subject
                LEFT JOIN subject_taxonomy sb ON sb.code = b.subject
                WHERE sa.domain IS NOT NULL AND sb.domain IS NOT NULL
                  AND sa.domain <> 'common' AND sb.domain <> 'common'
                  AND sa.domain <> sb.domain
                """
            )
        ).scalar()

    print(f"入库：实体 {total_e}，关系 {total_r}，其中跨域 {cross} 条")
    if cross == 0:
        print("⚠ 跨域边为 0——全库图的核心卖点没了，检查概念是否跨文档共享")
    _ = subjects_map
    return 0


def _subject_domains() -> dict[str, str]:
    from sqlalchemy import text

    with SessionLocal() as db:
        return {
            r[0]: r[1]
            for r in db.execute(text("SELECT code, domain FROM subject_taxonomy"))
        }


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
