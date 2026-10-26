package com.codeatlas.dto;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import lombok.Data;

import java.util.Map;

/**
 * 一次执行中的单个节点（契约 components/schemas/Trace.steps）。
 *
 * 数据来源是 agent_step 表，由 Python 在每次回答结束时写入。
 */
@Data
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public class TraceStepView {

    private Integer seq;
    private String node;
    private String status;
    /** agent_step.payload 是 JSONB，查出来转成 Map 直接透给前端 */
    private Map<String, Object> payload;
    private Integer durationMs;
}
