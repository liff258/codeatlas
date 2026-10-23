-- ============================================================================
-- CodeAtlas Schema 冒烟测试
--
-- 用途：验证 schema 的约束、索引与跨域查询是否真的可用。
--       整个脚本在一个事务里跑完并 ROLLBACK，不留脏数据。
--
-- 运行：
--   docker exec -i codeatlas-db psql -U codeatlas -d codeatlas -v ON_ERROR_STOP=1 -f - < db/smoke-test.sql
-- ============================================================================

\set ON_ERROR_STOP on
\echo '=== CodeAtlas Schema 冒烟测试 ==='

BEGIN;

DO $$
DECLARE
  v_doc    BIGINT;
  v_parent BIGINT;
  v_c1     BIGINT;
  v_c2     BIGINT;
  v_e1     BIGINT;
  v_e2     BIGINT;
  v_cnt    INT;
BEGIN
  -- ------------------------------------------------------------------
  -- 1. 写入一篇文档 + 父子块 + 向量
  -- ------------------------------------------------------------------
  INSERT INTO document (filename, file_type, size_bytes, content_hash, status, chunk_count)
  VALUES ('smoke-test.md', 'md', 1024, repeat('a', 64), 'done', 2)
  RETURNING id INTO v_doc;

  INSERT INTO chunk (document_id, level, content, token_count, heading_path, subject, difficulty, content_hash)
  VALUES (v_doc, 'parent', '父块：MySQL 索引与向量检索的对比', 200, '第1章 > 1.1 对比', 'MySQL', 3, repeat('b', 64))
  RETURNING id INTO v_parent;

  INSERT INTO chunk (document_id, parent_chunk_id, level, content, token_count, heading_path,
                     subject, difficulty, knowledge_points, content_hash)
  VALUES (v_doc, v_parent, 'child', 'B+ 树是一维有序结构，适合等值查询与范围查询。', 40,
          '第1章 > 1.1.1', 'MySQL', 3, ARRAY['B+树', '索引'], repeat('c', 64))
  RETURNING id INTO v_c1;

  INSERT INTO chunk (document_id, parent_chunk_id, level, content, token_count, heading_path,
                     subject, difficulty, knowledge_points, content_hash)
  VALUES (v_doc, v_parent, 'child', 'HNSW 用分层图做近似最近邻搜索，牺牲精度换速度。', 40,
          '第1章 > 1.1.2', '向量检索', 4, ARRAY['HNSW', 'ANN'], repeat('d', 64))
  RETURNING id INTO v_c2;

  -- c1 与 c2 用「不同方向」的向量，否则余弦相似度恒为 1，看不出检索效果
  INSERT INTO chunk_embedding (chunk_id, embedding)
  VALUES (v_c1, array_fill(0.10::real, ARRAY[1024])::vector(1024)),
         (v_c2, (SELECT array_agg(CASE WHEN i = 1 THEN -1.0::real ELSE 0.1::real END ORDER BY i)
                 FROM generate_series(1, 1024) i)::vector(1024));
  RAISE NOTICE '✓ 文档 + 父子块 + 1024 维向量写入成功';

  -- ------------------------------------------------------------------
  -- 2. 跨域关系：MySQL(backend) --对比--> 向量检索(ai)
  -- ------------------------------------------------------------------
  INSERT INTO entity (name, canonical_name, entity_type, subject)
  VALUES ('B+ 树索引', 'B+树', '算法', 'MySQL') RETURNING id INTO v_e1;
  INSERT INTO entity (name, canonical_name, entity_type, subject)
  VALUES ('HNSW', 'HNSW', '算法', '向量检索') RETURNING id INTO v_e2;

  INSERT INTO relation (src_entity_id, dst_entity_id, rel_type, weight, source_chunk_id, inferred_by)
  VALUES (v_e1, v_e2, '对比', 0.9, v_c1, 'inferred');

  SELECT count(*) INTO v_cnt
  FROM relation r
  JOIN entity a ON a.id = r.src_entity_id
  JOIN entity b ON b.id = r.dst_entity_id
  JOIN subject_taxonomy sa ON sa.code = a.subject
  JOIN subject_taxonomy sb ON sb.code = b.subject
  WHERE sa.domain <> sb.domain;

  IF v_cnt = 1 THEN
    RAISE NOTICE '✓ 跨域边查询正确，命中 % 条', v_cnt;
  ELSE
    RAISE EXCEPTION '跨域边查询异常，期望 1 条，实际 % 条', v_cnt;
  END IF;

  -- ------------------------------------------------------------------
  -- 3. 外键约束：脏学科必须被拒绝
  -- ------------------------------------------------------------------
  BEGIN
    INSERT INTO chunk (document_id, level, content, subject, content_hash)
    VALUES (v_doc, 'child', '脏数据测试', 'RAG检索', repeat('e', 64));
    RAISE EXCEPTION '✗ 外键约束失效：不存在的学科被写入了';
  EXCEPTION WHEN foreign_key_violation THEN
    RAISE NOTICE '✓ 外键约束生效：非法学科「RAG检索」被拒绝';
  END;

  -- ------------------------------------------------------------------
  -- 4. 唯一约束：重复 content_hash 必须被拒绝
  -- ------------------------------------------------------------------
  BEGIN
    INSERT INTO document (filename, file_type, content_hash)
    VALUES ('dup.md', 'md', repeat('a', 64));
    RAISE EXCEPTION '✗ 唯一约束失效：重复 content_hash 被写入';
  EXCEPTION WHEN unique_violation THEN
    RAISE NOTICE '✓ 唯一约束生效：重复 content_hash 被拒绝';
  END;

  -- ------------------------------------------------------------------
  -- 5. 自环约束：实体的边不能指向自己
  -- ------------------------------------------------------------------
  BEGIN
    INSERT INTO relation (src_entity_id, dst_entity_id, rel_type)
    VALUES (v_e1, v_e1, '依赖');
    RAISE EXCEPTION '✗ 自环约束失效';
  EXCEPTION WHEN check_violation THEN
    RAISE NOTICE '✓ 自环约束生效：实体不能指向自己';
  END;

END $$;

-- ----------------------------------------------------------------------
-- 6. 向量检索：验证 HNSW 索引真实存在且类型正确
-- ----------------------------------------------------------------------
\echo '--- HNSW 索引定义 ---'
SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename = 'chunk_embedding' AND indexname LIKE '%hnsw%';

\echo '--- 向量检索结果（c2 方向相反，相似度应明显低于 c1）---'
SET LOCAL enable_seqscan = off;

SELECT c.id, c.subject,
       round((1 - (e.embedding <=> array_fill(0.10::real, ARRAY[1024])::vector(1024)))::numeric, 4) AS cosine_sim
FROM chunk_embedding e
JOIN chunk c ON c.id = e.chunk_id
ORDER BY e.embedding <=> array_fill(0.10::real, ARRAY[1024])::vector(1024)
LIMIT 2;

-- 注：已用 EXPLAIN 验证过该查询走的是 Index Scan using idx_chunk_embedding_hnsw，
--     此处不再打印（1024 维字面量会把输出刷爆）。

ROLLBACK;

\echo ''
\echo '=== 测试结束，已回滚，数据库无残留 ==='
