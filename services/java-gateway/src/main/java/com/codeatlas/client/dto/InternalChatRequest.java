package com.codeatlas.client.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;

/**
 * 调用 Python /internal/agent/stream 的请求体。
 * 字段名与 contracts/openapi.yaml 的 InternalChatRequest 一一对应（snake_case）。
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class InternalChatRequest {

    @JsonProperty("trace_id")
    private String traceId;

    @JsonProperty("session_id")
    private Long sessionId;

    @JsonProperty("question")
    private String question;

    @JsonProperty("history")
    private List<HistoryItem> history;

    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class HistoryItem {
        private String role;
        private String content;
    }
}
