package com.codeatlas.dto;

import com.fasterxml.jackson.annotation.JsonAlias;
import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import lombok.Data;

@Data
public class ChatRequest {

    /**
     * 不传则自动新建会话。
     *
     * 显式声明 JSON 名称为 session_id：契约（contracts/openapi.yaml）和前端
     * （web/src/lib/sse.ts 的 ChatRequestBody）都用下划线写法，而 Java 字段是驼峰。
     * 不做映射的话，前端传来的 session_id 会被静默忽略——表现为「每次提问都新建会话，
     * 历史对话丢失」，且不报错，很难发现。
     *
     * 同时保留 sessionId 作为别名，方便手工 curl 调试时用驼峰写法。
     */
    @JsonProperty("session_id")
    @JsonAlias("sessionId")
    private Long sessionId;

    @NotBlank(message = "问题不能为空")
    @Size(max = 2000, message = "问题最长 2000 字")
    private String question;

    private Boolean stream = Boolean.TRUE;
}
