package com.codeatlas.service;

import com.codeatlas.common.BizException;
import com.codeatlas.dto.GraphDataView;
import com.codeatlas.dto.GraphEdgeView;
import com.codeatlas.dto.GraphNodeView;
import com.codeatlas.mapper.GraphMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 全库图谱的判定逻辑。
 *
 * 重点测跨域判定，因为它是产品核心卖点的判定规则：
 * 判错一次就是一条假边，演示时指着假边讲比没有边糟得多。
 */
class GraphServiceTest {

    private final GraphMapper mapper = mock(GraphMapper.class);
    private final GraphService service = new GraphService(mapper);

    private static GraphEdgeView edge(String srcDomain, String dstDomain) {
        GraphEdgeView e = new GraphEdgeView();
        e.setSource("甲");
        e.setTarget("乙");
        e.setRel("对比");
        e.setWeight(new BigDecimal("1.0"));
        e.setSrcDomain(srcDomain);
        e.setDstDomain(dstDomain);
        return e;
    }

    @Test
    @DisplayName("两端已知且不同 → 跨域")
    void differentKnownDomainsAreCross() {
        when(mapper.topNodes(anyInt(), eq(null))).thenReturn(List.of(new GraphNodeView()));
        when(mapper.edgesAmongTop(anyInt(), eq(null))).thenReturn(List.of(edge("ai", "backend")));
        when(mapper.countEntities()).thenReturn(10L);

        GraphDataView view = service.overview(50, null);

        assertThat(view.getEdges().get(0).getCrossDomain()).isTrue();
    }

    @Test
    @DisplayName("一端是 common（未归类）不算跨域——那是未知，不是另一个域")
    void commonDomainIsNotCross() {
        when(mapper.topNodes(anyInt(), eq(null))).thenReturn(List.of(new GraphNodeView()));
        when(mapper.edgesAmongTop(anyInt(), eq(null))).thenReturn(List.of(edge("common", "ai")));
        when(mapper.countEntities()).thenReturn(10L);

        GraphDataView view = service.overview(50, null);

        assertThat(view.getEdges().get(0).getCrossDomain()).isFalse();
    }

    @Test
    @DisplayName("两端同域不算跨域")
    void sameDomainIsNotCross() {
        when(mapper.topNodes(anyInt(), eq(null))).thenReturn(List.of(new GraphNodeView()));
        when(mapper.edgesAmongTop(anyInt(), eq(null))).thenReturn(List.of(edge("backend", "backend")));
        when(mapper.countEntities()).thenReturn(10L);

        assertThat(service.overview(50, null).getEdges().get(0).getCrossDomain()).isFalse();
    }

    @Test
    @DisplayName("实体总数大于返回节点数时标记 truncated")
    void truncatedWhenMoreEntitiesExist() {
        when(mapper.topNodes(anyInt(), eq(null))).thenReturn(List.of(new GraphNodeView()));
        when(mapper.edgesAmongTop(anyInt(), eq(null))).thenReturn(List.of());
        when(mapper.countEntities()).thenReturn(500L);

        assertThat(service.overview(50, null).getTruncated()).isTrue();
    }

    @Test
    @DisplayName("limit 超上限被夹到 300，防止一次拉爆前端")
    void limitIsClamped() {
        when(mapper.topNodes(anyInt(), eq(null))).thenReturn(List.of());
        when(mapper.edgesAmongTop(anyInt(), eq(null))).thenReturn(List.of());
        when(mapper.countEntities()).thenReturn(0L);

        service.overview(9999, null);

        verify(mapper).topNodes(300, null);
    }

    @Test
    @DisplayName("邻居查询：depth 夹到 2 跳，空结果给 404")
    void neighborsClampAnd404() {
        when(mapper.neighborIds(anyString(), anyInt())).thenReturn(List.of());

        assertThatThrownBy(() -> service.neighbors("不存在", 9))
                .isInstanceOf(BizException.class)
                .satisfies(e -> assertThat(((BizException) e).getCode()).isEqualTo(404));

        verify(mapper).neighborIds("不存在", 2);
    }

    @Test
    @DisplayName("邻居查询：entity 为空给 400")
    void neighborsRejectsBlankEntity() {
        assertThatThrownBy(() -> service.neighbors("  ", 1))
                .isInstanceOf(BizException.class)
                .satisfies(e -> assertThat(((BizException) e).getCode()).isEqualTo(400));
    }
}
