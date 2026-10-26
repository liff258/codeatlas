package com.codeatlas.dto;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import lombok.Data;

/**
 * 图谱节点（契约 components/schemas/GraphNode）。
 *
 * id 用 canonical_name：它天然唯一（表上有唯一索引），
 * 而且比数字 id 更适合当边的端点标识——前端拿到的边里写的就是这个名字。
 */
@Data
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public class GraphNodeView {

    private String id;
    private String label;
    private String type;
    private String subject;
    /** backend / ai / common，决定节点颜色；两端不同即为跨域边 */
    private String domain;
    /** 度数，决定节点大小 */
    private Integer weight;
}
