"""知识库摄入：加载 → 清洗 → 切片 → （落库）。

先支持 --dry-run：不写数据库，只打印切片统计和抽样，用来验证切片质量。
切片是整条 RAG 链路里最难返工的一步——切坏了，后面 embedding 再好也救不回来。

用法：
    # 只看统计，不写库
    python scripts/ingest.py --dry-run

    # 只看某几个素材
    python scripts/ingest.py --dry-run --source jg-jvm

    # 抽样打印具体内容
    python scripts/ingest.py --dry-run --source jg-jvm --show 3

    # 真正入库
    python scripts/ingest.py --apply
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "services" / "python-agent"))

from app.rag.chunker import chunk_markdown  # noqa: E402
from app.rag.loader import load_dir, load_file  # noqa: E402


def load_manifest() -> dict[str, dict]:
    """source_id → manifest 条目。用 yaml 读，不在运行时热路径上。"""
    import yaml

    data = yaml.safe_load((ROOT / "sources.manifest.yaml").read_text(encoding="utf-8"))
    return {s["id"]: s for s in data["sources"]}


def delete_by_source(source_ids: set[str]) -> int:
    """删掉这些素材已有的文档（级联删 chunk 和 chunk_embedding）。

    为什么需要这个：document 的去重键是 content_hash。素材内容一变（比如调大了
    excerpt 上限），hash 就变了，直接重跑只会新增一份，旧的那份还在库里——
    结果同一个文档有两份不同长度的内容，检索时互相打架。
    """
    from sqlalchemy import text

    from app.infra.db import SessionLocal

    deleted = 0
    with SessionLocal() as db:
        for sid in source_ids:
            n = db.execute(
                text("DELETE FROM document WHERE filename LIKE :p"), {"p": f"{sid}/%"}
            ).rowcount
            deleted += n
        db.commit()
    return deleted


def apply_to_db(entries: list[tuple[str, object]]) -> tuple[int, int]:
    """写库。返回 (新增文档数, 跳过的重复文档数)。

    每个文档一个事务：一个文件解析失败不该让整批回滚。
    幂等靠 document.content_hash 的唯一索引——重复跑脚本不会产生重复数据。
    """
    from sqlalchemy import text

    from app.infra.db import SessionLocal

    inserted = skipped = 0

    with SessionLocal() as db:
        for source_id, doc in entries:
            exists = db.execute(
                text("SELECT id FROM document WHERE content_hash = :h"),
                {"h": doc.content_hash},
            ).scalar()

            if exists:
                skipped += 1
                continue

            meta = load_manifest().get(source_id, {})
            subject = meta.get("subject")

            try:
                doc_id = db.execute(
                    text(
                        """
                        INSERT INTO document
                            (filename, file_type, size_bytes, content_hash,
                             storage_path, status, chunk_count)
                        VALUES
                            (:fn, :ft, :sz, :h, :sp, 'chunking', 0)
                        RETURNING id
                        """
                    ),
                    {
                        "fn": f"{source_id}/{doc.filename}",
                        "ft": doc.file_type,
                        "sz": doc.size_bytes,
                        "h": doc.content_hash,
                        "sp": f"data/raw/{source_id}/{doc.filename}",
                    },
                ).scalar_one()

                groups = chunk_markdown(doc.text)
                n_chunks = 0

                for g in groups:
                    parent_id = db.execute(
                        text(
                            """
                            INSERT INTO chunk
                                (document_id, parent_chunk_id, level, content, token_count,
                                 heading_path, ordinal, subject, content_hash)
                            VALUES
                                (:did, NULL, 'parent', :c, :tk, :hp, :od, :sj, :ch)
                            RETURNING id
                            """
                        ),
                        {
                            "did": doc_id,
                            "c": g.parent.content,
                            "tk": g.parent.token_count,
                            "hp": g.parent.heading_path,
                            "od": g.parent.ordinal,
                            "sj": subject,
                            "ch": g.parent.content_hash,
                        },
                    ).scalar_one()
                    n_chunks += 1

                    for c in g.children:
                        db.execute(
                            text(
                                """
                                INSERT INTO chunk
                                    (document_id, parent_chunk_id, level, content, token_count,
                                     heading_path, ordinal, subject, content_hash)
                                VALUES
                                    (:did, :pid, 'child', :c, :tk, :hp, :od, :sj, :ch)
                                """
                            ),
                            {
                                "did": doc_id,
                                "pid": parent_id,
                                "c": c.content,
                                "tk": c.token_count,
                                "hp": c.heading_path,
                                "od": c.ordinal,
                                "sj": subject,
                                "ch": c.content_hash,
                            },
                        )
                        n_chunks += 1

                db.execute(
                    text(
                        "UPDATE document SET status='done', chunk_count=:n, updated_at=now() "
                        "WHERE id=:id"
                    ),
                    {"n": n_chunks, "id": doc_id},
                )
                db.commit()
                inserted += 1

            except Exception as e:  # noqa: BLE001
                db.rollback()
                print(f"  ✗ {source_id}/{doc.filename}: {type(e).__name__}: {e}")

    return inserted, skipped


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只统计，不写库")
    ap.add_argument("--apply", action="store_true", help="写入数据库")
    ap.add_argument("--source", action="append", help="只处理指定素材 id，可重复")
    ap.add_argument("--show", type=int, default=0, help="抽样打印 n 个 child chunk")
    ap.add_argument(
        "--replace",
        action="store_true",
        help="先删掉这些素材的旧文档再重新入库。素材内容变化（如调大 excerpt 上限）时必须加，"
        "否则会留下旧版本形成重复。",
    )
    args = ap.parse_args()

    if not args.dry_run and not args.apply:
        ap.error("必须指定 --dry-run 或 --apply")

    # 素材分两处：
    #   data/raw/<id>/  —— 从外部抓的（gitignore，版权原因不入库）
    #   notes/*.md      —— 项目自写的（必须进仓库，这是原创内容的主体）
    # 自写笔记的 source_id 约定为 own-<文件名>，与 manifest 的 local://notes/xxx.md 对应。
    raw_root = ROOT / "data" / "raw"
    notes_root = ROOT / "notes"

    units: list[tuple[Path, str]] = []
    if raw_root.exists():
        units += [(d, d.name) for d in sorted(raw_root.iterdir()) if d.is_dir()]
    if notes_root.exists():
        for f in sorted(notes_root.glob("*.md")):
            units.append((f, f"own-{f.stem}"))

    if args.source:
        units = [u for u in units if u[1] in set(args.source)]
    if not units:
        print("✗ 没有匹配的素材")
        return 1

    total_docs = 0
    total_parents = 0
    total_children = 0
    child_tokens: list[int] = []
    parent_tokens: list[int] = []
    code_chunks = 0
    per_source: Counter[str] = Counter()

    samples: list[tuple[str, str, str, int]] = []
    entries: list[tuple[str, object]] = []

    print(f"{'素材':<18}{'文档':>5}{'parent':>8}{'child':>7}{'平均tok':>9}{'最大tok':>9}")
    print("-" * 60)

    for unit, source_id in units:
        # 单个文件（notes/）和目录（data/raw/<id>/）两种形态
        docs = [load_file(unit, source_id)] if unit.is_file() else load_dir(unit, source_id)
        if not docs:
            continue

        src_parents = 0
        src_children = 0
        src_tokens: list[int] = []

        for doc in docs:
            entries.append((source_id, doc))
            groups = chunk_markdown(doc.text)
            src_parents += len(groups)
            for g in groups:
                parent_tokens.append(g.parent.token_count)
                for c in g.children:
                    src_children += 1
                    child_tokens.append(c.token_count)
                    src_tokens.append(c.token_count)
                    if "```" in c.content:
                        code_chunks += 1
                    if len(samples) < args.show * 3:
                        samples.append((source_id, doc.filename, c.heading_path, c.token_count))

        total_docs += len(docs)
        total_parents += src_parents
        total_children += src_children
        per_source[source_id] = src_children

        avg = sum(src_tokens) / len(src_tokens) if src_tokens else 0
        mx = max(src_tokens) if src_tokens else 0
        print(f"{source_id:<18}{len(docs):>5}{src_parents:>8}{src_children:>7}{avg:>9.0f}{mx:>9}")

    print("-" * 60)
    print(
        f"{'合计':<18}{total_docs:>5}{total_parents:>8}{total_children:>7}"
        f"{sum(child_tokens)/max(1,len(child_tokens)):>9.0f}{max(child_tokens) if child_tokens else 0:>9}"
    )

    if child_tokens:
        ordered = sorted(child_tokens)
        p50 = ordered[len(ordered) // 2]
        p95 = ordered[int(len(ordered) * 0.95)]
        print(f"\nchild token 分布：p50={p50}  p95={p95}  max={ordered[-1]}")
        print(f"含代码块的 child：{code_chunks}（{code_chunks/len(child_tokens)*100:.1f}%）")
        over = sum(1 for t in child_tokens if t > 256)
        print(f"超出 256 token 预算的 child：{over}（{over/len(child_tokens)*100:.1f}%）")

    if args.show:
        print(f"\n{'='*60}\n抽样（前 {args.show} 个）\n{'='*60}")
        for src, fn, hp, tk in samples[: args.show]:
            print(f"\n[{src}] {fn}  ({tk} tok)")
            print(f"  heading: {hp}")

    if args.apply:
        if args.replace:
            sids = {sid for sid, _ in entries}
            n = delete_by_source(sids)
            print(f"\n已删除旧文档 {n} 个（{', '.join(sorted(sids))}）")

        print(f"\n{'='*60}\n开始落库：{len(entries)} 个文档\n{'='*60}")
        inserted, skipped = apply_to_db(entries)
        print(f"\n✓ 新增 {inserted} 个文档，跳过 {skipped} 个已存在（content_hash 相同）")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
