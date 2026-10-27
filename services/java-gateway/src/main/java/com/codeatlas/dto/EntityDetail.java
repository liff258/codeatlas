package com.codeatlas.dto;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import lombok.Data;

import java.util.List;

/**
 * 实体详情（契约 components/schemas/EntityDetail）。
 *
 * description 目前全部来自原文摘录（entity.description 727 条全是 NULL），
 * 所以必须带 description_source 让前端标注「摘自原文」——
 * 不标的话，用户会以为这是权威定义，被追问出处就答不上来。
 */
@Data
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public class EntityDetail {

    private String name;
    private String entityType;
    private String subject;
    private String domain;
    private Integer docFreq;
    private String description;
    /** curated = 人工/AI 写的；extracted = 从原文摘的 */
    private String descriptionSource;
    private List<Mention> mentions;
    private List<GraphEdgeView> relations;

    /** 提及该实体的一处原文 */
    @Data
    @JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
    public static class Mention {
        private String chunkId;
        /** 对应的知识点，前端可点进去 */
        private String kpId;
        private String kpTitle;
        private String snippet;
    }
}
