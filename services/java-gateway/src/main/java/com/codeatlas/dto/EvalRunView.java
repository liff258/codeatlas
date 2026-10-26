package com.codeatlas.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import lombok.Data;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/**
 * 一次评测的汇总（契约 components/schemas/EvalRun）。
 *
 * 由 scripts/eval_retrieval.py 跑完写入，每种检索模式一行——
 * 四种模式的对比才是这张表的价值，合成一行就只剩最终数字了。
 */
@Data
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public class EvalRunView {

    private Long id;
    private String name;

    /**
     * 契约里是 recall_at_5（数字前有下划线）。
     *
     * 全局的 snake_case 策略处理不了这个位置——{@code recallAt5} 会被转成
     * {@code recall_at5}，少一个下划线，前端按契约取值就是 undefined。
     * 这个坑是 JsonNamingTest 抓出来的，不是靠肉眼发现的。
     */
    @JsonProperty("recall_at_5")
    private BigDecimal recallAt5;

    private BigDecimal citationAccuracy;
    private BigDecimal noSourceRate;
    private Integer caseCount;
    private OffsetDateTime createdAt;
}
