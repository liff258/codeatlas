package com.codeatlas.dto;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 契约字段名的回归测试。
 *
 * 为什么值得单独测：契约（contracts/openapi.yaml）里字段全是 snake_case，
 * 而 Java 字段按惯例是驼峰。少加一个 {@code @JsonNaming} 不会编译报错、
 * 不会抛异常，只是默默返回 {@code createdAt}——前端按契约取值拿到 undefined，
 * 表现是"数据明明有，界面上就是空"。这种错误只能靠断言抓。
 *
 * 之前 Session / Message 就是这个毛病（返回 createdAt，契约要 created_at）。
 */
class JsonNamingTest {

    private final ObjectMapper mapper = new ObjectMapper();

    @Test
    @DisplayName("学科视图序列化成契约要求的 snake_case")
    void subjectViewUsesSnakeCase() throws Exception {
        SubjectView v = new SubjectView();
        v.setCode("RAG");
        v.setDisplayName("检索增强生成");
        v.setSortOrder(10);
        v.setChunkCount(42);

        String json = mapper.writeValueAsString(v);

        assertThat(json).contains("\"display_name\"", "\"sort_order\"", "\"chunk_count\"");
        assertThat(json).doesNotContain("displayName", "sortOrder", "chunkCount");
    }

    @Test
    @DisplayName("切片详情带 document_id / heading_path / knowledge_points")
    void chunkDetailUsesSnakeCase() throws Exception {
        ChunkDetailView v = new ChunkDetailView();
        v.setId("c_102");
        v.setDocumentId(7L);
        v.setHeadingPath("JVM > 3.2 G1 收集器");
        v.setKnowledgePoints(List.of("SATB", "写屏障"));

        String json = mapper.writeValueAsString(v);

        assertThat(json).contains("\"document_id\"", "\"heading_path\"", "\"knowledge_points\"");
        assertThat(json).doesNotContain("documentId", "headingPath", "knowledgePoints");
    }

    @Test
    @DisplayName("轨迹带 trace_id / rewrite_count / stop_reason / latency_ms")
    void traceUsesSnakeCase() throws Exception {
        TraceView t = new TraceView();
        t.setTraceId("t_abc");
        t.setRewriteCount(2);
        t.setStopReason("normal");
        t.setLatencyMs(25800);
        t.setCoverage(new BigDecimal("0.750"));

        String json = mapper.writeValueAsString(t);

        assertThat(json).contains(
                "\"trace_id\"", "\"rewrite_count\"", "\"stop_reason\"", "\"latency_ms\"");
        assertThat(json).doesNotContain("traceId", "rewriteCount", "stopReason", "latencyMs");
    }

    @Test
    @DisplayName("评测结果带 recall_at_5 / case_count")
    void evalRunUsesSnakeCase() throws Exception {
        EvalRunView v = new EvalRunView();
        v.setName("检索评测 · rerank");
        v.setRecallAt5(new BigDecimal("0.9390"));
        v.setCaseCount(33);

        String json = mapper.writeValueAsString(v);

        assertThat(json).contains("\"recall_at_5\"", "\"case_count\"");
        assertThat(json).doesNotContain("recallAt5", "caseCount");
    }

    @Test
    @DisplayName("反馈请求按 snake_case 反序列化（前端传 message_id）")
    void feedbackRequestDeserializesSnakeCase() throws Exception {
        String json = "{\"message_id\": 42, \"rating\": -1, \"reason\": \"无出处\"}";

        FeedbackRequest req = mapper.readValue(json, FeedbackRequest.class);

        assertThat(req.getMessageId()).isEqualTo(42L);
        assertThat(req.getRating()).isEqualTo(-1);
    }
}
