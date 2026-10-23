package com.codeatlas.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.OffsetDateTime;

/**
 * 消息。表所有权：Java 写，Python 不碰。
 */
@Data
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
