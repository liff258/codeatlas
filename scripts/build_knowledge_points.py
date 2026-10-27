#!/usr/bin/env python
"""从 chunk 构建知识点表 knowledge_point。

## 为什么要这张表

现在知识点只能靠 `heading_path` 现算，但有三件事现算做不到：

1. **稳定 id**：前端要 `#/kp/kp_xxxxxxxx` 这样的 URL，现算的 hash 没法反查
2. **跨 chunk 的完整答案**：一道题的内容常常切成 2~3 个 child chunk，
   必须按 heading_path 聚合、按 ordinal 排序拼接
3. **题库筛选**：`is_question` 要预先算好并建索引，不能每次查询都跑正则

## 为什么不能用 parent chunk 当答案

parent 是 1024 token 的滑窗，**787/903 个 parent 跨多个 heading_path**。
拿它当答案，会把上一道题的尾巴拼进下一道题——这是这个脚本最需要防的错误。
所以只聚合 child，并且按 heading_path 严格分组。

## 用法

    python scripts/build_knowledge_points.py            # 重建
    python scripts/build_knowledge_points.py --dry-run  # 只看统计不写库
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "services" / "python-agent"))

from sqlalchemy import text  # noqa: E402

from app.infra.db import SessionLocal  # noqa: E402

# 太短的丢弃。实测 670 个 child <80 字是「纯标题空块」（如 `## 泛型` 只有 5 字），
# 合并后仍然 <100 字的，基本是目录项而不是内容。
MIN_CHARS = 100

# 问句判定。宁可多判（把陈述句当题），也别漏——漏了题库就少题，
# 多判的题点开也有答案，不影响使用。
QUESTION_MARKS = ("？", "?")
QUESTION_WORDS = (
    "什么", "如何", "为什么", "怎么", "怎样", "区别", "是否", "哪些",
    "吗", "呢", "了解", "说一下", "讲讲", "谈谈", "有没有", "能不能",
)

# 标题清洗：去掉 ⭐️/emoji/前导编号
_EMOJI_PREFIX = re.compile(r"^[^\w\u4e00-\u9fff]+", re.UNICODE)
_NUMBER_PREFIX = re.compile(r"^\s*(?:\d+(?:\.\d+)*[.、)\s]+|[一二三四五六七八九十]+[、.)]\s*)")
_MD_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+")


def clean_title(seg: str) -> str:
    s = (seg or "").strip()
    s = _MD_HEADING.sub("", s)
    s = _EMOJI_PREFIX.sub("", s)
    s = _NUMBER_PREFIX.sub("", s)
    # 行内代码和加粗符号：标题里常见 `jmap`、**重点** 这种写法，
    # 直接显示成「`jmap`:生成堆转储快照」很丑
    s = s.replace("`", "").replace("**", "")
    return s.strip(" \t：:，,。.；;！!、")


def norm(s: str) -> str:
    """归一化用于匹配：去所有空白、转小写。"""
    return re.sub(r"\s+", "", s).lower()


def is_question(title: str) -> bool:
    if any(m in title for m in QUESTION_MARKS):
        return True
    return any(w in title for w in QUESTION_WORDS)


def strip_leading_heading(content: str, title: str) -> str:
    """去掉正文开头重复的标题行。

    原文常把标题又写一遍（`### 多态\\n\\n多态是...`），拼进答案里会显得啰嗦，
    而且列表页的 preview 会变成一串重复的标题。
    """
    lines = content.splitlines()
    out: list[str] = []
    dropped = False
    for line in lines:
        if not dropped:
            stripped = line.strip()
            if not stripped:
                continue
            # 开头的 markdown 标题，或与 title 完全一致的短行
            if _MD_HEADING.match(line) or (len(stripped) <= 40 and clean_title(stripped) == title):
                continue
            dropped = True
        out.append(line)
    return "\n".join(out).strip()


def kp_id(subject: str | None, doc_id: int, heading_path: str) -> str:
    """稳定 id：学科 + 文档 + 标题路径。

    用 12 位 hex（48 bit）：2632 条数据下碰撞概率约十万分之一，
    而 10 位（40 bit）约 0.3%——不值得为省 2 个字符冒这个险。
    """
    raw = f"{subject or ''}|{doc_id}|{heading_path}"
    return "kp_" + hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]


def load_rows() -> tuple[list[dict], dict[int, str]]:
    with SessionLocal() as db:
        docs = {
            r[0]: r[1]
            for r in db.execute(text("SELECT id, filename FROM document")).all()
        }
        rows = db.execute(
            text(
                """
                SELECT c.id, c.document_id, c.heading_path, c.ordinal, c.content, c.subject
                FROM chunk c
                WHERE c.level = 'child'
                ORDER BY c.document_id, c.ordinal, c.id
                """
            )
        ).mappings().all()
    return [dict(r) for r in rows], docs


def load_entities() -> list[tuple[str, str]]:
    """返回 [(归一化名, 显示名)]，按名字长度倒序——长名优先匹配。"""
    with SessionLocal() as db:
        rows = db.execute(text("SELECT name FROM entity")).all()
    items = [(norm(r[0]), r[0]) for r in rows if r[0] and len(r[0]) >= 2]
    return sorted(items, key=lambda x: -len(x[0]))


def build(rows: list[dict], docs: dict[int, str], entities: list[tuple[str, str]]) -> list[dict]:
    # 按 (文档, 标题路径) 严格分组 —— 这是防串题的关键
    groups: dict[tuple[int, str], list[dict]] = defaultdict(list)
    for r in rows:
        hp = (r["heading_path"] or "").strip()
        if not hp:
            # heading_path 为 NULL 的 522 条：用文档名兜底，单独成一组
            hp = f"《{docs.get(r['document_id'], '未命名')}》"
        groups[(r["document_id"], hp)].append(r)

    kps: list[dict] = []
    for (doc_id, hp), items in groups.items():
        items.sort(key=lambda x: (x["ordinal"] or 0, x["id"]))
        parts = hp.split(">")
        title = clean_title(parts[-1])
        if not title:
            title = clean_title(parts[0]) or "（无标题）"
        breadcrumb = " > ".join(clean_title(p) for p in parts[:-1] if clean_title(p)) or None

        body = "\n\n".join(strip_leading_heading(it["content"] or "", title) for it in items).strip()
        if len(body) < MIN_CHARS:
            continue

        subject = next((it["subject"] for it in items if it["subject"]), None)
        haystack = norm(body)
        matched = [name for key, name in entities if key in haystack]

        # 实体排序：标题里出现的优先，其次名字长的优先。
        #
        # 为什么需要这个：抽出来的 727 个实体里混着 String / Exception / Java 这类泛词，
        # 它们在正文里确实出现了，但对「这个知识点涉及哪些概念」毫无信息量。
        # doc_freq 分不开它们——实测「线程池」的 doc_freq 是 5，「Java」也是 5。
        # 而名字长度是个不错的代理：ArrayBlockingQueue 比 String 具体得多。
        head = norm(title + (breadcrumb or ""))
        matched.sort(key=lambda n: (0 if norm(n) in head else 1, -len(n)))
        ents = matched[:8]

        kps.append(
            {
                "id": kp_id(subject, doc_id, hp),
                "subject": subject,
                "document_id": doc_id,
                "heading_path": hp,
                "title": title[:200],
                "breadcrumb": breadcrumb[:400] if breadcrumb else None,
                "answer": body,
                "chunk_ids": [it["id"] for it in items],
                "chunk_count": len(items),
                "char_count": len(body),
                "is_question": is_question(title),
                "entity_names": ents,
                "ordinal_start": min((it["ordinal"] or 0) for it in items),
                # 仅供自检使用，写库前会 pop 掉
                "_src_key": (doc_id, hp),
            }
        )
    return kps


def self_check(kps: list[dict], rows: list[dict], docs: dict[int, str]) -> None:
    """自检。不通过就非 0 退出——宁可失败，也不能把串了题的答案写进库。

    **只做结构性校验，不做文本猜测。**

    第一版用的是「正文里出现别的知识点标题两次以上就算串题」，结果全是误报：
    「StampedLock 的性能为什么更好？」这篇正文里当然会两次提到 StampedLock，
    而 StampedLock 本身也是另一个知识点的标题。文本启发式判断不了
    「引用」和「串题」的区别。

    真正的串题风险来自数据源：如果用 parent chunk 当答案，
    1024 token 滑窗会把相邻章节一起吞进来（787/903 个 parent 跨多个 heading_path）。
    而本脚本只聚合 child，所以只要验证「同一条知识点的所有 chunk 属于同一个
    heading_path」，就证明没有串。
    """
    problems: list[str] = []

    # 1) 结构校验：chunk 的 heading_path 必须和知识点一致
    src = {}
    for r in rows:
        hp = (r["heading_path"] or "").strip() or f"《{docs.get(r['document_id'], '未命名')}》"
        src[r["id"]] = (r["document_id"], hp)

    for kp in kps:
        key = kp["_src_key"]
        for cid in kp["chunk_ids"]:
            if src.get(cid) != key:
                problems.append(f"串题：{kp['id']} 混入了来自 {src.get(cid)} 的 chunk {cid}")
                break

    # 2) id 不能重复
    ids = [k["id"] for k in kps]
    if len(ids) != len(set(ids)):
        problems.append(f"id 冲突 {len(ids) - len(set(ids))} 条")

    # 3) 规模合理性
    if not (2000 <= len(kps) <= 3200):
        problems.append(f"知识点数量异常：{len(kps)}（预期 2400~2900）")
    q = sum(1 for k in kps if k["is_question"])
    if not (500 <= q <= 900):
        problems.append(f"题目数量异常：{q}（预期 600~800）")

    # 4) 太短的不该出现在结果里
    short = [k for k in kps if k["char_count"] < MIN_CHARS]
    if short:
        problems.append(f"有 {len(short)} 条短于 {MIN_CHARS} 字")

    if problems:
        print("\n✗ 自检未通过：")
        for p in problems[:10]:
            print("  -", p)
        raise SystemExit(1)


def report(kps: list[dict]) -> None:
    q = [k for k in kps if k["is_question"]]
    print(f"\n知识点 {len(kps)} 条，其中面试题 {len(q)} 条")
    by_subject: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for k in kps:
        s = k["subject"] or "(无)"
        by_subject[s][0] += 1
        if k["is_question"]:
            by_subject[s][1] += 1
    print(f"\n{'学科':<12}{'知识点':>8}{'题目':>8}")
    for s, (n, qn) in sorted(by_subject.items(), key=lambda kv: -kv[1][0]):
        print(f"{s:<12}{n:>8}{qn:>8}")

    print("\n--- 抽样（人工扫一眼有没有串题）---")
    step = max(1, len(kps) // 3)
    for kp in kps[::step][:3]:
        body = " ".join(kp["answer"].split())[:80]
        flag = "题" if kp["is_question"] else "  "
        print(f"[{flag}] {kp['title'][:40]}  ({kp['char_count']}字/{kp['chunk_count']}块)")
        print(f"      {body}")


def write(kps: list[dict]) -> None:
    with SessionLocal() as db:
        db.execute(text("TRUNCATE knowledge_point"))
        for kp in kps:
            db.execute(
                text(
                    """
                    INSERT INTO knowledge_point (
                        id, subject, document_id, heading_path, title, breadcrumb,
                        answer, chunk_ids, chunk_count, char_count, is_question,
                        entity_names, ordinal_start
                    ) VALUES (
                        :id, :subject, :document_id, :heading_path, :title, :breadcrumb,
                        :answer, :chunk_ids, :chunk_count, :char_count, :is_question,
                        :entity_names, :ordinal_start
                    )
                    """
                ),
                kp,
            )
        db.commit()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只统计不写库")
    args = ap.parse_args()

    print("读取 chunk ...")
    rows, docs = load_rows()
    print(f"  child chunk {len(rows)} 条，文档 {len(docs)} 篇")

    print("读取实体 ...")
    entities = load_entities()
    print(f"  实体 {len(entities)} 个")

    print("聚合 ...")
    kps = build(rows, docs, entities)
    self_check(kps, rows, docs)
    print("✓ 自检通过")
    report(kps)

    if args.dry_run:
        print("\n(dry-run，未写库)")
        return 0

    for kp in kps:
        kp.pop("_src_key", None)
    write(kps)
    print(f"\n✓ 已写入 knowledge_point：{len(kps)} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
