package com.codeatlas.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.OffsetDateTime;

/**
 * 会话。表所有权：Java 写，Python 不碰。
 */
@Data
@TableName("session")
public class Session {

    @TableId(type = IdType.AUTO)
    private Long id;

    private String userId;

    private String title;

    private OffsetDateTime createdAt;

    private OffsetDateTime updatedAt;
}
