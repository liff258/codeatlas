"""切片与分词的单元测试。

这两块坏掉的方式都很隐蔽：
- 切片坏了 → embedding 和检索都不会报错，只是答非所问
- 分词坏了 → BM25 分数还在，只是召回的完全不相干

所以必须有断言守住，而不是靠肉眼看输出。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.rag.bm25_index import tokenize  # noqa: E402
from app.rag.chunker import chunk_markdown  # noqa: E402
from app.rag.text import count_tokens, split_sentences  # noqa: E402


# ---------------------------------------------------------------- 分词


def test_tokenize_keeps_tech_terms_whole():
    """ConcurrentHashMap 不能被拆成 Concurrent/Hash/Map——拆了区分度就没了。"""
    toks = tokenize("ConcurrentHashMap 的 size 方法")
    assert "concurrenthashmap" in toks
    assert "size" in toks


def test_tokenize_distinguishes_btree_variants():
    """B+树 和 B树 必须能分开——这是 MySQL 索引最经典的一组对比。"""
    toks = tokenize("B+树和B树的区别")
    assert "b+树" in toks
    assert "b树" in toks
    assert "区别" in toks


def test_tokenize_handles_space_between_tech_and_cjk():
    """原文常写成「B+ 树」（带空格），必须归一成 b+树 才能整体匹配。"""
    toks = tokenize("MySQL 为什么用 B+ 树")
    assert "b+树" in toks


def test_tokenize_domain_dict_fixes_jieba():
    """jieba 默认会把「红黑树」切错，靠 dict.txt 兜住。"""
    toks = tokenize("为什么比红黑树快")
    assert "红黑树" in toks


def test_tokenize_keeps_symbols():
    toks = tokenize("C++ 和 C# 以及 .NET")
    assert "c++" in toks
    assert "c#" in toks


# ---------------------------------------------------------------- 切片


def _doc() -> str:
    return """# 标题

## 第一节

第一段内容，讲了一些基础概念。这里凑一点长度，让 token 数不至于太小。

第二段内容，继续展开。

### 1.1 子节

子节里的内容，描述具体细节。

## 第二节

第二节的内容。
"""


def test_chunks_have_parent_and_children():
    groups = chunk_markdown(_doc())
    assert groups, "至少产出一个 parent"
    for g in groups:
        assert g.parent.level == "parent"
        assert g.children, "每个 parent 必须有 child"
        for c in g.children:
            assert c.level == "child"


def test_heading_path_is_built():
    groups = chunk_markdown(_doc())
    paths = [c.heading_path for g in groups for c in g.children]
    assert any("第一节" in p for p in paths)
    assert any("第二节" in p for p in paths)
    # 子节要能体现出层级
    assert any("1.1" in p for p in paths)


def test_code_block_is_never_split():
    """代码块必须整块保留。切开的代码检索到了也读不懂。"""
    body = "```java\n" + "\n".join(f"int x{i} = {i};" for i in range(80)) + "\n```"
    doc = f"# 代码\n\n{body}\n"
    groups = chunk_markdown(doc)
    children = [c for g in groups for c in g.children]

    # 每一段都必须是完整的围栏块：以 ``` 开头，以 ``` 结尾
    code_children = [c for c in children if "```" in c.content]
    assert code_children, "代码块应该被保留"
    for c in code_children:
        s = c.content.strip()
        assert s.startswith("```"), f"代码块开头被破坏：{s[:40]}"
        assert s.endswith("```"), f"代码块结尾被破坏：{s[-40:]}"


def test_oversized_code_block_gets_split_with_fences():
    """超长代码块要切开，但每段都得补回围栏，保证单独看也是合法代码。"""
    lines = []
    for i in range(300):
        lines.append(f"public void method{i}() {{ int a = {i}; }}")
        if i % 20 == 0:
            lines.append("")  # 空行分段
    body = "```java\n" + "\n".join(lines) + "\n```"

    groups = chunk_markdown(f"# 大文件\n\n{body}\n")
    children = [c for g in groups for c in g.children if "```" in c.content]

    assert len(children) > 1, "超长代码块应该被切成多段"
    for c in children:
        s = c.content.strip()
        assert s.startswith("```java")
        assert s.endswith("```")


def test_table_keeps_header_when_split():
    """表格切开后每段都要重复表头，否则数据行单独看毫无意义。"""
    rows = "\n".join(f"| key{i} | 值{i} | 说明{i} |" for i in range(120))
    table = f"| 名称 | 值 | 说明 |\n| --- | --- | --- |\n{rows}"
    groups = chunk_markdown(f"# 表\n\n{table}\n")
    children = [c for g in groups for c in g.children if c.content.strip().startswith("|")]

    assert len(children) > 1, "超长表格应该被切开"
    for c in children:
        assert "| 名称 | 值 | 说明 |" in c.content, "每段都要带表头"


def test_child_token_budget_respected():
    """普通段落切完，绝大多数 child 应该在预算内。"""
    para = "这是一段测试文本，用来验证切片长度控制。" * 60
    doc = "# 长文\n\n" + "\n\n".join([para] * 6)
    groups = chunk_markdown(doc)
    children = [c for g in groups for c in g.children]

    assert children
    within = sum(1 for c in children if c.token_count <= 256)
    assert within / len(children) > 0.9, f"超预算比例过高：{len(children)-within}/{len(children)}"


def test_parent_covers_all_children():
    """parent 的内容必须覆盖它所有 child，否则生成阶段会缺上下文。"""
    groups = chunk_markdown(_doc())
    for g in groups:
        for c in g.children:
            # child 允许带 markdown 标记差异，用前 20 个非空白字符做锚点
            anchor = "".join(c.content.split())[:20]
            assert anchor in "".join(g.parent.content.split()), "child 不在 parent 里"


# ---------------------------------------------------------------- 文本工具


def test_count_tokens_monotonic():
    assert count_tokens("") == 0
    assert count_tokens("短") < count_tokens("长" * 100)


def test_count_tokens_mixed_language():
    assert count_tokens("HashMap 扩容") > 0
    assert count_tokens("hello world") > 0


def test_split_sentences_keeps_punctuation():
    sents = split_sentences("第一句。第二句！第三句？")
    assert len(sents) == 3
    assert sents[0].endswith("。")
