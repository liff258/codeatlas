package com.codeatlas.service;

import com.codeatlas.common.BizException;
import com.codeatlas.dto.EntityDetail;
import com.codeatlas.dto.GraphEdgeView;
import com.codeatlas.dto.KnowledgePointBrief;
import com.codeatlas.dto.KnowledgePointDetail;
import com.codeatlas.dto.KnowledgePointRaw;
import com.codeatlas.dto.PageResult;
import com.codeatlas.mapper.LearningMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 知识平台服务层。
 *
 * 重点测「存储形态 → 契约形态」的转换和参数边界，
 * 因为这两处出错不会抛异常，只会静默返回错的东西：
 * 分页参数不夹紧会拖垮数据库，chunk id 不带前缀前端就对不上引用。
 */
class LearningServiceTest {

    private final LearningMapper mapper = mock(LearningMapper.class);
    private final LearningService service = new LearningService(mapper);

    private static KnowledgePointRaw raw() {
        KnowledgePointRaw r = new KnowledgePointRaw();
        r.setId("kp_test");
        r.setTitle("AQS 是什么");
        r.setSubject("并发");
        r.setIsQuestion(true);
        r.setChunkCount(2);
        r.setCharCount(420);
        r.setDocumentId(5L);
        r.setDocName("aqs.md");
        r.setAnswer("AQS 是抽象队列同步器。它用一个 int 表示同步状态。");
        r.setChunkIds("453,454");
        r.setEntityNames("AQS||ReentrantLock||Semaphore");
        r.setOrdinalStart(10);
        return r;
    }

    @Test
    @DisplayName("size 超上限被夹到 50，防止一次拉爆")
    void sizeIsClamped() {
        when(mapper.countKnowledgePoints(any(), any(), any())).thenReturn(100L);
        when(mapper.listKnowledgePoints(any(), any(), any(), anyInt(), anyInt())).thenReturn(List.of());

        PageResult<KnowledgePointBrief> page = service.list("并发", "question", null, 1, 9999);

        assertThat(page.getSize()).isEqualTo(50);
        verify(mapper).listKnowledgePoints(eq("并发"), eq("question"), eq(null), eq(50), eq(0));
    }

    @Test
    @DisplayName("page 小于 1 时按 1 处理，offset 不能为负")
    void pageIsClamped() {
        when(mapper.countKnowledgePoints(any(), any(), any())).thenReturn(10L);
        when(mapper.listKnowledgePoints(any(), any(), any(), anyInt(), anyInt())).thenReturn(List.of());

        PageResult<KnowledgePointBrief> page = service.list(null, "all", null, -3, 20);

        assertThat(page.getPage()).isEqualTo(1);
        verify(mapper).listKnowledgePoints(eq(null), eq(null), eq(null), eq(20), eq(0));
    }

    @Test
    @DisplayName("type 传错值当 all 处理，不返回空列表")
    void unknownTypeFallsBackToAll() {
        when(mapper.countKnowledgePoints(any(), any(), any())).thenReturn(5L);
        when(mapper.listKnowledgePoints(any(), any(), any(), anyInt(), anyInt())).thenReturn(List.of());

        service.list("并发", "quesiton", null, 1, 20);

        // normalizeType 把拼错的值归一成 null（= 不过滤）
        verify(mapper).countKnowledgePoints(eq("并发"), eq(null), eq(null));
    }

    @Test
    @DisplayName("总数 0 时不查列表，省一次空查询")
    void emptyResultSkipsListQuery() {
        when(mapper.countKnowledgePoints(any(), any(), any())).thenReturn(0L);

        PageResult<KnowledgePointBrief> page = service.list("工程实践", null, null, 1, 20);

        assertThat(page.getItems()).isEmpty();
        assertThat(page.isHasMore()).isFalse();
        verify(mapper, never()).listKnowledgePoints(any(), any(), any(), anyInt(), anyInt());
    }

    @Test
    @DisplayName("详情：chunk id 要带 c_ 前缀，和 citation 里的形式一致")
    void detailPrefixesChunkIds() {
        when(mapper.getKnowledgePoint("kp_test")).thenReturn(raw());
        when(mapper.entitiesByNames(any())).thenReturn(List.of());
        when(mapper.relatedKnowledgePoints(anyString(), anyInt())).thenReturn(List.of());

        KnowledgePointDetail d = service.detail("kp_test");

        assertThat(d.getChunkIds()).containsExactly("c_453", "c_454");
        assertThat(d.getEntities()).isEmpty();
        assertThat(d.getPreview()).startsWith("AQS 是抽象队列同步器");
    }

    @Test
    @DisplayName("详情：知识点不存在给 404")
    void detailMissingIs404() {
        when(mapper.getKnowledgePoint("kp_none")).thenReturn(null);

        assertThatThrownBy(() -> service.detail("kp_none"))
                .isInstanceOf(BizException.class)
                .satisfies(e -> assertThat(((BizException) e).getCode()).isEqualTo(404));
    }

    @Test
    @DisplayName("实体：description 为空时用首条提及兜底，并标 extracted")
    void entityDescriptionFallsBackToExtracted() {
        EntityDetail e = new EntityDetail();
        e.setName("AQS");
        e.setEntityType("概念");
        e.setDocFreq(3);
        when(mapper.getEntity("AQS")).thenReturn(e);

        EntityDetail.Mention m = new EntityDetail.Mention();
        m.setSnippet("### 4.1 标题\n\nAQS 是抽象队列同步器。它维护一个同步状态。");
        when(mapper.listMentions(eq("AQS"), anyInt())).thenReturn(new java.util.ArrayList<>(List.of(m)));
        when(mapper.entityRelations(eq("AQS"), anyInt())).thenReturn(List.of());

        EntityDetail d = service.entity("AQS");

        assertThat(d.getDescriptionSource()).isEqualTo("extracted");
        // markdown 标题要被剥掉，否则「描述」变成一行标题
        assertThat(d.getDescription()).doesNotContain("###");
        assertThat(d.getDescription()).contains("AQS 是抽象队列同步器");
    }

    @Test
    @DisplayName("实体：有 description 时标 curated，不覆盖")
    void entityDescriptionCuratedIsKept() {
        EntityDetail e = new EntityDetail();
        e.setName("AQS");
        e.setDescription("抽象队列同步器，AQS 是并发包的基础。");
        when(mapper.getEntity("AQS")).thenReturn(e);
        when(mapper.listMentions(anyString(), anyInt())).thenReturn(List.of());
        when(mapper.entityRelations(anyString(), anyInt())).thenReturn(List.of());

        EntityDetail d = service.entity("AQS");

        assertThat(d.getDescriptionSource()).isEqualTo("curated");
        assertThat(d.getDescription()).isEqualTo("抽象队列同步器，AQS 是并发包的基础。");
    }

    @Test
    @DisplayName("实体：关系里的跨域标记走统一规则，common 不算跨域")
    void entityRelationsMarkCrossDomain() {
        EntityDetail e = new EntityDetail();
        e.setName("AQS");
        when(mapper.getEntity("AQS")).thenReturn(e);
        when(mapper.listMentions(anyString(), anyInt())).thenReturn(List.of());

        GraphEdgeView cross = edge("ai", "backend");
        GraphEdgeView sameDomain = edge("backend", "backend");
        GraphEdgeView unknown = edge("common", "ai");
        when(mapper.entityRelations(eq("AQS"), anyInt())).thenReturn(List.of(cross, sameDomain, unknown));

        EntityDetail d = service.entity("AQS");

        assertThat(d.getRelations().get(0).getCrossDomain()).isTrue();
        assertThat(d.getRelations().get(1).getCrossDomain()).isFalse();
        assertThat(d.getRelations().get(2).getCrossDomain()).isFalse();
    }

    @Test
    @DisplayName("实体：name 为空给 400")
    void entityBlankNameIs400() {
        assertThatThrownBy(() -> service.entity("  "))
                .isInstanceOf(BizException.class)
                .satisfies(e -> assertThat(((BizException) e).getCode()).isEqualTo(400));
    }

    private static GraphEdgeView edge(String a, String b) {
        GraphEdgeView e = new GraphEdgeView();
        e.setSource("x");
        e.setTarget("y");
        e.setRel("使用");
        e.setWeight(new BigDecimal("1.0"));
        e.setSrcDomain(a);
        e.setDstDomain(b);
        return e;
    }
}
