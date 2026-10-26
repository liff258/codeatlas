package com.codeatlas.dto;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import lombok.Data;

import java.util.List;

/**
 * 切片详情（契约 components/schemas/ChunkDetail）。
 *
 * 这是「引用角标点开看原文」的数据来源。id 对外是 {@code c_102} 这种带前缀的形式
 * （和 SSE 里 citation.chunk_ids 保持一致），内部才是 BIGINT。
 */
@Data
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public class ChunkDetailView {

    private String id;
    private Long documentId;
    private String docName;
    private String headingPath;
    private String content;
    private String subject;
    private List<String> knowledgePoints;
}
