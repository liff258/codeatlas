package com.codeatlas.dto;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import lombok.Data;
import lombok.EqualsAndHashCode;

import java.util.List;

/**
 * 知识点详情（契约 components/schemas/KnowledgePointDetail）。
 *
 * 继承 Brief 而不是重写一遍字段：列表和详情共享 8 个字段，
 * 分开写迟早会出现「列表有 doc_name、详情忘了加」这种不一致。
 */
@Data
@EqualsAndHashCode(callSuper = true)
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public class KnowledgePointDetail extends KnowledgePointBrief {

    /** 完整正文（同标题下多个 child 按 ordinal 拼接） */
    private String answer;
    private List<String> chunkIds;
    private Long documentId;
    /** 正文提到的实体，前端画局部图谱、点击跳实体页 */
    private List<GraphNodeView> entities;
    /** 相关知识点，按共享实体数排序 */
    private List<KnowledgePointBrief> related;
    private KnowledgePointBrief prev;
    private KnowledgePointBrief next;
}
