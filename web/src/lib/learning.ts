/**
 * 知识平台的数据访问层。
 *
 * 类型严格对齐 contracts/openapi.yaml——字段名是 snake_case，
 * 和后端 @JsonNaming 的输出一致。改契约时这里要同步改。
 */

import { apiGet } from './api';
import { buildQuery } from './router';
import { buildGraph, type ApiGraph } from './libraryGraph';
import type { GraphEdge, GraphNode } from '../types/events';
import type { GraphState } from '../store/chatStore';

/* ────────────────────────── 类型 ────────────────────────── */

export interface Subject {
  code: string;
  domain: 'backend' | 'ai' | 'common';
  display_name: string;
  sort_order: number;
  color: string;
  chunk_count: number;
  kp_count: number;
  question_count: number;
}

export interface KnowledgePointBrief {
  id: string;
  title: string;
  breadcrumb?: string | null;
  subject?: string | null;
  is_question: boolean;
  chunk_count: number;
  char_count: number;
  preview?: string;
  doc_name?: string;
}

export interface KnowledgePointDetail extends KnowledgePointBrief {
  answer: string;
  chunk_ids: string[];
  document_id: number;
  entities: GraphNode[];
  related: KnowledgePointBrief[];
  prev?: KnowledgePointBrief | null;
  next?: KnowledgePointBrief | null;
}

export interface EntityMention {
  chunk_id: string;
  kp_id?: string | null;
  kp_title?: string | null;
  snippet: string;
}

export interface EntityDetail {
  name: string;
  entity_type: string;
  subject?: string | null;
  domain: 'backend' | 'ai' | 'common';
  doc_freq: number;
  description?: string | null;
  description_source: 'curated' | 'extracted';
  mentions: EntityMention[];
  relations: GraphEdge[];
}

export interface PageResult<T> {
  items: T[];
  total: number;
  page: number;
  size: number;
  has_more: boolean;
}

/* ────────────────────────── 接口 ────────────────────────── */

export function getSubjects(signal?: AbortSignal): Promise<Subject[]> {
  return apiGet<Subject[]>('/api/subjects', signal);
}

export function listKnowledgePoints(
  params: {
    subject?: string;
    type?: 'all' | 'question';
    q?: string;
    page?: number;
    size?: number;
  },
  signal?: AbortSignal,
): Promise<PageResult<KnowledgePointBrief>> {
  return apiGet<PageResult<KnowledgePointBrief>>(
    `/api/knowledge-points${buildQuery(params)}`,
    signal,
  );
}

export function getKnowledgePoint(id: string, signal?: AbortSignal): Promise<KnowledgePointDetail> {
  return apiGet<KnowledgePointDetail>(`/api/knowledge-points/${encodeURIComponent(id)}`, signal);
}

export function getEntity(name: string, signal?: AbortSignal): Promise<EntityDetail> {
  return apiGet<EntityDetail>(`/api/entities${buildQuery({ name })}`, signal);
}

/**
 * 某个实体的一跳邻居图（实体页用）。
 *
 * 走 /api/graph/neighbors 而不是自己拼：那个接口返回的已经是
 * 「节点带 domain、边带 cross_domain」的完整结构，前端直接渲染即可。
 */
export async function getNeighbors(
  entity: string,
  depth = 1,
  signal?: AbortSignal,
): Promise<GraphState> {
  const data = await apiGet<ApiGraph>(
    `/api/graph/neighbors${buildQuery({ entity, depth })}`,
    signal,
  );
  return buildGraph(data).state;
}

/** 学科 → 域名（决定配色）。未知学科按 common 处理，不猜 */
export function domainOf(subject?: Subject | null): 'backend' | 'ai' | 'common' {
  return subject?.domain ?? 'common';
}
