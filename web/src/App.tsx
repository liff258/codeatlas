/**
 * 路由分发。
 *
 * 改造后这里只剩两件事：把 hash 映射到页面、兼容旧的 `?q=` 分享链接。
 * 具体页面在 pages/ 下，全局导航在 components/AppShell.tsx。
 */

import { useEffect } from 'react';
import AppShell from './components/AppShell';
import HomePage from './pages/HomePage';
import SubjectPage from './pages/SubjectPage';
import KnowledgePointPage from './pages/KnowledgePointPage';
import EntityPage from './pages/EntityPage';
import QuestionsPage from './pages/QuestionsPage';
import ChatPage from './pages/ChatPage';
import { navigate, useRoute } from './lib/router';

export default function App() {
  const { route } = useRoute();

  // 兼容改造前的分享链接 `?q=xxx`（截图脚本、演示链接都用了这个形式）。
  // 没有 hash 时把它转成 #/chat?q=xxx，老链接不会失效。
  useEffect(() => {
    if (window.location.hash) return;
    const q = new URLSearchParams(window.location.search).get('q');
    if (q) navigate(`/chat?q=${encodeURIComponent(q)}`, { replace: true });
  }, []);

  return (
    <AppShell>
      {route.name === 'home' && <HomePage />}
      {route.name === 'subject' && <SubjectPage subject={route.subject} />}
      {route.name === 'kp' && <KnowledgePointPage id={route.id} />}
      {route.name === 'entity' && <EntityPage name={route.entity} />}
      {route.name === 'questions' && <QuestionsPage />}
      {route.name === 'chat' && <ChatPage />}
    </AppShell>
  );
}
