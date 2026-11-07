// SPDX-License-Identifier: Apache-2.0

// Server-side client for the control-plane API. Never import from client code.
import "server-only";

import { parseEmbeddingsStatus, type EmbeddingsStatus } from "@/lib/embeddings";
import { type LoginError, loginErrorFromResponse } from "@/lib/login-error";
import { isPasswordPolicyRejection } from "@/lib/password-policy";
import { requestForwardedHeaders } from "@/lib/session";

const BASE = process.env.CONTROL_PLANE_URL ?? "http://localhost:8000";

export type Tokens = { access_token: string; refresh_token: string };
export type Me = {
  id: string;
  email: string;
  role: string;
  org_id: string | null;
  locale?: string;
  full_name?: string | null;
  job_title?: string | null;
  department?: string | null;
  timezone?: string;
  answer_style?: AnswerStyle;
  preferred_chat_model?: string | null;
  must_change_password?: boolean;
  // Operator authority across every org (distinct from org SUPER_ADMIN).
  is_platform_admin?: boolean;
};

// Full user profile (mirrors the control-plane User model + the account view).
export type Profile = {
  id: string;
  email: string;
  role: string;
  is_active: boolean;
  auth_provider: string;
  full_name: string | null;
  job_title: string | null;
  department: string | null;
  manager_user_id: string | null;
  hire_date: string | null;
  phone: string | null;
  location: string | null;
  timezone: string;
  locale: string;
  answer_style: AnswerStyle;
  preferred_chat_model: string | null;
  must_change_password: boolean;
};
export type ProfileResponse = {
  user: Profile;
  manager_display: string | null;
  tenure_days: number | null;
};
export type InviteListItem = {
  id: string;
  email: string;
  role: string;
  status: "pending" | "accepted" | "revoked" | "expired";
  full_name: string | null;
  department: string | null;
  expires_at: string;
  created_at: string;
};
export type InvitePreview = {
  email: string;
  role: string;
  full_name: string | null;
  job_title: string | null;
  department: string | null;
  phone: string | null;
  location: string | null;
  timezone: string | null;
  locale: string | null;
};

export async function login(
  email: string,
  password: string,
): Promise<{ ok: true; tokens: Tokens } | { ok: false; failure: LoginError }> {
  let res: Response;
  try {
    res = await fetch(`${BASE}/api/v1/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(await requestForwardedHeaders()) },
      body: JSON.stringify({ email, password }),
      cache: "no-store",
    });
  } catch {
    return { ok: false, failure: loginErrorFromResponse(0, null) };
  }
  if (!res.ok) {
    return { ok: false, failure: loginErrorFromResponse(res.status, res.headers.get("retry-after")) };
  }
  return { ok: true, tokens: (await res.json()) as Tokens };
}

export async function logout(token: string): Promise<void> {
  await fetch(`${BASE}/api/v1/auth/logout`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, ...(await requestForwardedHeaders()) },
    cache: "no-store",
  });
}

export async function me(token: string): Promise<Me | null> {
  const res = await fetch(`${BASE}/api/v1/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!res.ok) return null;
  return (await res.json()) as Me;
}

// ───────────────────────── Onboarding ─────────────────────────
export type OnboardingState = {
  onboarded: boolean;
  has_super_admin: boolean;
  // Whether bootstrap needs the installer-printed setup token. Absent on older
  // control planes — callers treat "unknown" as required.
  setup_token_required?: boolean;
};

export async function onboardingState(): Promise<OnboardingState> {
  const res = await fetch(`${BASE}/api/v1/onboarding/state`, { cache: "no-store" });
  if (!res.ok) return { onboarded: false, has_super_admin: false };
  return (await res.json()) as OnboardingState;
}

export type BootstrapResult = Tokens & { user_id: string; org_id: string };

// The failure carries the HTTP status so the UI can tell an invalid setup token
// (401/403) from "already set up" (409) and other errors.
export type BootstrapOutcome =
  | { ok: true; result: BootstrapResult }
  | { ok: false; status: number; passwordRejected?: boolean };

export async function bootstrap(
  email: string,
  password: string,
  orgName: string,
  setupToken: string,
): Promise<BootstrapOutcome> {
  const res = await fetch(`${BASE}/api/v1/onboarding/bootstrap`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await requestForwardedHeaders()) },
    body: JSON.stringify({
      email,
      password,
      org_name: orgName,
      ...(setupToken ? { setup_token: setupToken } : {}),
    }),
    cache: "no-store",
  });
  if (!res.ok) {
    const body: unknown = await res.json().catch(() => undefined);
    return { ok: false, status: res.status, passwordRejected: isPasswordPolicyRejection(res.status, body) };
  }
  return { ok: true, result: (await res.json()) as BootstrapResult };
}

export type WorkspaceSetup = {
  workspace: { id: string; name: string; type: string };
  embed_snippet: string | null;
  invite_token: string | null;
  invite_accept_path: string | null;
};

export async function createOnboardingWorkspace(
  token: string,
  type: "INTERNAL" | "EXTERNAL",
  name: string,
  inviteEmail?: string,
): Promise<WorkspaceSetup | null> {
  const res = await fetch(`${BASE}/api/v1/onboarding/workspace`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ type, name, invite_email: inviteEmail ?? null }),
    cache: "no-store",
  });
  if (!res.ok) return null;
  return (await res.json()) as WorkspaceSetup;
}

export type WorkspaceSummary = { id: string; name: string; type: "INTERNAL" | "EXTERNAL" };

export async function listMyWorkspaces(token: string): Promise<WorkspaceSummary[]> {
  const res = await fetch(`${BASE}/api/v1/workspaces`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!res.ok) return [];
  return (await res.json()) as WorkspaceSummary[];
}

export async function uploadDocument(
  token: string,
  workspaceId: string,
  file: File,
): Promise<boolean> {
  return (await uploadDocumentResult(token, workspaceId, file)).ok;
}

// Same upload, keeping what a refusal needs to be explained (status, body,
// Retry-After): 409/503 come from the embedding-profile guard.
export async function uploadDocumentResult(
  token: string,
  workspaceId: string,
  file: File,
): Promise<{ ok: boolean; status: number; body: string; retryAfter: string | null }> {
  const form = new FormData();
  form.append("file", file, file.name);
  try {
    const res = await fetch(`${BASE}/api/v1/admin/workspaces/${workspaceId}/documents`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: form,
      cache: "no-store",
    });
    const body = res.ok ? "" : await res.text().catch(() => "");
    return { ok: res.ok, status: res.status, body, retryAfter: res.headers.get("retry-after") };
  } catch {
    return { ok: false, status: 0, body: "", retryAfter: null };
  }
}

// Re-queue all of a workspace's documents for ingestion (idempotent).
export async function reindexWorkspace(token: string, workspaceId: string): Promise<boolean> {
  const res = await fetch(
    `${BASE}/api/v1/admin/workspaces/${workspaceId}/documents/reindex`,
    {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
    },
  );
  return res.ok;
}

// ───────────────────────── Admin: analytics ─────────────────────────
export type Analytics = {
  workspaces: number;
  documents: { total: number; pending: number; processing: number; success: number; failed: number };
  conversations: number;
  flagged: number;
  messages: number;
  tokens_used: number;
  activity: { date: string; messages: number }[];
};

export async function analytics(token: string): Promise<Analytics | null> {
  const res = await fetch(`${BASE}/api/v1/admin/analytics`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!res.ok) return null;
  return (await res.json()) as Analytics;
}

// ───────────────────────── Admin: documents (KB) ─────────────────────────
export type DocumentStatus = "PENDING" | "PROCESSING" | "SUCCESS" | "FAILED" | "ARCHIVED";
export type DocumentRow = {
  id: string;
  workspace_id: string;
  filename: string;
  file_size: number;
  status: DocumentStatus;
  // Why ingestion failed (contracts/document_errors.md): a stable code + its
  // params, and the same reason in English. Optional for older payloads.
  error_code?: string | null;
  error_params?: Record<string, unknown> | null;
  error_message: string | null;
  created_at: string;
  // Auto-retry attempts spent so far (backend caps at MAX_DOC_RETRIES). Optional
  // so older payloads without the field still type-check.
  retry_count?: number;
  // Drive lifecycle (migration 0017). Optional so older payloads still type-check.
  folder_id?: string | null;
  archived_at?: string | null;
  deleted_at?: string | null;
};

// A folder in a workspace's document tree. parent_folder_id is null at root.
export type DocumentFolder = {
  id: string;
  workspace_id: string;
  parent_folder_id: string | null;
  name: string;
  created_at: string;
  updated_at: string;
};

// List documents in a workspace. When folderId is supplied, scopes to that
// folder ("root" = top level); omitting it returns all non-deleted documents.
export async function listDocuments(
  token: string,
  workspaceId: string,
  folderId?: string | "root",
): Promise<DocumentRow[]> {
  const qs = folderId ? `?folder_id=${encodeURIComponent(folderId)}` : "";
  const res = await fetch(`${BASE}/api/v1/admin/workspaces/${workspaceId}/documents${qs}`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!res.ok) return [];
  return (await res.json()) as DocumentRow[];
}

// ── Drive: folders ──
export async function listFolders(
  token: string,
  workspaceId: string,
): Promise<DocumentFolder[]> {
  const res = await fetch(`${BASE}/api/v1/admin/workspaces/${workspaceId}/folders`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!res.ok) return [];
  return (await res.json()) as DocumentFolder[];
}

export async function createFolder(
  token: string,
  workspaceId: string,
  body: { name: string; parent_folder_id?: string | null },
): Promise<DocumentFolder | null> {
  const res = await fetch(`${BASE}/api/v1/admin/workspaces/${workspaceId}/folders`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  if (!res.ok) return null;
  return (await res.json()) as DocumentFolder;
}

// Rename and/or move a folder (set parent_folder_id to null to move to root).
export async function renameFolder(
  token: string,
  workspaceId: string,
  folderId: string,
  body: { name?: string; parent_folder_id?: string | null },
): Promise<boolean> {
  return authedSend(
    token,
    "PATCH",
    `/api/v1/admin/workspaces/${workspaceId}/folders/${folderId}`,
    body,
  );
}

// Recursive: deletes sub-folders + their documents (backend cascades the purge).
export async function deleteFolder(
  token: string,
  workspaceId: string,
  folderId: string,
): Promise<boolean> {
  return authedSend(
    token,
    "DELETE",
    `/api/v1/admin/workspaces/${workspaceId}/folders/${folderId}`,
  );
}

// ── Drive: document lifecycle ──
// Move a document into a folder (folderId null = workspace root).
export async function moveDocument(
  token: string,
  workspaceId: string,
  documentId: string,
  folderId: string | null,
): Promise<boolean> {
  return authedSend(
    token,
    "PATCH",
    `/api/v1/admin/workspaces/${workspaceId}/documents/${documentId}`,
    { folder_id: folderId },
  );
}

// Archive a document: status → ARCHIVED, Qdrant chunks removed (object kept).
export async function archiveDocument(
  token: string,
  workspaceId: string,
  documentId: string,
): Promise<boolean> {
  return authedSend(
    token,
    "POST",
    `/api/v1/admin/workspaces/${workspaceId}/documents/${documentId}/archive`,
  );
}

// Delete a document: soft-delete in DB + hard purge of Qdrant chunks + MinIO object.
export async function deleteDocument(
  token: string,
  workspaceId: string,
  documentId: string,
): Promise<boolean> {
  return authedSend(
    token,
    "DELETE",
    `/api/v1/admin/workspaces/${workspaceId}/documents/${documentId}`,
  );
}

// Re-enqueue every FAILED document across the org for ingestion (super-admin).
// Returns how many were re-queued, or null on failure.
export async function retryFailedDocuments(token: string): Promise<{ retried: number } | null> {
  const res = await fetch(`${BASE}/api/v1/admin/documents/retry-failed`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!res.ok) return null;
  return (await res.json()) as { retried: number };
}

// ───────────────────────── Admin: invites ─────────────────────────
export type InviteResult = {
  invite_id: string;
  token: string;
  accept_path: string;
  expires_at: string;
};

// Profile fields an admin may seed onto an invite (carried until acceptance).
export type ProfileSeed = {
  full_name?: string;
  job_title?: string;
  department?: string;
  department_id?: string;
  location_id?: string;
  manager_user_id?: string;
  phone?: string;
  location?: string;
  timezone?: string;
  locale?: string;
};

export async function createInvite(
  token: string,
  email: string,
  role: "WORKSPACE_ADMIN" | "STAFF" = "STAFF",
  opts?: { workspaceId?: string; teamId?: string } & ProfileSeed,
): Promise<InviteResult | null> {
  const { workspaceId, teamId, ...profile } = opts ?? {};
  const res = await fetch(`${BASE}/api/v1/auth/invites`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({
      email,
      role,
      workspace_id: workspaceId ?? null,
      team_id: teamId ?? null,
      ...profile,
    }),
    cache: "no-store",
  });
  if (!res.ok) return null;
  return (await res.json()) as InviteResult;
}

// ───────────────────────── Admin: flagged conversations (P6) ─────────────────────────
export type FlaggedConversation = {
  id: string;
  workspace_id: string;
  evaluation_score: number;
  faithfulness_score: number | null;
  citation_validity_score: number | null;
  citation_coverage_score: number | null;
  preview: string | null;
  created_at: string;
};

export async function listFlagged(token: string): Promise<FlaggedConversation[]> {
  const res = await fetch(`${BASE}/api/v1/admin/conversations/flagged`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!res.ok) return [];
  return (await res.json()) as FlaggedConversation[];
}

// ───────────────────────── Admin: audit log (SUPER_ADMIN) ─────────────────────────
export type AuditEntry = {
  action: string;
  target: string | null;
  metadata: unknown;
  actor: string | null;
  created_at: string;
};

export async function listAudit(token: string): Promise<AuditEntry[]> {
  const res = await fetch(`${BASE}/api/v1/admin/audit`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!res.ok) return [];
  return (await res.json()) as AuditEntry[];
}

// ───────────────────────── Admin: team console (P8.5) ─────────────────────────
export type Role = "SUPER_ADMIN" | "WORKSPACE_ADMIN" | "STAFF";
export type TeamRow = {
  id: string;
  org_id: string;
  parent_team_id: string | null;
  name: string;
  created_at: string;
};
export type WorkspaceRow = {
  id: string;
  name: string;
  type: "INTERNAL" | "EXTERNAL";
  team_id: string | null;
  web_search_enabled?: boolean;
  personalization_enabled?: boolean;
  memory_enabled?: boolean;
  cors_allowed_origins?: string[];
};
export type Member = { id: string; email: string; role: Role; is_active: boolean };
export type OrgUser = {
  id: string;
  email: string;
  role: Role;
  is_active: boolean;
  full_name: string | null;
  job_title: string | null;
  department: string | null;
  department_id: string | null;
  location_id: string | null;
  manager_user_id: string | null;
  manager_display: string | null;
  hire_date: string | null;
  phone: string | null;
  location: string | null;
  timezone: string;
  locale: string;
  tenure_days: number | null;
  is_platform_admin?: boolean;
};

// ───────────────────────── Admin: directory (departments & locations) ─────────
export type Department = {
  id: string;
  org_id: string;
  name: string;
  owner_user_id: string | null;
  parent_department_id: string | null;
  created_at: string;
  updated_at: string;
};
export type Location = {
  id: string;
  org_id: string;
  name: string;
  city: string | null;
  country: string | null;
  created_at: string;
  updated_at: string;
};
// Flat node from the org-chart endpoint; the reporting tree is built client-side.
export type OrgChartNode = {
  id: string;
  name: string;
  email: string;
  job_title: string | null;
  department: string | null;
  manager_user_id: string | null;
};

// The shared authed helpers forward the end user's IP/proto (X-Forwarded-*) so
// control-plane rate limits and audit logs see the real client.
async function authedGet<T>(token: string, path: string, fallback: T): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { Authorization: `Bearer ${token}`, ...(await requestForwardedHeaders()) },
    cache: "no-store",
  });
  if (!res.ok) return fallback;
  return (await res.json()) as T;
}

async function authedSend(
  token: string,
  method: "POST" | "DELETE" | "PUT" | "PATCH",
  path: string,
  body?: unknown,
): Promise<boolean> {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...(await requestForwardedHeaders()),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
  });
  return res.ok;
}

// Teams
export const listTeams = (t: string, orgId: string) =>
  authedGet<TeamRow[]>(t, `/api/v1/admin/orgs/${orgId}/teams`, []);
export const getTeam = (t: string, orgId: string, teamId: string) =>
  authedGet<TeamRow | null>(t, `/api/v1/admin/orgs/${orgId}/teams/${teamId}`, null);
export const createTeam = (t: string, orgId: string, name: string, parentTeamId?: string) =>
  authedSend(t, "POST", `/api/v1/admin/orgs/${orgId}/teams`, {
    name,
    parent_team_id: parentTeamId ?? null,
  });

// Workspaces
export const listOrgWorkspaces = (t: string, orgId: string) =>
  authedGet<WorkspaceRow[]>(t, `/api/v1/admin/orgs/${orgId}/workspaces`, []);
export const listTeamWorkspaces = (t: string, orgId: string, teamId: string) =>
  authedGet<WorkspaceRow[]>(t, `/api/v1/admin/orgs/${orgId}/teams/${teamId}/workspaces`, []);
export const createWorkspace = (
  t: string,
  orgId: string,
  body: {
    name: string;
    type: "INTERNAL" | "EXTERNAL";
    team_id?: string | null;
    web_search_enabled?: boolean;
    personalization_enabled?: boolean;
  },
) => authedSend(t, "POST", `/api/v1/admin/orgs/${orgId}/workspaces`, body);

// Per-workspace chat-intelligence flags (web search / personalization / memory).
// memory_available mirrors the global MEMORY_ENABLED switch (read-only).
export type WorkspaceSettings = {
  workspace_id: string;
  web_search_enabled: boolean;
  personalization_enabled: boolean;
  memory_enabled: boolean;
  memory_available: boolean;
};
export const getWorkspaceSettings = (t: string, workspaceId: string) =>
  authedGet<WorkspaceSettings | null>(t, `/api/v1/admin/workspaces/${workspaceId}/settings`, null);
export const updateWorkspaceSettings = (
  t: string,
  workspaceId: string,
  body: { web_search_enabled?: boolean; personalization_enabled?: boolean; memory_enabled?: boolean },
) => authedSend(t, "PUT", `/api/v1/admin/workspaces/${workspaceId}/settings`, body);

// Replace an EXTERNAL workspace's widget allowed origins (the edge only mints
// widget tokens for these exact Origin values). Returns the stored list.
export async function updateWidgetOrigins(
  t: string,
  workspaceId: string,
  origins: string[],
): Promise<{ ok: true; origins: string[] } | { ok: false; status: number }> {
  const res = await authedJson(t, "PUT", `/api/v1/admin/workspaces/${workspaceId}/widget`, {
    cors_allowed_origins: origins,
  });
  const stored = (res.data as { cors_allowed_origins?: unknown } | undefined)?.cors_allowed_origins;
  if (!res.ok || !Array.isArray(stored)) return { ok: false, status: res.status };
  return { ok: true, origins: stored.filter((o): o is string => typeof o === "string") };
}

// Members
export const listTeamMembers = (t: string, orgId: string, teamId: string) =>
  authedGet<Member[]>(t, `/api/v1/admin/orgs/${orgId}/teams/${teamId}/members`, []);
export const addTeamMember = (t: string, orgId: string, teamId: string, userId: string, role: Role = "STAFF") =>
  authedSend(t, "POST", `/api/v1/admin/orgs/${orgId}/teams/${teamId}/members`, { user_id: userId, role });
export const removeTeamMember = (t: string, orgId: string, teamId: string, userId: string) =>
  authedSend(t, "DELETE", `/api/v1/admin/orgs/${orgId}/teams/${teamId}/members/${userId}`);
export const listWorkspaceMembers = (t: string, workspaceId: string) =>
  authedGet<Member[]>(t, `/api/v1/admin/workspaces/${workspaceId}/members`, []);
export const addWorkspaceMember = (t: string, workspaceId: string, userId: string, role: Role = "STAFF") =>
  authedSend(t, "POST", `/api/v1/admin/workspaces/${workspaceId}/members`, { user_id: userId, role });
export const removeWorkspaceMember = (t: string, workspaceId: string, userId: string) =>
  authedSend(t, "DELETE", `/api/v1/admin/workspaces/${workspaceId}/members/${userId}`);

// Org users + team documents
export const listOrgUsers = (t: string, orgId: string) =>
  authedGet<OrgUser[]>(t, `/api/v1/admin/orgs/${orgId}/users`, []);
export const listTeamDocuments = (t: string, orgId: string, teamId: string) =>
  authedGet<DocumentRow[]>(t, `/api/v1/admin/orgs/${orgId}/teams/${teamId}/documents`, []);

// ───────────────────────── Account settings + user mgmt ─────────────────────────
// A JSON-returning variant of authedSend (the original returns just a boolean);
// used where the caller needs the status code or the response body (e.g. the
// temp password shown once, or a precise error).
async function authedJson(
  token: string,
  method: "POST" | "PATCH" | "PUT" | "DELETE",
  path: string,
  body?: unknown,
): Promise<{ ok: boolean; status: number; data?: unknown }> {
  try {
    const res = await fetch(`${BASE}${path}`, {
      method,
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
        ...(await requestForwardedHeaders()),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
    });
    let data: unknown;
    try {
      data = await res.json();
    } catch {
      /* empty / non-JSON body (e.g. 204) */
    }
    return { ok: res.ok, status: res.status, data };
  } catch {
    return { ok: false, status: 0 };
  }
}

// Self-service account settings.
export const getProfile = (t: string) =>
  authedGet<ProfileResponse | null>(t, "/api/v1/auth/profile", null);
export const updateMyProfile = (
  t: string,
  body: {
    full_name?: string | null;
    job_title?: string | null;
    department?: string | null;
    phone?: string | null;
    location?: string | null;
    timezone?: string | null;
  },
) => authedJson(t, "PATCH", "/api/v1/auth/profile", body);
export const changeMyPassword = (
  t: string,
  body: { current_password: string; new_password: string },
) => authedJson(t, "POST", "/api/v1/auth/change-password", body);
export const setMyLocale = (t: string, locale: string) =>
  authedJson(t, "PUT", "/api/v1/auth/locale", { locale });

// Durable memory the assistant has learned about the signed-in user.
export type MemoryItem = { content: string; created_at: string };
export const listMyMemory = (t: string) =>
  authedGet<MemoryItem[]>(t, "/api/v1/auth/memory", []);
export const clearMyMemory = (t: string) =>
  authedJson(t, "DELETE", "/api/v1/auth/memory");
// Import a memory summary pasted from another assistant (parsed into facts server-side).
export const importMemory = (t: string, text: string) =>
  authedJson(t, "POST", "/api/v1/auth/memory/import", { text });

// ───────────────────────── Admin: Qdrant 2D vector map ─────────────────────────
export type ScatterPoint = {
  x: number;
  y: number;
  workspace_id: string | null;
  filename: string | null;
  document_id: string | null;
};
export type QdrantScatter = {
  collection: string;
  total: number;
  points: ScatterPoint[];
  // Index pairs into `points`; chunks of the same document linked in a star.
  edges: [number, number][];
};

export const getQdrantScatter = (t: string) =>
  authedGet<QdrantScatter | null>(t, "/api/v1/admin/qdrant/scatter?limit=1500", null);

// ───────────────────────── White-label branding ─────────────────────────
export type Branding = {
  name: string;
  tagline: string | null;
  color: string;
  logo_data_url: string | null;
  icon_data_url: string | null;
};

// Public — no token (the login page reads this before auth). Falls back to the
// default Raggie brand if the control plane is unreachable.
export async function getBranding(): Promise<Branding> {
  const fallback: Branding = {
    name: "Raggie",
    tagline: null,
    color: "#0a5bff",
    logo_data_url: null,
    icon_data_url: null,
  };
  try {
    const res = await fetch(`${BASE}/api/v1/branding`, { cache: "no-store" });
    if (!res.ok) return fallback;
    return (await res.json()) as Branding;
  } catch {
    return fallback;
  }
}

export const updateBranding = (
  t: string,
  body: { name?: string; tagline?: string; color?: string },
) => authedJson(t, "PUT", "/api/v1/admin/branding", body);

// ───────────────────────── AI models + user preferences ─────────────────────────
export type AnswerStyle = "corporate" | "short" | "instructive" | "balanced";
export type ModelsConfig = {
  default_model: string | null;
  allowed_models: string[];
  // Display aliases: real model id -> friendly name shown in the picker.
  aliases?: Record<string, string>;
};

// Allowed/default chat models for the picker (any logged-in user).
export const getModelsConfig = (t: string) =>
  authedGet<ModelsConfig>(t, "/api/v1/models", { default_model: null, allowed_models: [] });

// Update the current user's answer style + preferred chat model.
export const updatePreferences = (
  t: string,
  body: { answer_style?: AnswerStyle; preferred_chat_model?: string | null },
) => authedJson(t, "PUT", "/api/v1/auth/me/preferences", body);

// Admin AI config (default model + allowed canonical ids). Provider endpoints
// and keys stay in the edge environment-backed registry.
export const getAiConfig = (t: string) =>
  authedGet<ModelsConfig>(t, "/api/v1/admin/ai-config", { default_model: null, allowed_models: [] });
export const updateAiConfig = (
  t: string,
  body: {
    chat_default_model?: string | null;
    chat_allowed_models?: string[];
    chat_model_aliases?: Record<string, string>;
  },
) => authedJson(t, "PUT", "/api/v1/admin/ai-config", body);

// ───────────────────────── Embeddings profile (platform admin) ─────────────────────────
// What the embeddings gateway runs vs. what the indexed documents were embedded
// with, plus re-embed progress. null when the control plane is unreachable or
// answers with something other than the documented shape.
export async function getEmbeddingsStatus(t: string): Promise<EmbeddingsStatus | null> {
  try {
    return parseEmbeddingsStatus(await authedGet<unknown>(t, "/api/v1/admin/embeddings", null));
  } catch {
    return null;
  }
}
// Accept the gateway's current profile (the fingerprint the admin confirmed)
// and re-embed every live document still on another one.
export const startReembed = (t: string, fingerprint: string) =>
  authedJson(t, "POST", "/api/v1/admin/embeddings/reembed", { fingerprint });

// ───────────────────────── Skills (versioned execution policies) ─────────────────────────
// Chat sends only id + version; the edge resolves all policy fields server-side.
export type Skill = {
  id: string;
  org_id: string;
  // owner_user_id null = org/published (admin-managed); non-null = a user's
  // personal skill. visibility mirrors that intent.
  owner_user_id: string | null;
  visibility: "personal" | "org";
  name: string;
  slug: string;
  description: string | null;
  instructions: string;
  icon: string | null;
  model: string | null;
  answer_style: AnswerStyle | null;
  allowed_tools: string[];
  version: number;
  policy_hash: string;
  enabled: boolean;
  created_at: string;
};

// Body for create/update. slug is a short lowercase token (a-z, 0-9, -; <=32).
export type SkillInput = {
  name?: string;
  slug?: string;
  description?: string | null;
  instructions?: string;
  icon?: string | null;
  model?: string | null;
  answer_style?: AnswerStyle | null;
  allowed_tools?: string[];
  enabled?: boolean;
};

// Enabled skills for the caller's org (the chat skill picker; any logged-in user).
export const listSkills = (t: string) => authedGet<Skill[]>(t, "/api/v1/skills", []);
// Full catalog incl. disabled (builder UI; WORKSPACE_ADMIN+).
export const listAdminSkills = (t: string) =>
  authedGet<Skill[]>(t, "/api/v1/admin/skills", []);
// Mutations use authedJson so callers can surface the 409 duplicate-slug case.
export const createSkill = (t: string, body: SkillInput) =>
  authedJson(t, "POST", "/api/v1/admin/skills", body);
export const updateSkill = (t: string, id: string, body: SkillInput) =>
  authedJson(t, "PUT", `/api/v1/admin/skills/${id}`, body);
export const deleteSkill = (t: string, id: string) =>
  authedJson(t, "DELETE", `/api/v1/admin/skills/${id}`);

// Personal skills: any user manages their OWN skills (not admin-gated). The chat
// picker (listSkills) already returns the union of org-published + the caller's own.
export const listMySkills = (t: string) =>
  authedGet<Skill[]>(t, "/api/v1/skills/personal", []);
export const createMySkill = (t: string, body: SkillInput) =>
  authedJson(t, "POST", "/api/v1/skills/personal", body);
export const updateMySkill = (t: string, id: string, body: SkillInput) =>
  authedJson(t, "PUT", `/api/v1/skills/personal/${id}`, body);
export const deleteMySkill = (t: string, id: string) =>
  authedJson(t, "DELETE", `/api/v1/skills/personal/${id}`);

// Admin: per-user token usage ("who burns the most tokens").
export type UserTokenUsage = {
  user_id: string | null;
  email: string;
  full_name: string | null;
  message_count: number;
  total_tokens: number;
};
export const usageByUser = (t: string) =>
  authedGet<UserTokenUsage[]>(t, "/api/v1/admin/analytics/usage-by-user", []);

// ───────────────────────── Self-hosted update check ─────────────────────────
export type UpdateStatus = {
  current_version: string;
  latest_version: string | null;
  update_available: boolean;
  notes: string | null;
  release_url: string | null;
  update_command: string;
  checked: boolean;
};

export const getUpdateStatus = (t: string) =>
  authedGet<UpdateStatus | null>(t, "/api/v1/admin/updates", null);

// Invite management (admin).
export const listInvites = (t: string) =>
  authedGet<InviteListItem[]>(t, "/api/v1/auth/invites", []);
export const revokeInvite = (t: string, inviteId: string) =>
  authedJson(t, "POST", `/api/v1/auth/invites/${inviteId}/revoke`);
export const resendInvite = (t: string, inviteId: string) =>
  authedJson(t, "POST", `/api/v1/auth/invites/${inviteId}/resend`);

// Public: preview the profile seeded on an invite token (accept page pre-fill).
export async function invitePreview(token: string): Promise<InvitePreview | null> {
  try {
    const res = await fetch(
      `${BASE}/api/v1/auth/invites/${encodeURIComponent(token)}/preview`,
      { cache: "no-store" },
    );
    if (!res.ok) return null;
    return (await res.json()) as InvitePreview;
  } catch {
    return null;
  }
}

// Public: redeem an invite; returns the auto-login tokens on success.
export async function acceptInvite(
  body: { token: string; password: string } & Omit<ProfileSeed, "manager_user_id">,
): Promise<{ ok: boolean; status: number; data?: Tokens }> {
  try {
    const res = await fetch(`${BASE}/api/v1/auth/invites/accept`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(await requestForwardedHeaders()) },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    let data: Tokens | undefined;
    try {
      data = (await res.json()) as Tokens;
    } catch {
      /* no body */
    }
    return { ok: res.ok, status: res.status, data };
  } catch {
    return { ok: false, status: 0 };
  }
}

// Admin user management.
export const createOrgUser = (
  t: string,
  orgId: string,
  body: { email: string; role: string; password?: string; hire_date?: string } & ProfileSeed,
) => authedJson(t, "POST", `/api/v1/admin/orgs/${orgId}/users`, body);
// Update allows null to CLEAR a field (create only sets, so it uses ProfileSeed).
export type ProfilePatch = {
  full_name?: string | null;
  job_title?: string | null;
  department?: string | null;
  department_id?: string | null;
  location_id?: string | null;
  manager_user_id?: string | null;
  phone?: string | null;
  location?: string | null;
  timezone?: string | null;
  locale?: string | null;
};
export const updateOrgUser = (
  t: string,
  orgId: string,
  userId: string,
  body: { email?: string; role?: string; hire_date?: string | null } & ProfilePatch,
) => authedJson(t, "PATCH", `/api/v1/admin/orgs/${orgId}/users/${userId}`, body);
export const setOrgUserActive = (t: string, orgId: string, userId: string, active: boolean) =>
  authedJson(t, "PATCH", `/api/v1/admin/orgs/${orgId}/users/${userId}/active`, { active });
export const resetOrgUserPassword = (t: string, orgId: string, userId: string) =>
  authedJson(t, "POST", `/api/v1/admin/orgs/${orgId}/users/${userId}/reset-password`);
// Platform admin only; 409 when revoking the last platform admin or granting a
// non-SUPER_ADMIN / inactive user.
export const setPlatformAdmin = (t: string, userId: string, isPlatformAdmin: boolean) =>
  authedJson(t, "PUT", `/api/v1/admin/users/${userId}/platform-admin`, {
    is_platform_admin: isPlatformAdmin,
  });

// ───────────────────────── Integrations (generic / MCP) ─────────────────────────
export type IntegrationProviderField = { key: string; label: string; secret: boolean };
export type IntegrationProvider = {
  key: string;
  label: string;
  auth: string; // token | oauth | mcp
  description: string;
  category?: string;
  icon?: string;
  featured?: boolean;
  // Connect scope: "org" = organization-wide (no workspace; SUPER_ADMIN only),
  // "workspace" = scoped to a single workspace. Defaults to workspace when absent.
  scope?: "org" | "workspace";
  fields: IntegrationProviderField[];
};
export type IntegrationRow = {
  id: string;
  org_id: string;
  scope_type: "user" | "team" | "workspace";
  scope_id: string;
  target_workspace_id: string | null;
  provider: string;
  display_name: string | null;
  status: string;
  config: Record<string, unknown>;
  last_error: string | null;
  created_at: string;
  updated_at: string;
};

// A connected MCP integration as exposed to ANY org user (no secrets): the chat
// "Araçlar" sidebar lists these so non-admins can see/toggle org-scoped tools.
// Mirrors the control-plane GET /api/v1/integrations/available contract.
export type AvailableIntegration = {
  provider: string;
  display_name: string;
  icon: string;
  status: string;
};

// The org's connected MCP integrations, readable by any authenticated org user
// (returns only display fields — no credentials). Empty on failure.
export const getAvailableIntegrations = (t: string) =>
  authedGet<AvailableIntegration[]>(t, "/api/v1/integrations/available", []);

export const listIntegrationProviders = (t: string) =>
  authedGet<IntegrationProvider[]>(t, "/api/v1/integrations/providers", []);
export const listIntegrations = (t: string) =>
  authedGet<IntegrationRow[]>(t, "/api/v1/integrations", []);
export const connectIntegration = (
  t: string,
  // Org-scoped connects omit scope_type/scope_id/target_workspace_id entirely —
  // the server forces org scope (SUPER_ADMIN only). Workspace connects pass them.
  body: {
    provider: string;
    scope_type?: "user" | "team" | "workspace";
    scope_id?: string;
    target_workspace_id?: string | null;
    display_name?: string;
    credentials?: Record<string, string>;
    config?: Record<string, string>;
  },
) => authedJson(t, "POST", "/api/v1/integrations", body);
export const deleteIntegration = (t: string, id: string) =>
  authedJson(t, "DELETE", `/api/v1/integrations/${id}`);

// ───────────────────────── Admin: MCP capabilities (edge) ─────────────────────────
// A single MCP tool the connected provider exposes (from the live tools/list).
export type MCPToolSpec = { name: string; description: string };
// The admin MCP capability probe. The edge times one tools/list handshake — which
// doubles as a health check + version negotiation — and ALWAYS returns 200
// (fail-soft): `status` carries ok | error | disabled instead of an HTTP error.
export type MCPCapabilities = {
  enabled: boolean;
  status: "ok" | "error" | "disabled";
  protocol_version: string;
  latency_ms: number;
  checked_at: string; // ISO8601
  tools: MCPToolSpec[];
};

// Probe one MCP provider's live capabilities (admin-only; SUPER_ADMIN or
// WORKSPACE_ADMIN). Goes straight to the edge admin endpoint — the edge holds the
// MCP session. The client modal hits the same-origin proxy instead (it can't
// import this server-only module); this server helper exists for SSR/parity.
export async function getMCPCapabilities(
  token: string,
  provider: string,
): Promise<MCPCapabilities | null> {
  const edge = process.env.EDGE_URL ?? "http://localhost:8080";
  try {
    const res = await fetch(
      `${edge}/api/v1/admin/mcp/capabilities?provider=${encodeURIComponent(provider)}`,
      { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" },
    );
    if (!res.ok) return null;
    return (await res.json()) as MCPCapabilities;
  } catch {
    return null;
  }
}

// ───────────────────────── Admin: directory CRUD ─────────────────────────
// Mutations use authedJson so callers can surface the 409 duplicate-name case.
const dir = (orgId: string) => `/api/v1/admin/orgs/${orgId}`;

export const listDepartments = (t: string, orgId: string) =>
  authedGet<Department[]>(t, `${dir(orgId)}/departments`, []);
export const createDepartment = (
  t: string,
  orgId: string,
  body: { name: string; owner_user_id?: string | null; parent_department_id?: string | null },
) => authedJson(t, "POST", `${dir(orgId)}/departments`, body);
export const updateDepartment = (
  t: string,
  orgId: string,
  deptId: string,
  body: { name?: string; owner_user_id?: string | null; parent_department_id?: string | null },
) => authedJson(t, "PATCH", `${dir(orgId)}/departments/${deptId}`, body);
export const deleteDepartment = (t: string, orgId: string, deptId: string) =>
  authedJson(t, "DELETE", `${dir(orgId)}/departments/${deptId}`);

export const listLocations = (t: string, orgId: string) =>
  authedGet<Location[]>(t, `${dir(orgId)}/locations`, []);
export const createLocation = (
  t: string,
  orgId: string,
  body: { name: string; city?: string | null; country?: string | null },
) => authedJson(t, "POST", `${dir(orgId)}/locations`, body);
export const updateLocation = (
  t: string,
  orgId: string,
  locId: string,
  body: { name?: string; city?: string | null; country?: string | null },
) => authedJson(t, "PATCH", `${dir(orgId)}/locations/${locId}`, body);
export const deleteLocation = (t: string, orgId: string, locId: string) =>
  authedJson(t, "DELETE", `${dir(orgId)}/locations/${locId}`);

export const getOrgChart = (t: string, orgId: string) =>
  authedGet<OrgChartNode[]>(t, `${dir(orgId)}/org-chart`, []);

// ───────────────────────── Scheduled tasks (cron jobs) ─────────────────────────
// A scheduled task runs `prompt` on a `cron` schedule (in `timezone`) for the
// current user. The control plane computes next_run_at; a separate scheduler
// worker executes due tasks and writes a notification. Current-user scoped.
export type ScheduledTask = {
  id: string;
  org_id: string;
  user_id: string; // owner
  workspace_id: string;
  name: string;
  prompt: string;
  cron: string; // standard 5-field cron expression
  timezone: string;
  enabled: boolean;
  web_search: boolean;
  deep_search: boolean;
  model: string | null;
  answer_style: AnswerStyle | null;
  next_run_at: string | null;
  last_run_at: string | null;
  last_status: "ok" | "error" | null;
  created_at: string;
  updated_at: string;
};

// Body for create. cron is a standard 5-field expression; timezone is IANA
// (blank = DEFAULT_TIMEZONE server-side, UTC by default). model/answer_style are optional pins.
export type ScheduledTaskInput = {
  name: string;
  workspace_id: string;
  prompt: string;
  cron: string;
  timezone?: string;
  web_search?: boolean;
  deep_search?: boolean;
  model?: string | null;
  answer_style?: AnswerStyle | null;
  enabled?: boolean;
};

// Body for update — every field optional (partial patch).
export type ScheduledTaskPatch = Partial<ScheduledTaskInput>;

export const listScheduledTasks = (t: string) =>
  authedGet<ScheduledTask[]>(t, "/api/v1/scheduled-tasks", []);
// Mutations use authedJson so callers can surface the 400 (bad cron / workspace) case.
export const createScheduledTask = (t: string, body: ScheduledTaskInput) =>
  authedJson(t, "POST", "/api/v1/scheduled-tasks", body);
export const updateScheduledTask = (t: string, id: string, body: ScheduledTaskPatch) =>
  authedJson(t, "PUT", `/api/v1/scheduled-tasks/${id}`, body);
export const deleteScheduledTask = (t: string, id: string) =>
  authedJson(t, "DELETE", `/api/v1/scheduled-tasks/${id}`);

// ───────────────────────── Notifications (in-app inbox) ─────────────────────────
export type Notification = {
  id: string;
  org_id: string;
  user_id: string;
  task_id: string | null;
  kind: string; // 'task_result' (default)
  title: string;
  body: string;
  is_read: boolean;
  created_at: string;
};
export type NotificationsResponse = { items: Notification[]; unread: number };

// The caller's latest ~50 notifications + unread count (the badge).
export const listNotifications = (t: string) =>
  authedGet<NotificationsResponse>(t, "/api/v1/notifications", { items: [], unread: 0 });
export const markNotificationRead = (t: string, id: string) =>
  authedJson(t, "POST", `/api/v1/notifications/${id}/read`);
export const markAllNotificationsRead = (t: string) =>
  authedJson(t, "POST", "/api/v1/notifications/read-all");
export const deleteNotification = (t: string, id: string) =>
  authedJson(t, "DELETE", `/api/v1/notifications/${id}`);
