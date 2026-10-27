/**
 * 全局助手 store。
 *
 * 和主对话是两个完全独立的实例：
 *   - 各自有自己的 messages / sessionId / abort
 *   - 不持久化（storageKey: null）——助手是临时追问窗口，
 *     把它的内容写进 localStorage 会让主对话刷新后冒出无关的问答
 *
 * 后端那边是同一个 `/api/chat/stream`，但带的是各自的 session_id，
 * 所以会话在库里也是分开的两条。
 */

import { createChatStore } from './createChatStore';

export const useAssistantStore = createChatStore({ storageKey: null });
