package com.codeatlas.controller;

import com.codeatlas.common.Result;
import com.codeatlas.entity.Message;
import com.codeatlas.entity.Session;
import com.codeatlas.service.SessionService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/sessions")
@RequiredArgsConstructor
public class SessionController {

    private final SessionService sessionService;

    @GetMapping
    public Result<List<Session>> list(
            @RequestHeader(value = "X-User-Id", required = false, defaultValue = "local") String userId,
            @RequestParam(defaultValue = "20") int limit) {
        return Result.ok(sessionService.listSessions(userId, limit));
    }

    @PostMapping
    public Result<Session> create(
            @RequestHeader(value = "X-User-Id", required = false, defaultValue = "local") String userId,
            @RequestBody(required = false) Map<String, String> body) {
        String title = body == null ? null : body.get("title");
        return Result.ok(sessionService.createSession(userId, title));
    }

    @GetMapping("/{sessionId}/messages")
    public Result<List<Message>> messages(@PathVariable Long sessionId) {
        return Result.ok(sessionService.listMessages(sessionId));
    }
}
