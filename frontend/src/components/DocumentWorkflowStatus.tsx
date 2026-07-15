import type { DocumentVersionStatus } from "../types/knowledgeDocument";

const STATUS_LABELS: Record<DocumentVersionStatus, string> = {
  draft: "草稿待处理",
  processing: "处理中",
  ready_for_review: "待审核 Chunk",
  indexing: "向量索引中",
  indexing_failed: "索引失败",
  ready_to_publish: "待发布",
  published: "已发布",
  superseded: "已被新版本替代",
};

const ACTION_LABELS: Record<DocumentVersionStatus, string> = {
  draft: "去处理",
  processing: "查看处理状态",
  ready_for_review: "审核 Chunk 并索引",
  indexing: "查看索引状态",
  indexing_failed: "检查并重试索引",
  ready_to_publish: "审核并发布",
  published: "查看已发布版本",
  superseded: "查看历史版本",
};

export function documentStatusLabel(status: DocumentVersionStatus | undefined): string {
  return status ? STATUS_LABELS[status] : "暂无版本";
}

export function documentActionLabel(status: DocumentVersionStatus | undefined): string {
  return status ? ACTION_LABELS[status] : "查看文档";
}
