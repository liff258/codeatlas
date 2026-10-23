package com.codeatlas.service;

import com.codeatlas.client.AgentClient;
import com.codeatlas.client.dto.InternalChatRequest;
import com.codeatlas.config.AgentProperties;
import com.codeatlas.dto.ChatRequest;
import com.codeatlas.entity.Message;
import com.codeatlas.entity.Session;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.MediaType;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.stereotype.Service;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import reactor.core.Disposable;
import reactor.core.publisher.SignalType;

import java.io.IOException;
import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

/**
 * 问答编排：落库 + 调用 Agent + SSE 转发。
 *
 * 这是整个网关最容易翻车的地方，三个点必须守住：
 *
 * 1. **不攒批**：Python 每来一个事件就立刻 send，绝不 buffer 后统一发。
 * 2. **异常必须收尾**：无论出什么错，都要补发 error + done。
 *    否则前端状态机停在「正在思考」，演示时看起来就是卡死。
 * 3. **客户端断开要停上游**：SseEmitter.send 抛 IOException 说明浏览器走了，
 *    必须 dispose 订阅，否则 Python 那边会白跑完整个流程、白烧 token。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ChatService {

    private final AgentClient agentClient;
    private final SessionService sessionService;
    private final AgentProperties agentProperties;
    private final ObjectMapper objectMapper;

    public SseEmitter stream(ChatRequest request, String userId) {
        Session session = sessionService.getOrCreate(request.getSessionId(), userId, request.getQuestion());
        sessionService.saveUserMessage(session.getId(), request.getQuestion());

        List<InternalChatRequest.HistoryItem> history = buildHistory(session.getId());

        String traceId = "t_" + UUID.randomUUID().toString().replace("-", "").substring(0, 8);

        SseEmitter emitter = new SseEmitter(
                Duration.ofSeconds(agentProperties.getStreamTimeoutSeconds()).toMillis());

        Ctx ctx = new Ctx(session.getId(), traceId, emitter);

        InternalChatRequest internal = InternalChatRequest.builder()
                .traceId(traceId)
                .sessionId(session.getId())
                .question(request.getQuestion())
                .history(history)
                .build();

        emitter.onTimeout(() -> {
            log.warn("sse timeout | trace={}", traceId);
            ctx.stop();
            emitter.complete();
        });
        emitter.onError(e -> {
            log.info("sse error | trace={} | {}", traceId, e.toString());
            ctx.stop();
        });

        Disposable disposable = agentClient.stream(internal).subscribe(
                sse -> onEvent(sse, ctx),
                err -> onError(err, ctx),
                () -> onComplete(ctx)
        );
        ctx.subscription.set(disposable);

        return emitter;
    }

    // ------------------------------------------------------------------ 事件处理

    private void onEvent(ServerSentEvent<String> sse, Ctx ctx) {
        String name = sse.event();
        String data = sse.data();
        if (name == null || data == null) {
            return;
        }
        if (ctx.finished.get()) {
            return;
        }

        try {
            JsonNode node = objectMapper.readTree(data);
            if (node.has("seq")) {
                ctx.lastSeq = node.get("seq").asInt(ctx.lastSeq);
            }
            if ("token".equals(name) && node.has("text")) {
                ctx.answer.append(node.get("text").asText());
            }
            if ("done".equals(name)) {
                data = attachMessageId(data, ctx);
                ctx.finished.set(true);
            }
        } catch (Exception e) {
            // 解析失败不阻断转发：宁可让前端收到原始数据，也不要吞掉事件
            log.warn("event parse failed | trace={} | name={}", ctx.traceId, name, e);
        }

        send(ctx, name, data);
    }

    private void onError(Throwable err, Ctx ctx) {
        if (ctx.finished.getAndSet(true)) {
            return;
        }
        log.error("agent stream failed | trace={}", ctx.traceId, err);
        persistPartialAnswer(ctx);

        int seq = ctx.lastSeq + 1;
        String code = classify(err);
        send(ctx, "error", json(Map.of(
                "seq", seq,
                "trace_id", ctx.traceId,
                "ts", System.currentTimeMillis(),
                "code", code,
                "message", describe(err),
                "retryable", !"INTERNAL".equals(code)
        )));
        send(ctx, "done", json(Map.of(
                "seq", seq + 1,
                "trace_id", ctx.traceId,
                "ts", System.currentTimeMillis(),
                "stop_reason", "error",
                "coverage", 0.0,
                "rewrite_count", 0,
                "latency_ms", ctx.elapsedMs(),
                "usage", Map.of("input_tokens", 0, "output_tokens", 0, "cost_cny", 0.0),
                "insufficient_evidence", false
        )));
        ctx.emitter.complete();
    }

    private void onComplete(Ctx ctx) {
        if (ctx.finished.getAndSet(true)) {
            ctx.emitter.complete();
            return;
        }
        // 正常路径下 done 事件已经把 finished 置位，走到这里说明上游没发 done 就结束了
        log.warn("stream completed without done event | trace={}", ctx.traceId);
        persistPartialAnswer(ctx);
        int seq = ctx.lastSeq + 1;
        send(ctx, "done", json(Map.of(
                "seq", seq,
                "trace_id", ctx.traceId,
                "ts", System.currentTimeMillis(),
                "stop_reason", "error",
                "coverage", 0.0,
                "rewrite_count", 0,
                "latency_ms", ctx.elapsedMs(),
                "usage", Map.of("input_tokens", 0, "output_tokens", 0, "cost_cny", 0.0),
                "insufficient_evidence", false
        )));
        ctx.emitter.complete();
    }

    // ------------------------------------------------------------------ 落库

    /**
     * 在 done 事件里补上 message_id 并落库。
     * 为什么在 done 才落库：答案要等流结束才完整，提前插入只能拿到半截内容。
     */
    private String attachMessageId(String data, Ctx ctx) {
        String answer = ctx.answer.toString();
        if (answer.isBlank()) {
            return data;
        }
        try {
            Message saved = sessionService.saveAssistantMessage(ctx.sessionId, answer, ctx.traceId);
            ObjectNode node = (ObjectNode) objectMapper.readTree(data);
            node.put("message_id", saved.getId());
            return objectMapper.writeValueAsString(node);
        } catch (Exception e) {
            log.error("persist assistant message failed | trace={}", ctx.traceId, e);
            return data;
        }
    }

    private void persistPartialAnswer(Ctx ctx) {
        String answer = ctx.answer.toString();
        if (answer.isBlank() || ctx.persisted.getAndSet(true)) {
            return;
        }
        try {
            sessionService.saveAssistantMessage(ctx.sessionId, answer + "\n\n（回答中断）", ctx.traceId);
        } catch (Exception e) {
            log.error("persist partial answer failed | trace={}", ctx.traceId, e);
        }
    }

    // ------------------------------------------------------------------ 工具

    private void send(Ctx ctx, String name, String data) {
        if (ctx.closed.get()) {
            return;
        }
        try {
            // 用 TEXT_PLAIN 强制原样写出：换成 APPLICATION_JSON 会被 Jackson 再包一层引号
            ctx.emitter.send(SseEmitter.event().name(name).data(data, MediaType.TEXT_PLAIN));
        } catch (IOException | IllegalStateException e) {
            // 浏览器已经断开：立刻停上游，别让 Python 白跑
            log.info("client disconnected, stop upstream | trace={}", ctx.traceId);
            ctx.closed.set(true);
            ctx.stop();
        }
    }

    private List<InternalChatRequest.HistoryItem> buildHistory(Long sessionId) {
        List<Message> recent = sessionService.recentHistory(sessionId, 6);
        List<InternalChatRequest.HistoryItem> history = new ArrayList<>(recent.size());
        for (Message m : recent) {
            if ("system".equals(m.getRole())) {
                continue;
            }
            history.add(new InternalChatRequest.HistoryItem(m.getRole(), m.getContent()));
        }
        return history;
    }

    private String json(Map<String, Object> map) {
        try {
            return objectMapper.writeValueAsString(new LinkedHashMap<>(map));
        } catch (Exception e) {
            return "{}";
        }
    }

    private String classify(Throwable err) {
        String name = err.getClass().getSimpleName();
        String msg = err.getMessage() == null ? "" : err.getMessage();
        if (name.contains("Timeout") || msg.contains("timeout")) {
            return "LLM_TIMEOUT";
        }
        if (msg.contains("429") || msg.contains("rate")) {
            return "LLM_RATE_LIMIT";
        }
        return "INTERNAL";
    }

    private String describe(Throwable err) {
        String name = err.getClass().getSimpleName();
        if (name.contains("Timeout")) {
            return "Agent 响应超时";
        }
        if (name.contains("WebClientResponseException")) {
            return "Agent 服务返回错误：" + err.getMessage();
        }
        return "Agent 服务不可用";
    }

    // ------------------------------------------------------------------ 上下文

    /** 单次问答的可变状态。用对象承载，避免在 lambda 里捕获一堆局部变量。 */
    private static final class Ctx {
        final Long sessionId;
        final String traceId;
        final SseEmitter emitter;
        final StringBuilder answer = new StringBuilder();
        final AtomicReference<Disposable> subscription = new AtomicReference<>();
        final AtomicBoolean finished = new AtomicBoolean(false);
        final AtomicBoolean persisted = new AtomicBoolean(false);
        final AtomicBoolean closed = new AtomicBoolean(false);
        final long startedAt = System.currentTimeMillis();
        volatile int lastSeq = 0;

        Ctx(Long sessionId, String traceId, SseEmitter emitter) {
            this.sessionId = sessionId;
            this.traceId = traceId;
            this.emitter = emitter;
        }

        int elapsedMs() {
            return (int) (System.currentTimeMillis() - startedAt);
        }

        void stop() {
            Disposable d = subscription.get();
            if (d != null && !d.isDisposed()) {
                d.dispose();
            }
        }
    }

    /** 供测试断言使用：判断信号类型是否属于正常终止 */
    static boolean isTerminal(SignalType type) {
        return type == SignalType.ON_COMPLETE || type == SignalType.ON_ERROR;
    }
}
