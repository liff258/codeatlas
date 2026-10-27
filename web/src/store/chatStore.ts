/**
 * 主对话 store。
 *
 * 逻辑在 createChatStore.ts（工厂），这里只做两件事：
 *   1. 用主对话的 localStorage key 造一个实例
 *   2. 把工厂里的类型和选择器再导出一次，让页面保持 `from '../store/chatStore'` 不变
 *
 * 为什么要拆：助手（AssistantDock）需要第二个独立实例，
 * 而原来的 store 里有四个模块级可变变量，两个实例会互相打断。
 * 详见 createChatStore.ts 里的说明。
 */

import { createChatStore } from './createChatStore';

export * from './createChatStore';

/** 主对话。持久化到 localStorage，刷新不丢 */
export const useChatStore = createChatStore({ storageKey: 'codeatlas.session.v1' });
