package com.codeatlas.controller;

import com.codeatlas.common.BizException;
import com.codeatlas.common.GlobalExceptionHandler;
import com.codeatlas.dto.ChunkDetailView;
import com.codeatlas.dto.SubjectView;
import com.codeatlas.service.CatalogService;
import com.codeatlas.service.GraphService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.List;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 目录接口的 HTTP 层契约。
 *
 * 用 standalone MockMvc 而不是 @SpringBootTest：这些接口不依赖 Spring 上下文里的
 * 数据源和 WebClient，起整个容器只是让测试慢十几秒，测的东西并不会更多。
 *
 * 断言的重点是「契约里写的样子」——外层 Result 包装、字段 snake_case、错误码分 400/404。
 */
class CatalogControllerTest {

    private CatalogService service;
    private GraphService graphService;
    private MockMvc mvc;

    @BeforeEach
    void setUp() {
        service = mock(CatalogService.class);
        graphService = mock(GraphService.class);
        mvc = MockMvcBuilders
                .standaloneSetup(new CatalogController(service, graphService))
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    @Test
    @DisplayName("学科列表包在 Result 里，字段是 snake_case")
    void subjectsAreWrappedAndSnakeCased() throws Exception {
        SubjectView v = new SubjectView();
        v.setCode("JVM");
        v.setDisplayName("JVM");
        v.setChunkCount(512);
        when(service.listSubjects()).thenReturn(List.of(v));

        mvc.perform(get("/api/subjects"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data[0].code").value("JVM"))
                .andExpect(jsonPath("$.data[0].display_name").value("JVM"))
                .andExpect(jsonPath("$.data[0].chunk_count").value(512));
    }

    @Test
    @DisplayName("引用原文：路径里的 c_102 原样传给 service")
    void chunkDetailIsReturned() throws Exception {
        ChunkDetailView v = new ChunkDetailView();
        v.setId("c_102");
        v.setDocumentId(7L);
        v.setHeadingPath("JVM > 3.2 G1 收集器");
        when(service.getChunk("c_102")).thenReturn(v);

        mvc.perform(get("/api/chunks/c_102"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.id").value("c_102"))
                .andExpect(jsonPath("$.data.document_id").value(7))
                .andExpect(jsonPath("$.data.heading_path").value("JVM > 3.2 G1 收集器"));
    }

    @Test
    @DisplayName("切片不存在返回 404，不是 500")
    void missingChunkReturns404() throws Exception {
        when(service.getChunk("c_999")).thenThrow(new BizException(404, "切片不存在：c_999"));

        mvc.perform(get("/api/chunks/c_999"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value(404));
    }

    @Test
    @DisplayName("rating 超出 -1..1 时拒绝，不能把脏数据写进 feedback 表")
    void feedbackRatingIsValidated() throws Exception {
        mvc.perform(post("/api/feedback")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"message_id\": 1, \"rating\": 5}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value(400));
    }

    @Test
    @DisplayName("合法反馈返回成功")
    void feedbackAcceptsValidPayload() throws Exception {
        mvc.perform(post("/api/feedback")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"message_id\": 1, \"rating\": -1, \"reason\": \"无出处\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0));
    }

    @Test
    @DisplayName("删除不存在的文档返回 404")
    void deleteMissingDocumentReturns404() throws Exception {
        doThrow(new BizException(404, "文档不存在：9")).when(service).deleteDocument(9L);

        mvc.perform(delete("/api/documents/9"))
                .andExpect(status().isNotFound());
    }

    @Test
    @DisplayName("轨迹不存在返回 404")
    void missingTraceReturns404() throws Exception {
        when(service.getTrace(any())).thenThrow(new BizException(404, "轨迹不存在"));

        mvc.perform(get("/api/traces/t_none"))
                .andExpect(status().isNotFound());
    }
}
