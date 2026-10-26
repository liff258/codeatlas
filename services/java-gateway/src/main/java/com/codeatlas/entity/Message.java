package com.codeatlas.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import lombok.Data;

import java.time.OffsetDateTime;

/**
 * 消息。表所有权：Java 写，Python 不碰。
 */
@Data
// 契约里字段是 snake_case（created_at / session_id），Java 字段是驼峰。
// 不加这个注解，实际返回 createdAt——前端按契约取值拿到 undefined。
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
@TableName("message")
public class Message {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long sessionId;

    /** user / assistant / system */
    private String role;

    private String content;

    /** 助手消息关联的 trace，前端「回放思考过程」用 */
    private String traceId;

    private Long parentId;

    private OffsetDateTime createdAt;
}
