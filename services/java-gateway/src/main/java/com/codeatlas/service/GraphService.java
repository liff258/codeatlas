package com.codeatlas.service;

import com.codeatlas.common.BizException;
import com.codeatlas.dto.GraphDataView;
import com.codeatlas.dto.GraphEdgeView;
import com.codeatlas.dto.GraphNodeView;
import com.codeatlas.mapper.GraphMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.List;

/**
 * 全库知识图谱。
 *
 * 两个设计决定，和请求时生成的图谱保持一致：
 *
 * 1. **cross_domain 由代码算**（比较两端 domain），不从数据库读。
 *    两处用不同规则的话，全库图和单题图会互相矛盾——那比只有一种图更糟。
 * 2. **domain 为 common 表示"未归类"而不是"另一个域"**。
 *    把它算成跨域会造出假边，演示时指着假边讲是致命的。
 */
@Service
@RequiredArgsConstructor
public class GraphService {

    private static final int MAX_LIMIT = 300;
    private static final int DEFAULT_LIMIT = 120;

    private final GraphMapper graphMapper;

    public GraphDataView overview(Integer limit, String subject) {
        int n = clamp(limit == null ? DEFAULT_LIMIT : limit, 1, MAX_LIMIT);
        String subj = (subject == null || subject.isBlank()) ? null : subject.trim();

        List<GraphNodeView> nodes = graphMapper.topNodes(n, subj);
        List<GraphEdgeView> edges = graphMapper.edgesAmongTop(n, subj);
        edges.forEach(this::markCrossDomain);

        GraphDataView view = new GraphDataView();
        view.setNodes(nodes);
        view.setEdges(edges);
        // 实体比节点多就说明被截断了，前端据此提示"仅展示核心节点"
        view.setTruncated(graphMapper.countEntities() > nodes.size());
        return view;
    }

    public GraphDataView neighbors(String entity, Integer depth) {
        if (entity == null || entity.isBlank()) {
            throw new BizException(400, "entity 不能为空");
        }
        int d = clamp(depth == null ? 1 : depth, 1, 2);

        List<Long> ids = graphMapper.neighborIds(entity.trim(), d);
        if (ids.isEmpty()) {
            throw new BizException(404, "没有这个实体：" + entity);
        }

        List<GraphNodeView> nodes = graphMapper.nodesByIds(ids);
        List<GraphEdgeView> edges = graphMapper.edgesByIds(ids);
        edges.forEach(this::markCrossDomain);

        GraphDataView view = new GraphDataView();
        view.setNodes(nodes);
        view.setEdges(edges);
        view.setTruncated(false);
        return view;
    }

    /**
     * 跨域判定。两端都必须是已知域——common 是"没归类"，
     * 拿它和任何域比都会得到"不同"，于是造出假边。
     */
    private void markCrossDomain(GraphEdgeView e) {
        String a = e.getSrcDomain();
        String b = e.getDstDomain();
        boolean bothKnown = a != null && b != null
                && !"common".equals(a) && !"common".equals(b);
        e.setCrossDomain(bothKnown && !a.equals(b));
    }

    private static int clamp(int v, int lo, int hi) {
        return Math.max(lo, Math.min(hi, v));
    }
}
