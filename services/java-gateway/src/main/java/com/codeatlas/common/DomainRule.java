package com.codeatlas.common;

/**
 * 跨域判定规则。
 *
 * 抽成公共类是因为它现在有三个调用方（请求时图谱、全库图谱、实体详情），
 * 三处必须给出同一个答案。规则本身只有一行，但「common 算不算跨域」这个判断
 * 一旦有一处写错，界面上就会出现假边——而演示时指着假边讲是最致命的。
 *
 * 规则：两端都必须是**已知域**，且不同。`common` 表示「未归类」，
 * 拿它和任何域比较都会得到"不同"，于是凭空造出跨域边。
 */
public final class DomainRule {

    private static final String UNKNOWN = "common";

    private DomainRule() {
    }

    public static boolean isCross(String domainA, String domainB) {
        boolean bothKnown = domainA != null && domainB != null
                && !UNKNOWN.equals(domainA) && !UNKNOWN.equals(domainB);
        return bothKnown && !domainA.equals(domainB);
    }
}
