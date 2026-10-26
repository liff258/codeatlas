package com.codeatlas.common;

import lombok.Getter;

/**
 * 可预期的业务错误（找不到、参数不合法）。
 *
 * 为什么不用 IllegalArgumentException 顶替：
 * 那个已经被映射成 400，而"切片不存在"应该是 404——前端要按状态码决定
 * 是提示"数据被删了"还是"你参数写错了"，混在一起就没法区分。
 */
@Getter
public class BizException extends RuntimeException {

    private final int code;

    public BizException(int code, String message) {
        super(message);
        this.code = code;
    }
}
