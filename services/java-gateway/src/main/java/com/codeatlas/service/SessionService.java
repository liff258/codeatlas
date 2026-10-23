package com.codeatlas.service;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.codeatlas.entity.Message;
import com.codeatlas.entity.Session;
import com.codeatlas.mapper.MessageMapper;
import com.codeatlas.mapper.SessionMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.Collections;
import java.util.List;

/**
 * 会话与消息持久化。
 *
 * 表所有权（CLAUDE.md 不变量 2）：session / message 只由 Java 写。
 */
@Service
@RequiredArgsConstructor
public class SessionService {

    /** 传给 Python 的历史轮数。契约里 Router 只做最近 3 轮指代消解 */
    private static final int HISTORY_LIMIT = 6;

    private final SessionMapper sessionMapper;
    private final MessageMapper messageMapper;

    public Session getOrCreate(Long sessionId, String userId, String question) {
        if (sessionId != null) {
            Session existing = sessionMapper.selectById(sessionId);
            if (existing != null) {
                return existing;
            }
        }
        Session session = new Session();
        session.setUserId(userId == null ? "local" : userId);
        session.setTitle(buildTitle(question));
        sessionMapper.insert(session);
        return session;
    }

    public Message saveUserMessage(Long sessionId, String content) {
        Message msg = new Message();
        msg.setSessionId(sessionId);
        msg.setRole("user");
        msg.setContent(content);
        messageMapper.insert(msg);
        return msg;
    }

    public Message saveAssistantMessage(Long sessionId, String content, String traceId) {
        Message msg = new Message();
        msg.setSessionId(sessionId);
        msg.setRole("assistant");
        msg.setContent(content);
        msg.setTraceId(traceId);
        messageMapper.insert(msg);
        return msg;
    }

    /**
     * 取最近 N 条消息作为上下文。
     * 用 id 倒序取再反转，避免 offset 分页在大表上退化。
     */
    public List<Message> recentHistory(Long sessionId, int limit) {
        if (sessionId == null) {
            return Collections.emptyList();
        }
        List<Message> desc = messageMapper.selectList(
                Wrappers.<Message>lambdaQuery()
                        .eq(Message::getSessionId, sessionId)
                        .orderByDesc(Message::getId)
                        .last("LIMIT " + Math.min(limit, HISTORY_LIMIT))
        );
        Collections.reverse(desc);
        return desc;
    }

    private String buildTitle(String question) {
        if (question == null || question.isBlank()) {
            return "新对话";
        }
        String q = question.strip().replaceAll("\\s+", " ");
        return q.length() <= 30 ? q : q.substring(0, 30) + "…";
    }

    public List<Session> listSessions(String userId, int limit) {
        return sessionMapper.selectList(
                Wrappers.<Session>lambdaQuery()
                        .eq(Session::getUserId, userId == null ? "local" : userId)
                        .orderByDesc(Session::getUpdatedAt)
                        .last("LIMIT " + Math.min(Math.max(limit, 1), 100))
        );
    }

    public List<Message> listMessages(Long sessionId) {
        return messageMapper.selectList(
                Wrappers.<Message>lambdaQuery()
                        .eq(Message::getSessionId, sessionId)
                        .orderByAsc(Message::getId)
        );
    }

    public Session createSession(String userId, String title) {
        Session session = new Session();
        session.setUserId(userId == null ? "local" : userId);
        session.setTitle(title == null || title.isBlank() ? "新对话" : title);
        sessionMapper.insert(session);
        return session;
    }
}
