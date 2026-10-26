package com.codeatlas.service;

import com.codeatlas.common.BizException;
import com.codeatlas.dto.ChunkDetailView;
import com.codeatlas.dto.TraceView;
import com.codeatlas.mapper.CatalogMapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * 目录服务的转换逻辑。
 *
 * 重点测「存储形态 → 契约形态」这一层，因为它是唯一有判断的地方：
 * id 前缀怎么解析、数组怎么切、JSONB 怎么解析、找不到时给 404 还是 400。
 * SQL 本身不在这里测（那是集成测试的事，需要真库）。
 */
class CatalogServiceTest {

    private final CatalogMapper mapper = mock(CatalogMapper.class);
    private final CatalogService service = new CatalogService(mapper, new ObjectMapper());

    @Test
    @DisplayName("c_102 和 102 都能取到同一个切片")
    void chunkIdAcceptsBothForms() {
        when(mapper.getChunk(102L)).thenReturn(Map.of(
                "id", 102L,
                "document_id", 7L,
                "doc_name", "jvm.md",
                "heading_path", "JVM > 3.2 G1",
                "content", "SATB 是快照标记",
                "subject", "JVM",
                "knowledge_points", "SATB||写屏障"
        ));

        ChunkDetailView byPrefixed = service.getChunk("c_102");
        ChunkDetailView byPlain = service.getChunk("102");

        assertThat(byPrefixed.getId()).isEqualTo("c_102");
        assertThat(byPlain.getId()).isEqualTo("c_102");
        assertThat(byPrefixed.getDocumentId()).isEqualTo(7L);
        assertThat(byPrefixed.getKnowledgePoints()).containsExactly("SATB", "写屏障");
    }

    @Test
    @DisplayName("切片不存在时抛 404，不是 400")
    void missingChunkIs404() {
        when(mapper.getChunk(anyLong())).thenReturn(null);

        assertThatThrownBy(() -> service.getChunk("c_999"))
                .isInstanceOf(BizException.class)
                .satisfies(e -> assertThat(((BizException) e).getCode()).isEqualTo(404));
    }

    @Test
    @DisplayName("id 格式不对时抛 400")
    void malformedChunkIdIs400() {
        assertThatThrownBy(() -> service.getChunk("c_abc"))
                .isInstanceOf(BizException.class)
                .satisfies(e -> assertThat(((BizException) e).getCode()).isEqualTo(400));
    }

    @Test
    @DisplayName("轨迹的 payload JSONB 被解析成对象，脏数据也不炸")
    void traceStepsParsePayload() {
        TraceView trace = new TraceView();
        trace.setTraceId("t_abc");
        when(mapper.getTrace("t_abc")).thenReturn(trace);
        when(mapper.listSteps(eq("t_abc"))).thenReturn(List.of(
                Map.of("seq", 1, "node", "router", "status", "ok",
                        "payload", "{\"label\":\"判断问题意图\"}", "duration_ms", 1200),
                // 故意塞一段坏 JSON：单条脏数据不该让整个回放挂掉
                Map.of("seq", 2, "node", "planner", "status", "degraded",
                        "payload", "not-json", "duration_ms", 9000)
        ));

        TraceView result = service.getTrace("t_abc");

        assertThat(result.getSteps()).hasSize(2);
        assertThat(result.getSteps().get(0).getPayload()).containsEntry("label", "判断问题意图");
        assertThat(result.getSteps().get(1).getPayload()).containsKey("raw");
        assertThat(result.getSteps().get(1).getDurationMs()).isEqualTo(9000);
    }

    @Test
    @DisplayName("轨迹不存在时抛 404")
    void missingTraceIs404() {
        when(mapper.getTrace("t_none")).thenReturn(null);

        assertThatThrownBy(() -> service.getTrace("t_none"))
                .isInstanceOf(BizException.class)
                .satisfies(e -> assertThat(((BizException) e).getCode()).isEqualTo(404));
    }

    @Test
    @DisplayName("status 传空串等同于不过滤")
    void blankStatusMeansNoFilter() {
        service.listDocuments("  ");
        org.mockito.Mockito.verify(mapper).listDocuments(null);
    }
}
