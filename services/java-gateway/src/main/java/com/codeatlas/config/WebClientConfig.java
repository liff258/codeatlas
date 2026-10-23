package com.codeatlas.config;

import io.netty.channel.ChannelOption;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.reactive.ReactorClientHttpConnector;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.netty.http.client.HttpClient;

import java.time.Duration;

@Configuration
public class WebClientConfig {

    /**
     * 专用于调用 Python Agent 的 WebClient。
     *
     * ⚠️ 关键点：responseTimeout 默认关闭。
     * reactor-netty 的 responseTimeout 限制的是「两次网络读之间的间隔」，
     * 而不是整个响应的时长。SSE 在等 LLM 首 token 时可能静默十几秒，
     * 如果这里设 10s，连接会被无声掐断，表现为「前端卡住然后突然报错」。
     * 正确做法是：靠 Python 侧 15s 心跳保活 + 网关 SseEmitter 的 300s 总超时兜底。
     */
    @Bean("agentWebClient")
    public WebClient agentWebClient(AgentProperties props) {
        HttpClient httpClient = HttpClient.create()
                .option(ChannelOption.CONNECT_TIMEOUT_MILLIS, props.getConnectTimeoutMs())
                .compress(false)  // SSE 不压缩，避免代理层攒批
                .keepAlive(true);

        if (props.getResponseTimeoutMs() > 0) {
            httpClient = httpClient.responseTimeout(Duration.ofMillis(props.getResponseTimeoutMs()));
        }

        return WebClient.builder()
                .baseUrl(props.getBaseUrl())
                .defaultHeader("X-Internal-Token", props.getInternalToken())
                .clientConnector(new ReactorClientHttpConnector(httpClient))
                .build();
    }
}
