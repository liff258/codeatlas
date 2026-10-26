package com.codeatlas.controller;

import com.codeatlas.common.Result;
import com.codeatlas.dto.ChunkDetailView;
import com.codeatlas.dto.DocumentView;
import com.codeatlas.dto.EvalRunView;
import com.codeatlas.dto.FeedbackRequest;
import com.codeatlas.dto.SubjectView;
import com.codeatlas.dto.TraceView;
import com.codeatlas.service.CatalogService;
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
 * 没有实现的两个（见 README 的接口状态表）：
 * - POST /api/documents   文件上传要落盘 + 异步入库，当前用 scripts/ingest.py 批量入库
 * - GET  /api/graph/*     全库图谱需要离线抽取实体关系，entity/relation 表还是空的
 * 这两个宁可标成未实现，也不做一个假接口出来。
 */
@RestController
@RequestMapping("/api")
@RequiredArgsConstructor
public class CatalogController {

    private final CatalogService catalogService;

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

    @PostMapping("/feedback")
    public Result<Void> feedback(@Valid @RequestBody FeedbackRequest req) {
        catalogService.addFeedback(req);
        return Result.ok();
    }
}
