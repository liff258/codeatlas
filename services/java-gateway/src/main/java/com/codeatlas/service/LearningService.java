package com.codeatlas.service;

import com.codeatlas.common.BizException;
import com.codeatlas.common.DomainRule;
import com.codeatlas.dto.EntityDetail;
import com.codeatlas.dto.GraphEdgeView;
import com.codeatlas.dto.GraphNodeView;
import com.codeatlas.dto.KnowledgePointBrief;
import com.codeatlas.dto.KnowledgePointDetail;
import com.codeatlas.dto.KnowledgePointRaw;
import com.codeatlas.dto.PageResult;
import com.codeatlas.mapper.LearningMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

/**
 * 知识平台：知识点与实体。
 *
 * 这一层做三件 Mapper 做不了的事：
 *   1. 分页参数夹紧（page ≥ 1，size 1~50）——不夹紧的话 size=10000 能把库拖死
 *   2. 存储形态转换（"1,2,3" → ["c_1","c_2","c_3"]，"A||B" → ["A","B"]）
 *   3. 组装详情页需要的周边数据（相关推荐、前后篇、涉及实体）
 */
@Service
@RequiredArgsConstructor
public class LearningService {

    private static final int MAX_SIZE = 50;
    private static final int DEFAULT_SIZE = 20;
    private static final int RELATED_LIMIT = 6;
    private static final int MENTION_LIMIT = 6;
    private static final int RELATION_LIMIT = 20;

    private final LearningMapper learningMapper;

    public PageResult<KnowledgePointBrief> list(String subject, String type, String q,
                                                Integer page, Integer size) {
        int p = clamp(page == null ? 1 : page, 1, Integer.MAX_VALUE);
        int s = clamp(size == null ? DEFAULT_SIZE : size, 1, MAX_SIZE);
        String subj = blankToNull(subject);
        String kind = normalizeType(type);
        String kw = blankToNull(q);

        long total = learningMapper.countKnowledgePoints(subj, kind, kw);
        List<KnowledgePointBrief> items = total == 0
                ? List.of()
                : learningMapper.listKnowledgePoints(subj, kind, kw, s, (p - 1) * s);
        return PageResult.of(items, total, p, s);
    }

    public KnowledgePointDetail detail(String id) {
        KnowledgePointRaw raw = learningMapper.getKnowledgePoint(id);
        if (raw == null) {
            throw new BizException(404, "知识点不存在：" + id);
        }

        KnowledgePointDetail detail = new KnowledgePointDetail();
        detail.setId(raw.getId());
        detail.setTitle(raw.getTitle());
        detail.setBreadcrumb(raw.getBreadcrumb());
        detail.setSubject(raw.getSubject());
        detail.setIsQuestion(raw.getIsQuestion());
        detail.setChunkCount(raw.getChunkCount());
        detail.setCharCount(raw.getCharCount());
        detail.setDocumentId(raw.getDocumentId());
        detail.setDocName(raw.getDocName());
        detail.setAnswer(raw.getAnswer());
        detail.setChunkIds(splitChunkIds(raw.getChunkIds()));

        // 正文前 140 字当 preview，和列表接口保持一致
        String answer = raw.getAnswer() == null ? "" : raw.getAnswer();
        detail.setPreview(answer.length() > 140 ? answer.substring(0, 140) : answer);

        List<String> names = splitEntityNames(raw.getEntityNames());
        detail.setEntities(names.isEmpty() ? List.of() : learningMapper.entitiesByNames(names));
        detail.setRelated(learningMapper.relatedKnowledgePoints(id, RELATED_LIMIT));

        int ordinal = raw.getOrdinalStart() == null ? 0 : raw.getOrdinalStart();
        detail.setPrev(learningMapper.prevKnowledgePoint(raw.getDocumentId(), ordinal));
        detail.setNext(learningMapper.nextKnowledgePoint(raw.getDocumentId(), ordinal));
        return detail;
    }

    public EntityDetail entity(String name) {
        String key = blankToNull(name);
        if (key == null) {
            throw new BizException(400, "name 不能为空");
        }

        EntityDetail detail = learningMapper.getEntity(key);
        if (detail == null) {
            throw new BizException(404, "实体不存在：" + key);
        }

        List<EntityDetail.Mention> mentions = learningMapper.listMentions(key, MENTION_LIMIT);
        // 原文片段常常以 `### 4.1 xxx` 开头，直接展示很难看，
        // 而且会让「描述」变成一行标题而不是一句话
        for (EntityDetail.Mention m : mentions) {
            m.setSnippet(cleanSnippet(m.getSnippet()));
        }
        detail.setMentions(mentions);

        // entity.description 全部是 NULL，用首条提及的前两句兜底。
        // 必须标 extracted——这是原文摘录，不是权威定义。
        if (detail.getDescription() == null || detail.getDescription().isBlank()) {
            detail.setDescription(firstTwoSentences(mentions));
            detail.setDescriptionSource("extracted");
        } else {
            detail.setDescriptionSource("curated");
        }

        List<GraphEdgeView> relations = learningMapper.entityRelations(key, RELATION_LIMIT);
        for (GraphEdgeView e : relations) {
            e.setCrossDomain(DomainRule.isCross(e.getSrcDomain(), e.getDstDomain()));
        }
        detail.setRelations(relations);
        return detail;
    }

    // ---------------------------------------------------------------- 转换

    /** "1,2,3" → ["c_1","c_2","c_3"]。对外 id 一律带 c_ 前缀，和 citation 一致 */
    private List<String> splitChunkIds(String joined) {
        if (joined == null || joined.isBlank()) {
            return List.of();
        }
        List<String> out = new ArrayList<>();
        for (String part : joined.split(",")) {
            String t = part.trim();
            if (!t.isEmpty()) {
                out.add("c_" + t);
            }
        }
        return out;
    }

    private List<String> splitEntityNames(String joined) {
        if (joined == null || joined.isBlank()) {
            return List.of();
        }
        return Arrays.stream(joined.split("\\|\\|"))
                .map(String::trim)
                .filter(s -> !s.isEmpty())
                .toList();
    }

    /**
     * 从提及片段里取前两句当描述。
     *
     * 只取两句：长了会变成整段摘抄，而实体页要的是"这是什么"的一句话概述，
     * 完整内容往下滚就有 mentions 列表。
     */
    private String firstTwoSentences(List<EntityDetail.Mention> mentions) {
        if (mentions == null || mentions.isEmpty()) {
            return null;
        }
        String text = mentions.get(0).getSnippet();
        if (text == null || text.isBlank()) {
            return null;
        }
        String[] parts = text.split("(?<=[。！？!?])");
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < Math.min(2, parts.length); i++) {
            sb.append(parts[i]);
        }
        String out = sb.toString().trim();
        return out.length() > 200 ? out.substring(0, 200) : out;
    }

    /**
     * 清理原文片段：去标题、去围栏标记。
     *
     * 语料是 markdown，200 字的截断经常正好切在代码块里，
     * 界面上就会看到孤零零的 ` ```java ` 和半截代码。
     * 这里把围栏行去掉——片段只是「让你知道这段在讲什么」，
     * 不需要保留代码块结构。
     */
    private String cleanSnippet(String text) {
        String t = stripLeadingHeading(text);
        if (t == null) {
            return null;
        }
        StringBuilder sb = new StringBuilder();
        for (String line : t.split("\n", -1)) {
            // 围栏可能带引用前缀（`> ```java`），先剥掉 > 和空白再判断
            if (line.trim().replaceAll("^[>\\s]+", "").startsWith("```")) {
                continue;
            }
            sb.append(line).append('\n');
        }
        return sb.toString().trim();
    }

    /**
     * 去掉开头的 markdown 标题行和多余空行。
     *
     * 语料是 markdown，chunk 正文往往以 `### 4.1 xxx` 起头。
     * 这些标记对渲染有用，但当作「实体描述」时只会让人看到一行标题。
     */
    private String stripLeadingHeading(String text) {
        if (text == null) {
            return null;
        }
        String[] lines = text.split("\n", -1);
        int i = 0;
        while (i < lines.length) {
            String line = lines[i].trim();
            if (line.isEmpty() || line.matches("^#{1,6}\\s+.*")) {
                i++;
                continue;
            }
            break;
        }
        return i >= lines.length ? text.trim() : String.join("\n", Arrays.copyOfRange(lines, i, lines.length)).trim();
    }

    /** type 只接受 all / question，其余一律当 all——避免拼错参数导致空列表 */
    private String normalizeType(String type) {
        if (type == null || type.isBlank()) {
            return null;
        }
        String t = type.trim().toLowerCase();
        return "question".equals(t) ? "question" : null;
    }

    private static String blankToNull(String s) {
        return (s == null || s.isBlank()) ? null : s.trim();
    }

    private static int clamp(int v, int lo, int hi) {
        return Math.max(lo, Math.min(hi, v));
    }
}
