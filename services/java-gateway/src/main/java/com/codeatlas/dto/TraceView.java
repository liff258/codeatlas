package com.codeatlas.dto;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import lombok.Data;

import java.math.BigDecimal;
import java.util.List;

/**
 * 一次问答的完整轨迹（契约 components/schemas/Trace）。
 *
 * 用途：前端「回放思考过程」——点开历史消息，能看到当时每一步发生了什么、
 * 每步花了多久、哪一步降级了。这比看一堆日志直观得多，
 * 也是被问"你这步为什么慢"时最省事的回答方式。
 */
@Data
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public class TraceView {

    private String traceId;
    private String question;
    private String answer;
    private String intent;
    private BigDecimal coverage;
    private Integer rewriteCount;
    private String stopReason;
    private Integer latencyMs;
    private List<TraceStepView> steps;
}
