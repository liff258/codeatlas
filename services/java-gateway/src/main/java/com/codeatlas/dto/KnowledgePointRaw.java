package com.codeatlas.dto;

import lombok.Data;

/**
 * 知识点详情的**数据库行**，只在 Mapper 和 Service 之间流转，不对外。
 *
 * 为什么不直接用 KnowledgePointDetail 接：
 * 那里面 chunk_ids / entity_names 是 List<String>，而 SQL 里是 BIGINT[] / TEXT[]，
 * MyBatis 没有内置映射（要么引 TypeHandler，要么用 array_to_string 拼成字符串）。
 * 选了后者，于是需要一个 String 字段的中间对象来承接，再在 Service 里切开。
 *
 * 这个类不加 @JsonNaming：它不会被序列化出去。
 */
@Data
public class KnowledgePointRaw {

    private String id;
    private String title;
    private String breadcrumb;
    private String subject;
    private Boolean isQuestion;
    private Integer chunkCount;
    private Integer charCount;
    private Long documentId;
    private String answer;
    private String docName;
    /** 在文档内的起始序号，用于算前后篇 */
    private Integer ordinalStart;

    /** 逗号拼接的 chunk id，如 "453,454" */
    private String chunkIds;
    /** '||' 拼接的实体名（实体名里可能有逗号，不能用逗号分隔） */
    private String entityNames;
}
