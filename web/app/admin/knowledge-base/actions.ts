// SPDX-License-Identifier: Apache-2.0

"use server";

import { revalidatePath } from "next/cache";

import {
  archiveDocument,
  createFolder,
  deleteDocument,
  deleteFolder,
  moveDocument,
  reindexWorkspace,
  renameFolder,
  retryFailedDocuments,
  uploadDocument,
  type DocumentFolder,
} from "@/lib/api";
import { getFreshAccessToken } from "@/lib/session";

export type UploadState = { ok?: boolean; error?: boolean; count?: number };

export async function uploadDocumentsAction(
  _prev: UploadState,
  form: FormData,
): Promise<UploadState> {
  const token = await getFreshAccessToken();
  if (!token) return { error: true };

  const workspaceId = String(form.get("workspace_id") ?? "");
  const files = form
    .getAll("files")
    .filter((f): f is File => f instanceof File && f.size > 0);
  if (!workspaceId || files.length === 0) return { error: true };

  let uploaded = 0;
  for (const file of files) {
    if (await uploadDocument(token, workspaceId, file)) uploaded += 1;
  }
  revalidatePath("/admin/knowledge-base");
  return { ok: uploaded === files.length, count: uploaded, error: uploaded === 0 };
}

// Re-queue every document in a workspace for ingestion. Backend supports
// POST .../documents/reindex (per workspace); there is no per-document delete.
export async function reindexAction(workspaceId: string): Promise<boolean> {
  const token = await getFreshAccessToken();
  if (!token || !workspaceId) return false;
  const ok = await reindexWorkspace(token, workspaceId);
  if (ok) revalidatePath("/admin/knowledge-base");
  return ok;
}

// Re-enqueue every FAILED document across the org (super-admin). Returns the
// number re-queued, or null on failure.
export async function retryFailedAction(): Promise<number | null> {
  const token = await getFreshAccessToken();
  if (!token) return null;
  const res = await retryFailedDocuments(token);
  if (!res) return null;
  revalidatePath("/admin/knowledge-base");
  return res.retried;
}

// ───────────────────────── Drive: folders ─────────────────────────
// Create a folder under an optional parent (null = workspace root). Returns the
// created folder so the client can select it without a refetch.
export async function createFolderAction(
  workspaceId: string,
  name: string,
  parentFolderId: string | null,
): Promise<DocumentFolder | null> {
  const token = await getFreshAccessToken();
  if (!token || !workspaceId || !name.trim()) return null;
  const folder = await createFolder(token, workspaceId, {
    name: name.trim(),
    parent_folder_id: parentFolderId,
  });
  if (folder) revalidatePath("/admin/knowledge-base");
  return folder;
}

// Rename and/or move a folder (parent_folder_id undefined = leave in place).
export async function renameFolderAction(
  workspaceId: string,
  folderId: string,
  body: { name?: string; parent_folder_id?: string | null },
): Promise<boolean> {
  const token = await getFreshAccessToken();
  if (!token || !workspaceId || !folderId) return false;
  const ok = await renameFolder(token, workspaceId, folderId, body);
  if (ok) revalidatePath("/admin/knowledge-base");
  return ok;
}

// Recursively delete a folder (its sub-folders + documents are purged server-side).
export async function deleteFolderAction(
  workspaceId: string,
  folderId: string,
): Promise<boolean> {
  const token = await getFreshAccessToken();
  if (!token || !workspaceId || !folderId) return false;
  const ok = await deleteFolder(token, workspaceId, folderId);
  if (ok) revalidatePath("/admin/knowledge-base");
  return ok;
}

// ───────────────────────── Drive: document lifecycle ─────────────────────────
// Move a document into a folder (null = workspace root).
export async function moveDocumentAction(
  workspaceId: string,
  documentId: string,
  folderId: string | null,
): Promise<boolean> {
  const token = await getFreshAccessToken();
  if (!token || !workspaceId || !documentId) return false;
  const ok = await moveDocument(token, workspaceId, documentId, folderId);
  if (ok) revalidatePath("/admin/knowledge-base");
  return ok;
}

// Archive a document (status → ARCHIVED; Qdrant chunks removed, object kept).
export async function archiveDocumentAction(
  workspaceId: string,
  documentId: string,
): Promise<boolean> {
  const token = await getFreshAccessToken();
  if (!token || !workspaceId || !documentId) return false;
  const ok = await archiveDocument(token, workspaceId, documentId);
  if (ok) revalidatePath("/admin/knowledge-base");
  return ok;
}

// Delete a document (soft-delete + hard purge of chunks + the stored object).
export async function deleteDocumentAction(
  workspaceId: string,
  documentId: string,
): Promise<boolean> {
  const token = await getFreshAccessToken();
  if (!token || !workspaceId || !documentId) return false;
  const ok = await deleteDocument(token, workspaceId, documentId);
  if (ok) revalidatePath("/admin/knowledge-base");
  return ok;
}
