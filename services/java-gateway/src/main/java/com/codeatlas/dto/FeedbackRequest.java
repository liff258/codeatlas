package com.codeatlas.dto;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotNull;
import lombok.Data;

/**
 * 答案反馈（契约 POST /api/feedback）。
 *
 * rating 只允许 -1 / 1：这个接口是给"点踩时选原因"用的，
 * 不做五星评价——五星分布在小样本下没有统计意义，
 * 而「有没有出处」这种二值判断能直接驱动改进。
 */
@Data
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public class FeedbackRequest {

    @NotNull
    private Long messageId;

    /** 1 = 有用，-1 = 没用 */
    @NotNull
    @Min(-1)
    @Max(1)
    private Integer rating;

    /** 无出处 / 答非所问 / 引用错误 / 其他 */
    private String reason;

    private String comment;
}
