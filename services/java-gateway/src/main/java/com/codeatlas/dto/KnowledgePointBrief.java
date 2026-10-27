package com.codeatlas.dto;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import lombok.Data;

/**
 * 知识点列表项（契约 components/schemas/KnowledgePointBrief）。
 *
 * preview 是正文前 140 字，由 SQL 的 left() 截好——
 * 列表页只要摘要，没必要把整篇正文（可能 5000 字）传到前端再截。
 */
@Data
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public class KnowledgePointBrief {

    private String id;
    private String title;
    private String breadcrumb;
    private String subject;
    private Boolean isQuestion;
    private Integer chunkCount;
    private Integer charCount;
    private String preview;
    /** 来源文档名，列表页标注出处用 */
    private String docName;
}
