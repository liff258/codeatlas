package com.codeatlas.controller;

import com.codeatlas.common.Result;
import com.codeatlas.dto.ChunkDetailView;
import com.codeatlas.dto.DocumentView;
import com.codeatlas.dto.EvalRunView;
import com.codeatlas.dto.FeedbackRequest;
import com.codeatlas.dto.GraphDataView;
import com.codeatlas.dto.SubjectView;
import com.codeatlas.dto.TraceView;
import com.codeatlas.service.CatalogService;
import com.codeatlas.service.GraphService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * 知识库与轨迹的只读接口 + 两个写操作。
 *
 * 这些端点在契约里一直写着，之前没实现——文档列表、学科分布、引用原文、
 * 轨迹回放都属于"产品该有的东西"，缺了它们，界面之外的部分就全是黑盒。
 *
 * 没实现的两个（见 README 的接口状态表）：
 * - POST /api/documents   文件上传要落盘 + 异步入库，当前用 scripts/ingest.py 批量入库
 * - POST /api/eval/runs   评测结果由脚本直接写库，不需要 HTTP 入口
 * 宁可标成未实现，也不做一个假接口出来。
 */
@RestController
@RequestMapping("/api")
@RequiredArgsConstructor
public class CatalogController {

    private final CatalogService catalogService;
    private final GraphService graphService;

    @GetMapping("/subjects")
    public Result<List<SubjectView>> subjects() {
        return Result.ok(catalogService.listSubjects());
    }

    @GetMapping("/documents")
    public Result<List<DocumentView>> documents(
            @RequestParam(required = false) String status) {
        return Result.ok(catalogService.listDocuments(status));
    }

    @DeleteMapping("/documents/{docId}")
    public Result<Void> deleteDocument(@PathVariable long docId) {
        catalogService.deleteDocument(docId);
        return Result.ok();
    }

    /** 引用角标点开看原文走这个接口。chunkId 支持 {@code c_102} 和 {@code 102} */
    @GetMapping("/chunks/{chunkId}")
    public Result<ChunkDetailView> chunk(@PathVariable String chunkId) {
        return Result.ok(catalogService.getChunk(chunkId));
    }

    @GetMapping("/traces/{traceId}")
    public Result<TraceView> trace(@PathVariable String traceId) {
        return Result.ok(catalogService.getTrace(traceId));
    }

    @GetMapping("/eval/runs")
    public Result<List<EvalRunView>> evalRuns() {
        return Result.ok(catalogService.listEvalRuns());
    }

    /** 全库图谱：按度数取核心节点。传 subject 只看某个学科 */
    @GetMapping("/graph/overview")
    public Result<GraphDataView> graphOverview(
            @RequestParam(required = false) Integer limit,
            @RequestParam(required = false) String subject) {
        return Result.ok(graphService.overview(limit, subject));
    }

    /** 以某个概念为中心看它的邻居，depth 支持 1~2 跳 */
    @GetMapping("/graph/neighbors")
    public Result<GraphDataView> graphNeighbors(
            @RequestParam String entity,
            @RequestParam(required = false) Integer depth) {
        return Result.ok(graphService.neighbors(entity, depth));
    }

    @PostMapping("/feedback")
    public Result<Void> feedback(@Valid @RequestBody FeedbackRequest req) {
        catalogService.addFeedback(req);
        return Result.ok();
    }
}
