package com.codeatlas.controller;

import com.codeatlas.dto.ChatRequest;
import com.codeatlas.service.ChatService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

@RestController
@RequestMapping("/api")
@RequiredArgsConstructor
public class ChatController {

    private final ChatService chatService;

    /**
     * 提问并流式接收答案。
     * 事件协议见 contracts/sse-events.md。
     */
    @PostMapping(value = "/chat/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter stream(
            @Valid @RequestBody ChatRequest request,
            @RequestHeader(value = "X-User-Id", required = false, defaultValue = "local") String userId) {
        return chatService.stream(request, userId);
    }
}
