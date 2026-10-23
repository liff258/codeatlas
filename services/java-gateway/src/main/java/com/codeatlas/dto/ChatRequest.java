package com.codeatlas.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import lombok.Data;

@Data
public class ChatRequest {

    /** 不传则自动新建会话 */
    private Long sessionId;

    @NotBlank(message = "问题不能为空")
    @Size(max = 2000, message = "问题最长 2000 字")
    private String question;

    private Boolean stream = Boolean.TRUE;
}
