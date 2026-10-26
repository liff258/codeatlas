package com.codeatlas.dto;

import com.fasterxml.jackson.annotation.JsonIgnore;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import lombok.Data;

import java.math.BigDecimal;

/**
 * 图谱边（契约 components/schemas/GraphEdge）。
 *
 * crossDomain 由服务层按两端 domain 比较得出，**不从数据库读**——
 * 和请求时图谱的规则保持一致，两处用不同规则会让两个界面互相矛盾。
 */
@Data
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public class GraphEdgeView {

    private String source;
    private String target;
    private String rel;
    private BigDecimal weight;
    private Boolean crossDomain;

    /**
     * 两端各自的域。只用于服务层算 crossDomain，不返回给前端
     * （契约里没有这两个字段，多返回会让前端以为它们是接口的一部分）。
     */
    @JsonIgnore
    private String srcDomain;

    @JsonIgnore
    private String dstDomain;
}
