package com.codeatlas.controller;

import com.codeatlas.common.BizException;
import com.codeatlas.common.GlobalExceptionHandler;
import com.codeatlas.dto.EntityDetail;
import com.codeatlas.dto.KnowledgePointBrief;
import com.codeatlas.dto.KnowledgePointDetail;
import com.codeatlas.dto.PageResult;
import com.codeatlas.service.LearningService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.List;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 知识平台接口的 HTTP 契约。
 *
 * 断言重点是字段名（snake_case）和分页包装的形状——
 * 前端按契约写，字段名错一个就是 undefined。
 */
class LearningControllerTest {

    private LearningService service;
    private MockMvc mvc;

    @BeforeEach
    void setUp() {
        service = mock(LearningService.class);
        mvc = MockMvcBuilders
                .standaloneSetup(new LearningController(service))
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    private static KnowledgePointBrief brief() {
        KnowledgePointBrief b = new KnowledgePointBrief();
        b.setId("kp_abc");
        b.setTitle("AQS 是什么");
        b.setSubject("并发");
        b.setIsQuestion(true);
        b.setCharCount(420);
        b.setChunkCount(2);
        b.setDocName("aqs.md");
        return b;
    }

    @Test
    @DisplayName("列表返回分页包装，字段 snake_case")
    void listReturnsPageResult() throws Exception {
        when(service.list(eq("并发"), eq("question"), isNull(), isNull(), isNull()))
                .thenReturn(PageResult.of(List.of(brief()), 128, 1, 20));

        mvc.perform(get("/api/knowledge-points")
                        .param("subject", "并发")
                        .param("type", "question"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.total").value(128))
                .andExpect(jsonPath("$.data.has_more").value(true))
                .andExpect(jsonPath("$.data.items[0].id").value("kp_abc"))
                .andExpect(jsonPath("$.data.items[0].is_question").value(true))
                .andExpect(jsonPath("$.data.items[0].char_count").value(420))
                .andExpect(jsonPath("$.data.items[0].doc_name").value("aqs.md"));
    }

    @Test
    @DisplayName("题库接口内部按 type=question 查询，前端不用自己传")
    void questionsForcesQuestionType() throws Exception {
        when(service.list(any(), eq("question"), any(), any(), any()))
                .thenReturn(PageResult.of(List.of(), 0, 1, 20));

        mvc.perform(get("/api/questions").param("subject", "Redis"))
                .andExpect(status().isOk());

        verify(service).list(eq("Redis"), eq("question"), isNull(), isNull(), isNull());
    }

    @Test
    @DisplayName("详情：正文和 chunk_ids 都返回")
    void detailReturnsAnswer() throws Exception {
        KnowledgePointDetail d = new KnowledgePointDetail();
        d.setId("kp_abc");
        d.setTitle("AQS 是什么");
        d.setAnswer("AQS 是抽象队列同步器。");
        d.setChunkIds(List.of("c_453"));
        d.setRelated(List.of());
        when(service.detail("kp_abc")).thenReturn(d);

        mvc.perform(get("/api/knowledge-points/kp_abc"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.answer").value("AQS 是抽象队列同步器。"))
                .andExpect(jsonPath("$.data.chunk_ids[0]").value("c_453"));
    }

    @Test
    @DisplayName("知识点不存在返回 404")
    void detailMissingIs404() throws Exception {
        when(service.detail("kp_none")).thenThrow(new BizException(404, "知识点不存在"));

        mvc.perform(get("/api/knowledge-points/kp_none"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value(404));
    }

    @Test
    @DisplayName("实体详情：description_source 必须出现，前端靠它标「摘自原文」")
    void entityExposesDescriptionSource() throws Exception {
        EntityDetail e = new EntityDetail();
        e.setName("AQS");
        e.setEntityType("概念");
        e.setDescription("抽象队列同步器");
        e.setDescriptionSource("extracted");
        e.setMentions(List.of());
        e.setRelations(List.of());
        when(service.entity("AQS")).thenReturn(e);

        mvc.perform(get("/api/entities").param("name", "AQS"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.name").value("AQS"))
                .andExpect(jsonPath("$.data.entity_type").value("概念"))
                .andExpect(jsonPath("$.data.description_source").value("extracted"));
    }

    @Test
    @DisplayName("实体名含特殊字符（B+ 树）走 query 参数不会被路径解析吃掉")
    void entityNameWithSpecialChars() throws Exception {
        EntityDetail e = new EntityDetail();
        e.setName("B+ 树");
        when(service.entity("B+ 树")).thenReturn(e);

        mvc.perform(get("/api/entities").param("name", "B+ 树"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.name").value("B+ 树"));
    }

    @Test
    @DisplayName("缺少必填参数 name 时返回 400，不是 500")
    void missingRequiredParamIs400() throws Exception {
        mvc.perform(get("/api/entities"))
                .andExpect(status().isBadRequest());
    }
}
