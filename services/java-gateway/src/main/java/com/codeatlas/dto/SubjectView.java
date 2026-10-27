package com.codeatlas.dto;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import lombok.Data;

/**
 * 学科分类项（契约 components/schemas/Subject）。
 *
 * 为什么要加 {@code @JsonNaming}：
 * 契约里字段是 snake_case（{@code display_name} / {@code chunk_count}），
 * 而 Java 字段按惯例是驼峰。之前 Session / Message 没做这层映射，
 * 实际返回的是 {@code createdAt}，和契约对不上——前端按契约写就会取不到值。
 * 这个注解比在每个字段上挂 {@code @JsonProperty} 省事，也不容易漏。
 */
@Data
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public class SubjectView {

    private String code;
    private String domain;
    private String displayName;
    private Integer sortOrder;
    private String color;
    /** 该学科下已有多少 child chunk，前端用它显示"资料充足度" */
    private Integer chunkCount;
    /** 该学科下有多少知识点（板块页显示） */
    private Integer kpCount;
    /** 其中有多少道面试题；为 0 时前端标"建设中" */
    private Integer questionCount;
}
