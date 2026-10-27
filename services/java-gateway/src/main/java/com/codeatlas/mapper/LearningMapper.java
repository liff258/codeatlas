package com.codeatlas.mapper;

import com.codeatlas.dto.EntityDetail;
import com.codeatlas.dto.GraphEdgeView;
import com.codeatlas.dto.GraphNodeView;
import com.codeatlas.dto.KnowledgePointBrief;
import com.codeatlas.dto.KnowledgePointRaw;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

/**
 * 知识平台查询：知识点、实体。
 *
 * 分页用 LIMIT/OFFSET + 单独一条 count，不用窗口函数——
 * count(*) OVER() 会让每行都带一个 total，还得在 Service 里剥出来，
 * 反而更绕。2167 行数据，两次查询的代价可以忽略。
 *
 * 数组字段（chunk_ids / entity_names）用 array_to_string 拼成字符串再在 Service 里切：
 * MyBatis 没有内置的数组映射，为一个只读字段引 TypeHandler 不划算。
 */
@Mapper
public interface LearningMapper {

    @Select("""
            <script>
            SELECT count(*)
            FROM knowledge_point kp
            WHERE (#{subject}::text IS NULL OR kp.subject = #{subject}::text)
              AND (#{type}::text IS NULL OR kp.is_question = (#{type}::text = 'question'))
              AND (#{q}::text IS NULL OR kp.title ILIKE '%' || #{q}::text || '%')
            </script>
            """)
    long countKnowledgePoints(
            @Param("subject") String subject,
            @Param("type") String type,
            @Param("q") String q
    );

    /**
     * 列表。排序先按 is_question 降序（题库优先），再按字数降序——
     * 长内容通常是主干章节，短的多是零碎小节，先看主干更有价值。
     */
    @Select("""
            SELECT kp.id, kp.title, kp.breadcrumb, kp.subject, kp.is_question,
                   kp.chunk_count, kp.char_count,
                   left(kp.answer, 140) AS preview,
                   d.filename AS doc_name
            FROM knowledge_point kp
            JOIN document d ON d.id = kp.document_id
            WHERE (#{subject}::text IS NULL OR kp.subject = #{subject}::text)
              AND (#{type}::text IS NULL OR kp.is_question = (#{type}::text = 'question'))
              AND (#{q}::text IS NULL OR kp.title ILIKE '%' || #{q}::text || '%')
            ORDER BY kp.is_question DESC, kp.char_count DESC, kp.id
            LIMIT #{limit} OFFSET #{offset}
            """)
    List<KnowledgePointBrief> listKnowledgePoints(
            @Param("subject") String subject,
            @Param("type") String type,
            @Param("q") String q,
            @Param("limit") int limit,
            @Param("offset") int offset
    );

    /**
     * 详情主体。
     *
     * entity_names 用 '||' 拼：实体名里可能有逗号（「A、B 与 C」这种），
     * 用逗号当分隔符会把一个名字切成两个。
     */
    @Select("""
            SELECT kp.id, kp.title, kp.breadcrumb, kp.subject, kp.is_question,
                   kp.chunk_count, kp.char_count, kp.document_id, kp.ordinal_start,
                   kp.answer,
                   array_to_string(kp.chunk_ids, ',')     AS chunk_ids,
                   array_to_string(kp.entity_names, '||') AS entity_names,
                   d.filename AS doc_name
            FROM knowledge_point kp
            JOIN document d ON d.id = kp.document_id
            WHERE kp.id = #{id}
            """)
    KnowledgePointRaw getKnowledgePoint(@Param("id") String id);

    /** 同文档内按 ordinal 找前后篇，详情页底部导航用 */
    @Select("""
            SELECT kp.id, kp.title, kp.subject, kp.is_question, kp.char_count, kp.chunk_count
            FROM knowledge_point kp
            WHERE kp.document_id = #{docId} AND kp.ordinal_start < #{ordinal}
            ORDER BY kp.ordinal_start DESC
            LIMIT 1
            """)
    KnowledgePointBrief prevKnowledgePoint(@Param("docId") long docId, @Param("ordinal") int ordinal);

    @Select("""
            SELECT kp.id, kp.title, kp.subject, kp.is_question, kp.char_count, kp.chunk_count
            FROM knowledge_point kp
            WHERE kp.document_id = #{docId} AND kp.ordinal_start > #{ordinal}
            ORDER BY kp.ordinal_start ASC
            LIMIT 1
            """)
    KnowledgePointBrief nextKnowledgePoint(@Param("docId") long docId, @Param("ordinal") int ordinal);

    /**
     * 相关知识点：共享实体越多越相关。
     *
     * `&&`（数组重叠）走 GIN 索引先筛出候选，再用相关子查询数共享个数。
     * 不能直接用 `&`（交集）——那个操作符是 intarray 扩展给 int[] 的，
     * text[] 上没有，用了会报错。
     */
    @Select("""
            SELECT k2.id, k2.title, k2.subject, k2.is_question, k2.char_count, k2.chunk_count,
                   d.filename AS doc_name,
                   (SELECT count(*) FROM unnest(k1.entity_names) e
                     WHERE e = ANY(k2.entity_names)) AS shared
            FROM knowledge_point k1
            JOIN knowledge_point k2
              ON k2.id <> k1.id AND k2.entity_names && k1.entity_names
            JOIN document d ON d.id = k2.document_id
            WHERE k1.id = #{id}
            ORDER BY shared DESC, k2.char_count DESC
            LIMIT #{limit}
            """)
    List<KnowledgePointBrief> relatedKnowledgePoints(@Param("id") String id, @Param("limit") int limit);

    /** 知识点涉及的实体（按名字取回完整信息，前端画局部图谱用） */
    @Select("""
            <script>
            SELECT e.canonical_name AS id, e.name AS label, e.entity_type AS type,
                   e.subject, COALESCE(st.domain, 'common') AS domain, e.doc_freq AS weight
            FROM entity e
            LEFT JOIN subject_taxonomy st ON st.code = e.subject
            WHERE e.name IN
            <foreach collection="names" item="n" open="(" separator="," close=")">#{n}</foreach>
            </script>
            """)
    List<GraphNodeView> entitiesByNames(@Param("names") List<String> names);

    @Select("""
            SELECT e.name, e.entity_type, e.subject, COALESCE(st.domain, 'common') AS domain,
                   e.doc_freq, e.description
            FROM entity e
            LEFT JOIN subject_taxonomy st ON st.code = e.subject
            WHERE e.canonical_name = lower(#{name}::text) OR lower(e.name) = lower(#{name}::text)
            LIMIT 1
            """)
    EntityDetail getEntity(@Param("name") String name);

    /**
     * 提及该实体的原文片段。
     *
     * 走 idx_chunk_content_trgm（content 上的 GIN trgm 索引），
     * 5505 行下毫秒级。标题里出现实体的排在前面——那说明这整段就在讲它。
     */
    @Select("""
            SELECT c.id AS chunk_id, kp.id AS kp_id, kp.title AS kp_title,
                   left(c.content, 200) AS snippet
            FROM chunk c
            LEFT JOIN knowledge_point kp
              ON kp.document_id = c.document_id AND kp.heading_path = c.heading_path
            WHERE c.level = 'child' AND c.content ILIKE '%' || #{name}::text || '%'
            ORDER BY (c.heading_path ILIKE '%' || #{name}::text || '%') DESC,
                     length(c.content) DESC
            LIMIT #{limit}
            """)
    List<EntityDetail.Mention> listMentions(@Param("name") String name, @Param("limit") int limit);

    /** 实体的一跳关系，前端画关系网 */
    @Select("""
            SELECT a.canonical_name AS source, b.canonical_name AS target,
                   r.rel_type AS rel, r.weight,
                   COALESCE(sa.domain, 'common') AS src_domain,
                   COALESCE(sb.domain, 'common') AS dst_domain
            FROM relation r
            JOIN entity a ON a.id = r.src_entity_id
            JOIN entity b ON b.id = r.dst_entity_id
            LEFT JOIN subject_taxonomy sa ON sa.code = a.subject
            LEFT JOIN subject_taxonomy sb ON sb.code = b.subject
            WHERE a.canonical_name = lower(#{name}::text)
               OR b.canonical_name = lower(#{name}::text)
            ORDER BY r.weight DESC
            LIMIT #{limit}
            """)
    List<GraphEdgeView> entityRelations(@Param("name") String name, @Param("limit") int limit);
}
