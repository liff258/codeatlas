package com.codeatlas.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

@Data
@Component
@ConfigurationProperties(prefix = "codeatlas.agent")
public class AgentProperties {

    /** Python Agent 服务地址，仅内网可达 */
    private String baseUrl = "http://localhost:8000";

    /** 服务间共享密钥，Python 侧校验 X-Internal-Token */
    private String internalToken = "dev_internal_token";

    /** SSE 总超时（秒）。契约里 Agent 自身 60s 上限，网关留余量 */
    private int streamTimeoutSeconds = 300;

    /** 连接超时（毫秒） */
    private int connectTimeoutMs = 3000;

    /**
     * 响应超时（毫秒）。0 = 关闭。
     * SSE 是长连接，这里限制的是「两次网络读之间的间隔」，
     * 设太小会在等 LLM 首 token 时被无声掐断。默认关闭，靠心跳与 SseEmitter 超时兜底。
     */
    private int responseTimeoutMs = 0;
}
