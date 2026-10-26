package com.codeatlas.dto;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import lombok.Data;

import java.util.List;

/**
 * 图谱数据（契约 components/schemas/GraphData）。
 *
 * truncated 的意义：前端据此提示「仅展示核心节点」。
 * 不返回这个字段的话，用户会以为看到的就是全部——那是误导。
 */
@Data
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public class GraphDataView {

    private List<GraphNodeView> nodes;
    private List<GraphEdgeView> edges;
    private Boolean truncated;
}
