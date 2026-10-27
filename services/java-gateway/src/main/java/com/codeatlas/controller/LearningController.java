package com.codeatlas.controller;

import com.codeatlas.common.Result;
import com.codeatlas.dto.EntityDetail;
import com.codeatlas.dto.KnowledgePointBrief;
import com.codeatlas.dto.KnowledgePointDetail;
import com.codeatlas.dto.PageResult;
import com.codeatlas.service.LearningService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * 知识平台接口：板块页、知识点详情、面试题库、实体详情。
 *
 * 题库没有单独一套查询，就是 `knowledge-points` 的 `type=question`。
 * 单独留一个 `/api/questions` 路径只是让前端语义更直白，
 * 两套分页逻辑迟早会走偏。
 */
@RestController
@RequestMapping("/api")
@RequiredArgsConstructor
public class LearningController {

    private final LearningService learningService;

    /** 板块页 / 题库页共用。type=question 只看面试题 */
    @GetMapping("/knowledge-points")
    public Result<PageResult<KnowledgePointBrief>> knowledgePoints(
            @RequestParam(required = false) String subject,
            @RequestParam(required = false, defaultValue = "all") String type,
            @RequestParam(required = false) String q,
            @RequestParam(required = false) Integer page,
            @RequestParam(required = false) Integer size) {
        return Result.ok(learningService.list(subject, type, q, page, size));
    }

    @GetMapping("/knowledge-points/{id}")
    public Result<KnowledgePointDetail> knowledgePoint(@PathVariable String id) {
        return Result.ok(learningService.detail(id));
    }

    /** 题库：等价于 knowledge-points?type=question */
    @GetMapping("/questions")
    public Result<PageResult<KnowledgePointBrief>> questions(
            @RequestParam(required = false) String subject,
            @RequestParam(required = false) String q,
            @RequestParam(required = false) Integer page,
            @RequestParam(required = false) Integer size) {
        return Result.ok(learningService.list(subject, "question", q, page, size));
    }

    /**
     * 实体详情。用 query 参数而不是 path：实体名可能含 `+`、`#`、`/`
     * （如 `B+ 树`、`C++`），放 path 里编码问题很多。
     */
    @GetMapping("/entities")
    public Result<EntityDetail> entity(@RequestParam String name) {
        return Result.ok(learningService.entity(name));
    }
}
