package com.codeatlas.mapper;

import com.codeatlas.dto.DocumentView;
import com.codeatlas.dto.EvalRunView;
import com.codeatlas.dto.SubjectView;
import com.codeatlas.dto.TraceView;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;
import java.util.Map;

/**
 * 只读目录类查询 + 两个写操作。
 *
 * 为什么单独一个 mapper 而不是给每张表建一个：
 * 这些查询都是「读一次、拼一个视图」的形态，没有增删改的业务语义，
 * 一个文件里能一眼看完所有 SQL，比摊成 6 个文件更好维护。
 *
 * 表所有权（CLAUDE.md 不变量 2）：这里只读 document / chunk / subject_taxonomy /
 * agent_trace / agent_step / eval_run，写的只有 feedback 和 document 删除。
 */
@Mapper
public interface CatalogMapper {

    /**
     * 学科列表 + 每个学科下的切片数。
     *
     * 用 LEFT JOIN 而不是 INNER：新建但还没入库切片的学科也要显示出来，
     * 前端靠 chunk_count=0 提示"这个方向还没素材"——那正是补素材的线索。
     */
    @Select("""
            SELECT st.code, st.domain, st.display_name, st.sort_order, st.color,
                   count(c.id) AS chunk_count
            FROM subject_taxonomy st
            LEFT JOIN chunk c ON c.subject = st.code AND c.level = 'child'
            GROUP BY st.code, st.domain, st.display_name, st.sort_order, st.color
            ORDER BY st.sort_order, st.code
            """)
    List<SubjectView> listSubjects();

    /**
     * 文档列表。status 传 null 表示不过滤。
     *
     * 用 COALESCE 而不是动态 SQL：一个条件就够，没必要引入 {@code <script>}。
     */
    @Select("""
            SELECT id, filename, file_type, size_bytes, status, chunk_count, error_msg, uploaded_at
            FROM document
            WHERE status = COALESCE(#{status}, status)
            ORDER BY uploaded_at DESC
            LIMIT 200
            """)
    List<DocumentView> listDocuments(@Param("status") String status);

    /**
     * 单个切片的正文 + 所属文档名。
     *
     * knowledge_points 是 TEXT[]，用 array_to_string 拼成字符串再在 service 里切开——
     * 直接映射数组需要自定义 TypeHandler，为一个只读字段不值得。
     */
    @Select("""
            SELECT c.id, c.document_id, d.filename AS doc_name, c.heading_path,
                   c.content, c.subject,
                   array_to_string(c.knowledge_points, '||') AS knowledge_points
            FROM chunk c
            JOIN document d ON d.id = c.document_id
            WHERE c.id = #{id}
            """)
    Map<String, Object> getChunk(@Param("id") long id);

    @Select("""
            SELECT trace_id, question, answer, intent, coverage,
                   rewrite_count, stop_reason, latency_ms
            FROM agent_trace
            WHERE trace_id = #{traceId}
            """)
    TraceView getTrace(@Param("traceId") String traceId);

    /**
     * trace 的每一步。payload 是 JSONB，转成文本再在 service 里解析成 Map——
     * MyBatis 没有内置的 JSONB → Map 映射，为一个字段引 TypeHandler 不划算。
     */
    @Select("""
            SELECT seq, node, status, payload::text AS payload, duration_ms
            FROM agent_step
            WHERE trace_id = #{traceId}
            ORDER BY seq
            """)
    List<Map<String, Object>> listSteps(@Param("traceId") String traceId);

    @Select("""
            SELECT id, name, recall_at_5, citation_accuracy, no_source_rate, case_count, created_at
            FROM eval_run
            ORDER BY created_at DESC, id DESC
            LIMIT 50
            """)
    List<EvalRunView> listEvalRuns();

    @Insert("""
            INSERT INTO feedback (message_id, rating, reason, comment)
            VALUES (#{messageId}, #{rating}, #{reason}, #{comment})
            """)
    int insertFeedback(
            @Param("messageId") Long messageId,
            @Param("rating") Integer rating,
            @Param("reason") String reason,
            @Param("comment") String comment
    );

    /** chunk 有 ON DELETE CASCADE，删文档会连带删切片和向量 */
    @Delete("DELETE FROM document WHERE id = #{id}")
    int deleteDocument(@Param("id") long id);
}
