package com.codeatlas.service;

import com.codeatlas.common.BizException;
import com.codeatlas.dto.ChunkDetailView;
import com.codeatlas.dto.DocumentView;
import com.codeatlas.dto.EvalRunView;
import com.codeatlas.dto.FeedbackRequest;
import com.codeatlas.dto.SubjectView;
import com.codeatlas.dto.TraceStepView;
import com.codeatlas.dto.TraceView;
import com.codeatlas.mapper.CatalogMapper;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;

/**
 * 目录类查询：学科、文档、切片、轨迹、评测。
 *
 * 这一层的价值不是"转发 SQL"，而是把数据库的存储形态翻译成契约要求的形态：
 * chunk 的对外 id 是 {@code c_102}、knowledge_points 存成数组但对外是列表、
 * step 的 payload 存 JSONB 但对外是对象。
 * 这些转换散在 controller 里会让 controller 变厚，也不可复用。
 */
@Service
@RequiredArgsConstructor
public class CatalogService {

    private final CatalogMapper catalogMapper;
    private final ObjectMapper objectMapper;

    public List<SubjectView> listSubjects() {
        return catalogMapper.listSubjects();
    }

    public List<DocumentView> listDocuments(String status) {
        String normalized = (status == null || status.isBlank()) ? null : status.trim();
        return catalogMapper.listDocuments(normalized);
    }

    /**
     * 按对外 id 取切片。接受 {@code c_102} 和 {@code 102} 两种写法。
     *
     * 为什么两种都收：SSE 的 citation.chunk_ids 里是 {@code c_102}，
     * 而人手工 curl 调试时更可能直接敲数字。让接口容错比让调用方记住规则便宜。
     */
    public ChunkDetailView getChunk(String chunkRef) {
        long id = parseChunkId(chunkRef);
        Map<String, Object> row = catalogMapper.getChunk(id);
        if (row == null) {
            throw new BizException(404, "切片不存在：" + chunkRef);
        }

        ChunkDetailView view = new ChunkDetailView();
        view.setId("c_" + id);
        view.setDocumentId(asLong(row.get("document_id")));
        view.setDocName(asString(row.get("doc_name")));
        view.setHeadingPath(asString(row.get("heading_path")));
        view.setContent(asString(row.get("content")));
        view.setSubject(asString(row.get("subject")));
        view.setKnowledgePoints(splitKnowledgePoints(asString(row.get("knowledge_points"))));
        return view;
    }

    public TraceView getTrace(String traceId) {
        TraceView trace = catalogMapper.getTrace(traceId);
        if (trace == null) {
            throw new BizException(404, "轨迹不存在：" + traceId);
        }
        trace.setSteps(mapSteps(catalogMapper.listSteps(traceId)));
        return trace;
    }

    public List<EvalRunView> listEvalRuns() {
        return catalogMapper.listEvalRuns();
    }

    @Transactional
    public void addFeedback(FeedbackRequest req) {
        catalogMapper.insertFeedback(req.getMessageId(), req.getRating(), req.getReason(), req.getComment());
    }

    @Transactional
    public void deleteDocument(long docId) {
        int affected = catalogMapper.deleteDocument(docId);
        if (affected == 0) {
            throw new BizException(404, "文档不存在：" + docId);
        }
    }

    // ---------------------------------------------------------------- 转换

    private List<TraceStepView> mapSteps(List<Map<String, Object>> rows) {
        List<TraceStepView> steps = new ArrayList<>(rows.size());
        for (Map<String, Object> row : rows) {
            TraceStepView step = new TraceStepView();
            step.setSeq(asInt(row.get("seq")));
            step.setNode(asString(row.get("node")));
            step.setStatus(asString(row.get("status")));
            step.setDurationMs(asInt(row.get("duration_ms")));
            step.setPayload(parseJson(asString(row.get("payload"))));
            steps.add(step);
        }
        return steps;
    }

    /** payload 解析失败给空对象，不让一条脏数据把整个回放打挂 */
    private Map<String, Object> parseJson(String text) {
        if (text == null || text.isBlank()) {
            return Map.of();
        }
        try {
            return objectMapper.readValue(text, new TypeReference<Map<String, Object>>() {});
        } catch (Exception e) {
            return Map.of("raw", text);
        }
    }

    private List<String> splitKnowledgePoints(String joined) {
        if (joined == null || joined.isBlank()) {
            return List.of();
        }
        return Arrays.stream(joined.split("\\|\\|"))
                .map(String::trim)
                .filter(s -> !s.isEmpty())
                .toList();
    }

    private long parseChunkId(String chunkRef) {
        if (chunkRef == null || chunkRef.isBlank()) {
            throw new BizException(400, "切片 id 不能为空");
        }
        String digits = chunkRef.startsWith("c_") ? chunkRef.substring(2) : chunkRef;
        try {
            return Long.parseLong(digits);
        } catch (NumberFormatException e) {
            throw new BizException(400, "切片 id 格式不对：" + chunkRef);
        }
    }

    private static Long asLong(Object v) {
        return v == null ? null : ((Number) v).longValue();
    }

    private static Integer asInt(Object v) {
        return v == null ? null : ((Number) v).intValue();
    }

    private static String asString(Object v) {
        return v == null ? null : String.valueOf(v);
    }
}
