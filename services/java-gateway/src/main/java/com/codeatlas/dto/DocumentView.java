package com.codeatlas.dto;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import lombok.Data;

import java.time.OffsetDateTime;

/**
 * 文档列表项（契约 components/schemas/Document）。
 *
 * 注意不返回 storage_path / content_hash：前者是服务器本地路径，
 * 后者是内部去重用的指纹，都不该出现在 API 响应里。
 */
@Data
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public class DocumentView {

    private Long id;
    private String filename;
    private String fileType;
    private Long sizeBytes;
    private String status;
    private Integer chunkCount;
    private String errorMsg;
    private OffsetDateTime uploadedAt;
}
