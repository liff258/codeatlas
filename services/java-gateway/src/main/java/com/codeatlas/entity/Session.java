package com.codeatlas.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import lombok.Data;

import java.time.OffsetDateTime;

/**
 * 会话。表所有权：Java 写，Python 不碰。
 */
@Data
// 契约里字段是 snake_case（created_at / session_id），Java 字段是驼峰。
// 不加这个注解，实际返回 createdAt——前端按契约取值拿到 undefined。
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
@TableName("session")
public class Session {

    @TableId(type = IdType.AUTO)
    private Long id;

    private String userId;

    private String title;

    private OffsetDateTime createdAt;

    private OffsetDateTime updatedAt;
}
