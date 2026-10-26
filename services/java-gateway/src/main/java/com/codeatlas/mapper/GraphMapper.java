package com.codeatlas.mapper;

import com.codeatlas.dto.GraphEdgeView;
import com.codeatlas.dto.GraphNodeView;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

/**
 * 全库知识图谱查询。
 *
 * 度数（degree）在 SQL 里算而不是查出来再在 Java 里数：
 * 一个概念可能挂在几百条边上，把边全捞回内存再聚合是浪费。
 * CTE 里的 deg/d 两个临时表就是干这个的。
 */
@Mapper
public interface GraphMapper {

    /** 按度数取前 N 个节点。度数相同按 doc_freq 排，再相同按 id 保证顺序稳定 */
    @Select("""
            WITH deg AS (
                SELECT src_entity_id AS id, count(*) AS n FROM relation GROUP BY src_entity_id
                UNION ALL
                SELECT dst_entity_id AS id, count(*) AS n FROM relation GROUP BY dst_entity_id
            ), d AS (
                SELECT id, sum(n) AS weight FROM deg GROUP BY id
            )
            SELECT e.canonical_name AS id,
                   e.name          AS label,
                   e.entity_type   AS type,
                   e.subject       AS subject,
                   COALESCE(st.domain, 'common') AS domain,
                   COALESCE(d.weight, 0)         AS weight
            FROM entity e
            LEFT JOIN d  ON d.id = e.id
            LEFT JOIN subject_taxonomy st ON st.code = e.subject
            WHERE (#{subject}::text IS NULL OR e.subject = #{subject}::text)
            ORDER BY weight DESC, e.doc_freq DESC, e.id
            LIMIT #{limit}
            """)
    List<GraphNodeView> topNodes(@Param("limit") int limit, @Param("subject") String subject);

    /** 只保留两端都在前 N 个节点里的边，否则会返回一堆指向图外的悬空边 */
    @Select("""
            WITH deg AS (
                SELECT src_entity_id AS id, count(*) AS n FROM relation GROUP BY src_entity_id
                UNION ALL
                SELECT dst_entity_id AS id, count(*) AS n FROM relation GROUP BY dst_entity_id
            ), d AS (
                SELECT id, sum(n) AS weight FROM deg GROUP BY id
            ), top AS (
                SELECT e.id
                FROM entity e
                LEFT JOIN d ON d.id = e.id
                WHERE (#{subject}::text IS NULL OR e.subject = #{subject}::text)
                ORDER BY COALESCE(d.weight, 0) DESC, e.doc_freq DESC, e.id
                LIMIT #{limit}
            )
            SELECT a.canonical_name AS source,
                   b.canonical_name AS target,
                   r.rel_type       AS rel,
                   r.weight         AS weight,
                   COALESCE(sa.domain, 'common') AS src_domain,
                   COALESCE(sb.domain, 'common') AS dst_domain
            FROM relation r
            JOIN top ta ON ta.id = r.src_entity_id
            JOIN top tb ON tb.id = r.dst_entity_id
            JOIN entity a ON a.id = r.src_entity_id
            JOIN entity b ON b.id = r.dst_entity_id
            LEFT JOIN subject_taxonomy sa ON sa.code = a.subject
            LEFT JOIN subject_taxonomy sb ON sb.code = b.subject
            ORDER BY r.weight DESC
            """)
    List<GraphEdgeView> edgesAmongTop(@Param("limit") int limit, @Param("subject") String subject);

    /**
     * 从某个概念出发 BFS 若干跳，返回涉及的实体 id。
     *
     * 用 UNION（不是 UNION ALL）：递归 CTE 里 UNION 会去重，
     * 这是防止环导致无限递归的关键——图里 A→B→A 这种环很常见。
     */
    @Select("""
            WITH RECURSIVE walk AS (
                SELECT e.id, 0 AS depth
                FROM entity e
                WHERE e.canonical_name = lower(#{key}::text) OR lower(e.name) = lower(#{key}::text)
                UNION
                SELECT CASE WHEN r.src_entity_id = w.id THEN r.dst_entity_id ELSE r.src_entity_id END,
                       w.depth + 1
                FROM walk w
                JOIN relation r ON r.src_entity_id = w.id OR r.dst_entity_id = w.id
                WHERE w.depth < #{depth}
            )
            SELECT DISTINCT id FROM walk
            """)
    List<Long> neighborIds(@Param("key") String key, @Param("depth") int depth);

    @Select("""
            <script>
            SELECT e.canonical_name AS id,
                   e.name          AS label,
                   e.entity_type   AS type,
                   e.subject       AS subject,
                   COALESCE(st.domain, 'common') AS domain,
                   COALESCE(d.weight, 0)         AS weight
            FROM entity e
            LEFT JOIN subject_taxonomy st ON st.code = e.subject
            LEFT JOIN (
                SELECT id, count(*) AS weight FROM (
                    SELECT src_entity_id AS id FROM relation
                    UNION ALL
                    SELECT dst_entity_id AS id FROM relation
                ) x GROUP BY id
            ) d ON d.id = e.id
            WHERE e.id IN
            <foreach collection="ids" item="i" open="(" separator="," close=")">#{i}</foreach>
            </script>
            """)
    List<GraphNodeView> nodesByIds(@Param("ids") List<Long> ids);

    @Select("""
            <script>
            SELECT a.canonical_name AS source,
                   b.canonical_name AS target,
                   r.rel_type       AS rel,
                   r.weight         AS weight,
                   COALESCE(sa.domain, 'common') AS src_domain,
                   COALESCE(sb.domain, 'common') AS dst_domain
            FROM relation r
            JOIN entity a ON a.id = r.src_entity_id
            JOIN entity b ON b.id = r.dst_entity_id
            LEFT JOIN subject_taxonomy sa ON sa.code = a.subject
            LEFT JOIN subject_taxonomy sb ON sb.code = b.subject
            WHERE r.src_entity_id IN
                  <foreach collection="ids" item="i" open="(" separator="," close=")">#{i}</foreach>
              AND r.dst_entity_id IN
                  <foreach collection="ids" item="i" open="(" separator="," close=")">#{i}</foreach>
            ORDER BY r.weight DESC
            </script>
            """)
    List<GraphEdgeView> edgesByIds(@Param("ids") List<Long> ids);

    @Select("SELECT count(*) FROM entity")
    long countEntities();
}
