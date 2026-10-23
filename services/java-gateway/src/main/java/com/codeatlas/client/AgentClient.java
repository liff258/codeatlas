package com.codeatlas.client;

import com.codeatlas.client.dto.InternalChatRequest;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.MediaType;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

import java.time.Duration;
import java.util.Map;

/**
 * Python Agent 服务的唯一调用入口。
 *
 * 规则（见 CLAUDE.md）：controller / service 不得直接使用 WebClient，
 * 一律通过本类。这样换协议、加重试、改鉴权都只改一个地方。
 */
@Slf4j
@Component
public class AgentClient {

    private static final ParameterizedTypeReference<ServerSentEvent<String>> SSE_TYPE =
            new ParameterizedTypeReference<>() {};

    private final WebClient webClient;

    public AgentClient(@Qualifier("agentWebClient") WebClient webClient) {
        this.webClient = webClient;
    }

    /**
     * 发起流式推理。
     *
     * 注意：这里返回的是冷流，订阅才真正发起请求。
     * 调用方（ChatService）负责 subscribe 并把事件转发给 SseEmitter。
     */
    public Flux<ServerSentEvent<String>> stream(InternalChatRequest request) {
        return webClient.post()
                .uri("/internal/agent/stream")
                .contentType(MediaType.APPLICATION_JSON)
                .accept(MediaType.TEXT_EVENT_STREAM)
                .bodyValue(request)
                .retrieve()
                .bodyToFlux(SSE_TYPE)
                .timeout(Duration.ofSeconds(120))  // 单次事件间隔上限，与心跳 15s 留足余量
                .doOnSubscribe(s -> log.info("agent stream subscribed | trace={}", request.getTraceId()))
                .doOnError(e -> log.error("agent stream error | trace={}", request.getTraceId(), e));
    }

    /** 健康检查。失败不抛异常，返回 degraded，交给调用方决定怎么展示。 */
    public Mono<Map<String, Object>> health() {
        return webClient.get()
                .uri("/internal/health")
                .retrieve()
                .bodyToMono(new ParameterizedTypeReference<Map<String, Object>>() {})
                .timeout(Duration.ofSeconds(3))
                .onErrorResume(e -> {
                    log.warn("agent health check failed: {}", e.toString());
                    return Mono.just(Map.of("status", "down", "error", e.getClass().getSimpleName()));
                });
    }
}
