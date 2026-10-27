package com.codeatlas.dto;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import lombok.Data;

import java.util.List;

/**
 * 分页包装（契约 components/schemas/PageResult）。
 *
 * hasMore 由服务层算，不让前端自己用 total/page/size 推——
 * 边界条件（最后一页刚好整除）很容易推错，服务端算一次更省事。
 */
@Data
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public class PageResult<T> {

    private List<T> items;
    private long total;
    private int page;
    private int size;
    private boolean hasMore;

    public static <T> PageResult<T> of(List<T> items, long total, int page, int size) {
        PageResult<T> r = new PageResult<>();
        r.items = items;
        r.total = total;
        r.page = page;
        r.size = size;
        r.hasMore = (long) page * size < total;
        return r;
    }
}
