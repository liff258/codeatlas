package com.codeatlas.controller;

import com.codeatlas.client.AgentClient;
import com.codeatlas.common.Result;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import reactor.core.publisher.Mono;

import javax.sql.DataSource;
import java.sql.Connection;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 健康检查。同时探测数据库与 Python Agent，前端据此显示服务状态。
 * 任一依赖不可用都不返回 5xx，而是把状态写进 data，让调用方自己决定怎么展示。
 */
@Slf4j
@RestController
@RequestMapping("/api")
@RequiredArgsConstructor
public class HealthController {

    private final AgentClient agentClient;
    private final DataSource dataSource;

    @GetMapping("/health")
    public Mono<Result<Map<String, Object>>> health() {
        return agentClient.health().map(agent -> {
            Map<String, Object> data = new LinkedHashMap<>();
            data.put("gateway", "up");
            data.put("db", probeDb());
            data.put("agent", agent.getOrDefault("status", "down"));
            data.put("agent_mode", agent.getOrDefault("mode", "unknown"));
            data.put("agent_db", agent.getOrDefault("db", "unknown"));
            return Result.ok(data);
        });
    }

    private String probeDb() {
        try (Connection conn = dataSource.getConnection()) {
            return conn.isValid(2) ? "ok" : "invalid";
        } catch (Exception e) {
            log.warn("db health probe failed: {}", e.toString());
            return "down";
        }
    }
}
