// SPDX-License-Identifier: Apache-2.0

"use client";

import {
  Fragment,
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  useTransition,
  type DragEvent,
} from "react";
import { useLocale, useTranslations } from "next-intl";
import Link from "next/link";

import {
  archiveDocumentAction,
  createFolderAction,
  deleteDocumentAction,
  deleteFolderAction,
  moveDocumentAction,
  reindexAction,
  renameFolderAction,
  retryFailedAction,
} from "@/app/admin/knowledge-base/actions";
import { uploadFileResumable } from "@/lib/upload";
import { uploadFailureMessage } from "@/lib/upload-errors";
import type { DocumentFolder, DocumentRow, DocumentStatus, WorkspaceSummary } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardBody } from "@/components/ui/card";
import { Badge, STATUS_TONE } from "@/components/ui/badge";
import { Icon } from "@/components/ui/icon";
import { FileGlyph } from "@/components/ui/file-glyph";
import { Modal } from "@/components/ui/modal";
import Select from "@/components/ui/select";
import DropdownMenu, { type DropdownItem } from "@/components/ui/dropdown-menu";
import DocumentFailureReason from "@/components/admin/document-failure-reason";
import DocumentTree, { type FolderAction } from "@/components/admin/document-tree";

type UploadStatus = "queued" | "uploading" | "done" | "failed";
type ViewMode = "grid" | "list";

type UploadItem = {
  id: string;
  name: string;
  size: number;
  sent: number;
  status: UploadStatus;
  error?: string;
  // Retained so a failed upload can be retried without re-picking the file.
  file: File;
};

const POLL_INTERVAL_MS = 4000;
// Folder and file tiles: as many columns as fit, never narrower than ~13 rem, so
// names stay readable (two lines) at laptop and wide widths alike.
// File names rarely have spaces: offer line breaks after _ and - so a long name
// wraps at its word boundaries ("Teknik_Mimari_" / "NebulaCRM_2026.pdf")
// instead of mid-word (not after "." so the extension never sits alone);
// break-words still splits a single overlong segment.
function breakableName(name: string) {
  return name.split(/(?<=[_-])/).map((part, i) => (
    <Fragment key={i}>
      {i > 0 ? <wbr /> : null}
      {part}
    </Fragment>
  ));
}

const GRID_CLASS = "grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(13rem,1fr))]";
// Mirrors the backend auto-retry cap; used only to render "attempt n/3".
const MAX_DOC_RETRIES = 3;

function humanSize(bytes: number | null | undefined): string {
  if (bytes == null || Number.isNaN(bytes)) return "—";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value >= 100 || unit === 0 ? 0 : 1)} ${units[unit]}`;
}

// Short date in the UI locale — e.g. "4 Jun 2026" / "4 Haz 2026". Guards empty / invalid input.
const DATE_FMTS = new Map<string, Intl.DateTimeFormat>();
function fmtDate(iso: string, locale: string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  let fmt = DATE_FMTS.get(locale);
  if (!fmt) {
    fmt = new Intl.DateTimeFormat(locale, { day: "numeric", month: "short", year: "numeric" });
    DATE_FMTS.set(locale, fmt);
  }
  return fmt.format(d);
}

function isActive(status: DocumentStatus): boolean {
  return status === "PENDING" || status === "PROCESSING";
}

// File-type visuals now live in a dedicated Windows/Drive-style SVG badge —
// see <FileGlyph> in components/ui/file-glyph.tsx (color band + extension label).

// A folder action that needs a modal: rename, create (root / sub), move, delete.
type FolderDialog =
  | { kind: "create"; parentFolderId: string | null }
  | { kind: "rename"; folder: DocumentFolder }
  | { kind: "move"; folder: DocumentFolder }
  | { kind: "delete"; folder: DocumentFolder };

export default function KnowledgeBaseClient({
  workspaces,
  initialFolders,
  canRetryFailed = false,
}: {
  workspaces: WorkspaceSummary[];
  initialFolders: DocumentFolder[];
  // Retry-failed re-queues failed documents platform-wide: platform admin only.
  canRetryFailed?: boolean;
}) {
  const t = useTranslations("admin");

  const firstWsId = workspaces[0]?.id ?? "";
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState(firstWsId);
  // Per-workspace folder cache. undefined entry = not fetched yet. Seeded with
  // the first workspace's folders (fetched server-side on the page).
  const [foldersByWs, setFoldersByWs] = useState<Map<string, DocumentFolder[]>>(
    () => new Map(firstWsId ? [[firstWsId, initialFolders]] : []),
  );
  const [documents, setDocuments] = useState<DocumentRow[]>([]);
  // null = the workspace root (folder_id IS NULL).
  const [currentFolderId, setCurrentFolderId] = useState<string | null>(null);
  // The first workspace starts expanded so its tree shows immediately.
  const [expandedWorkspaces, setExpandedWorkspaces] = useState<Set<string>>(
    () => new Set(firstWsId ? [firstWsId] : []),
  );
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set());
  const [loadingDocs, setLoadingDocs] = useState(false);
  const [view, setView] = useState<ViewMode>("grid");
  // In-folder search query (client-side filter of the current folder's view).
  const [query, setQuery] = useState("");

  const [uploads, setUploads] = useState<UploadItem[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const [reindexing, startReindex] = useTransition();
  const [retrying, startRetry] = useTransition();
  // Brief outcome banner after a manual retry: how many docs were re-queued.
  const [retryResult, setRetryResult] = useState<number | null>(null);

  // Folder + document-move dialogs.
  const [folderDialog, setFolderDialog] = useState<FolderDialog | null>(null);
  const [moveDoc, setMoveDoc] = useState<DocumentRow | null>(null);
  // Pending destructive document action awaiting confirmation.
  const [docConfirm, setDocConfirm] = useState<{ doc: DocumentRow; kind: "archive" | "delete" } | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const dropzoneLabelId = useId();
  // In-flight upload controllers, so a user can cancel a running upload.
  const controllersRef = useRef<Map<string, AbortController>>(new Map());

  const selectedWorkspace = useMemo(
    () => workspaces.find((w) => w.id === selectedWorkspaceId),
    [workspaces, selectedWorkspaceId],
  );

  // The selected workspace's folders (drives breadcrumbs, child folders, move
  // targets). Empty until lazy-loaded.
  const folders = useMemo(
    () => foldersByWs.get(selectedWorkspaceId) ?? [],
    [foldersByWs, selectedWorkspaceId],
  );

  // Sub-folders of the current folder (for the contents pane).
  const childFolders = useMemo(
    () =>
      folders
        .filter((f) => (f.parent_folder_id ?? null) === currentFolderId)
        .sort((a, b) => a.name.localeCompare(b.name)),
    [folders, currentFolderId],
  );

  // Breadcrumb chain from root → current folder.
  const breadcrumbs = useMemo(() => {
    const byId = new Map(folders.map((f) => [f.id, f]));
    const chain: DocumentFolder[] = [];
    let cursor = currentFolderId ? byId.get(currentFolderId) : undefined;
    while (cursor) {
      chain.unshift(cursor);
      cursor = cursor.parent_folder_id ? byId.get(cursor.parent_folder_id) : undefined;
    }
    return chain;
  }, [folders, currentFolderId]);

  const hasActive = useMemo(() => documents.some((d) => isActive(d.status)), [documents]);
  // Failed in the current view (the retry endpoint is org-wide, but we only
  // surface the button when something visible failed).
  const failedCount = useMemo(
    () => documents.filter((d) => d.status === "FAILED").length,
    [documents],
  );

  const updateUpload = useCallback((id: string, patch: Partial<UploadItem>) => {
    setUploads((prev) => prev.map((u) => (u.id === id ? { ...u, ...patch } : u)));
  }, []);

  // ── Folder list (per workspace), cached in foldersByWs ──
  // Fetches a workspace's folder tree and stores it under that workspace id.
  const loadFolders = useCallback(async (workspaceId: string) => {
    if (!workspaceId) return;
    try {
      const res = await fetch(`/api/admin/workspaces/${workspaceId}/folders`, { cache: "no-store" });
      if (!res.ok) return;
      const list = (await res.json()) as DocumentFolder[];
      if (Array.isArray(list)) {
        setFoldersByWs((prev) => {
          const next = new Map(prev);
          next.set(workspaceId, list);
          return next;
        });
      }
    } catch {
      // Network blip — keep whatever is cached.
    }
  }, []);

  // Refresh the currently-selected workspace's folders (after a mutation).
  const refreshFolders = useCallback(
    () => loadFolders(selectedWorkspaceId),
    [loadFolders, selectedWorkspaceId],
  );

  // ── Documents in the current folder ──
  const refreshDocuments = useCallback(async () => {
    if (!selectedWorkspaceId) return;
    const scope = currentFolderId ?? "root";
    try {
      const res = await fetch(
        `/api/admin/workspaces/${selectedWorkspaceId}/documents?folder_id=${encodeURIComponent(scope)}`,
        { cache: "no-store" },
      );
      if (!res.ok) return;
      const list = (await res.json()) as DocumentRow[];
      if (Array.isArray(list)) setDocuments(list);
    } catch {
      // Network blip — keep current rows; the next tick retries.
    }
  }, [selectedWorkspaceId, currentFolderId]);

  // Load the current folder's documents whenever workspace/folder changes.
  // setState happens only inside the async callback, never synchronously.
  useEffect(() => {
    if (!selectedWorkspaceId) return;
    let cancelled = false;
    void (async () => {
      setLoadingDocs(true);
      await refreshDocuments();
      if (!cancelled) setLoadingDocs(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedWorkspaceId, currentFolderId, refreshDocuments]);

  // Live status polling while any visible document is PENDING/PROCESSING, so an
  // indexing tile visibly transitions PENDING → PROCESSING → SUCCESS.
  useEffect(() => {
    if (!hasActive) return;
    const timer = setInterval(refreshDocuments, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [hasActive, refreshDocuments]);

  // Cancel still-running uploads if the component unmounts.
  useEffect(() => {
    const controllers = controllersRef.current;
    return () => {
      controllers.forEach((c) => c.abort());
      controllers.clear();
    };
  }, []);

  const runUpload = useCallback(
    async (item: UploadItem, file: File) => {
      if (!selectedWorkspaceId) return;
      const controller = new AbortController();
      controllersRef.current.set(item.id, controller);
      updateUpload(item.id, { status: "uploading", sent: 0, error: undefined });

      const result = await uploadFileResumable(selectedWorkspaceId, file, {
        signal: controller.signal,
        folderId: currentFolderId,
        onProgress: (sent) => updateUpload(item.id, { sent }),
      });

      controllersRef.current.delete(item.id);

      if (result.ok) {
        updateUpload(item.id, { status: "done", sent: item.size });
        // A freshly completed document shows up as PENDING — pull it in.
        void refreshDocuments();
      } else if (result.aborted) {
        setUploads((prev) => prev.filter((u) => u.id !== item.id));
      } else {
        // Embedding-profile refusals get a translated explanation; anything
        // else keeps the server's message.
        const friendly = uploadFailureMessage(result);
        const error = friendly
          ? "values" in friendly
            ? t(friendly.key, friendly.values)
            : t(friendly.key)
          : result.error;
        updateUpload(item.id, { status: "failed", error });
      }
    },
    [selectedWorkspaceId, currentFolderId, updateUpload, refreshDocuments, t],
  );

  const enqueueFiles = useCallback(
    (files: File[]) => {
      if (!selectedWorkspaceId || files.length === 0) return;
      const items: UploadItem[] = files.map((file) => ({
        id: `${file.name}-${file.size}-${Date.now()}-${Math.random()
          .toString(36)
          .slice(2, 8)}`,
        name: file.name,
        size: file.size,
        sent: 0,
        status: "queued" as const,
        file,
      }));
      setUploads((prev) => [...items, ...prev]);
      // Kick them off; the uploader bounds per-file part concurrency internally.
      items.forEach((item) => void runUpload(item, item.file));
    },
    [selectedWorkspaceId, runUpload],
  );

  const handleFileList = useCallback(
    (list: FileList | null) => {
      if (!list) return;
      enqueueFiles(Array.from(list));
    },
    [enqueueFiles],
  );

  const retryUpload = useCallback(
    (id: string) => {
      setUploads((prev) => {
        const target = prev.find((u) => u.id === id);
        if (target) void runUpload(target, target.file);
        return prev;
      });
    },
    [runUpload],
  );

  const cancelUpload = useCallback((id: string) => {
    controllersRef.current.get(id)?.abort();
    // If it was still queued (no controller yet), drop it immediately.
    setUploads((prev) =>
      prev.filter((u) => u.id !== id || u.status === "uploading"),
    );
  }, []);

  const clearCompleted = useCallback(() => {
    setUploads((prev) =>
      prev.filter((u) => u.status !== "done" && u.status !== "failed"),
    );
  }, []);

  function onDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragOver(false);
    if (!selectedWorkspaceId) return;
    handleFileList(e.dataTransfer.files);
  }

  const handleReindex = useCallback(() => {
    if (!selectedWorkspaceId) return;
    startReindex(async () => {
      await reindexAction(selectedWorkspaceId);
      await refreshDocuments();
    });
  }, [selectedWorkspaceId, refreshDocuments]);

  const handleRetryFailed = useCallback(() => {
    startRetry(async () => {
      const retried = await retryFailedAction();
      setRetryResult(retried);
      await refreshDocuments();
    });
  }, [refreshDocuments]);

  // The same maintenance actions for the toolbar's overflow menu (narrow widths).
  const maintenanceItems: DropdownItem[] = [
    ...(canRetryFailed && failedCount > 0
      ? [
          {
            key: "retry",
            label: retrying ? t("retryFailedPending") : t("retryFailed", { count: failedCount }),
            icon: "restart_alt",
            onSelect: () => {
              if (!retrying) handleRetryFailed();
            },
          },
        ]
      : []),
    {
      key: "reindex",
      label: reindexing ? t("reindexing") : t("reindex"),
      icon: "autorenew",
      onSelect: () => {
        if (!reindexing) handleReindex();
      },
    },
  ];

  // ── Nav: workspaces + folders ──

  // Select a workspace: switch context to its root, ensure it's expanded and
  // its folders are loaded.
  const selectWorkspace = useCallback(
    (workspaceId: string) => {
      setSelectedWorkspaceId(workspaceId);
      setCurrentFolderId(null);
      setExpandedWorkspaces((prev) => new Set(prev).add(workspaceId));
      if (!foldersByWs.has(workspaceId)) void loadFolders(workspaceId);
    },
    [foldersByWs, loadFolders],
  );

  const toggleWorkspace = useCallback(
    (workspaceId: string) => {
      setExpandedWorkspaces((prev) => {
        const next = new Set(prev);
        if (next.has(workspaceId)) next.delete(workspaceId);
        else {
          next.add(workspaceId);
          // First expand → fetch its folders.
          if (!foldersByWs.has(workspaceId)) void loadFolders(workspaceId);
        }
        return next;
      });
    },
    [foldersByWs, loadFolders],
  );

  // Open a folder (select + ensure its ancestors are expanded). A folder always
  // belongs to the selected workspace's tree.
  const selectFolder = useCallback(
    (folderId: string | null) => {
      setCurrentFolderId(folderId);
      if (folderId) {
        const byId = new Map(folders.map((f) => [f.id, f]));
        const toOpen = new Set<string>();
        let cursor = byId.get(folderId);
        while (cursor) {
          toOpen.add(cursor.id);
          cursor = cursor.parent_folder_id ? byId.get(cursor.parent_folder_id) : undefined;
        }
        setExpandedFolders((prev) => new Set([...prev, ...toOpen]));
      }
    },
    [folders],
  );

  const toggleFolder = useCallback((folderId: string) => {
    setExpandedFolders((prev) => {
      const next = new Set(prev);
      if (next.has(folderId)) next.delete(folderId);
      else next.add(folderId);
      return next;
    });
  }, []);

  const onFolderAction = useCallback((action: FolderAction, folder: DocumentFolder) => {
    if (action === "rename") setFolderDialog({ kind: "rename", folder });
    else if (action === "move") setFolderDialog({ kind: "move", folder });
    else if (action === "delete") setFolderDialog({ kind: "delete", folder });
    else if (action === "newSub") setFolderDialog({ kind: "create", parentFolderId: folder.id });
  }, []);

  // "New root folder" from a workspace row: ensure that workspace is the active
  // one, then open the create-at-root dialog.
  const onNewRootFolder = useCallback(
    (workspaceId: string) => {
      if (workspaceId !== selectedWorkspaceId) selectWorkspace(workspaceId);
      setFolderDialog({ kind: "create", parentFolderId: null });
    },
    [selectedWorkspaceId, selectWorkspace],
  );

  // Confirm a document archive/delete (after the confirm modal).
  const confirmDocAction = useCallback(async () => {
    if (!docConfirm || !selectedWorkspaceId) return;
    const { doc, kind } = docConfirm;
    setDocConfirm(null);
    if (kind === "archive") await archiveDocumentAction(selectedWorkspaceId, doc.id);
    else await deleteDocumentAction(selectedWorkspaceId, doc.id);
    await refreshDocuments();
  }, [docConfirm, selectedWorkspaceId, refreshDocuments]);

  // No workspace yet → can't upload anywhere. Guide the admin to create one.
  if (workspaces.length === 0) {
    return (
      <Card>
        <CardBody>
          <div className="flex flex-col items-center justify-center gap-3 px-6 py-14 text-center">
            <span className="grid h-12 w-12 place-items-center rounded-2xl bg-surface-2 text-ink-muted">
              <Icon name="workspaces" size={24} />
            </span>
            <h3 className="font-display text-lg font-semibold tracking-tight text-ink">
              {t("noWorkspaces")}
            </h3>
            <p className="max-w-sm text-sm text-ink-muted">{t("kbSubtitle")}</p>
            <div className="mt-1 flex flex-wrap justify-center gap-2">
              <Link href="/admin/workspaces">
                <Button>
                  <Icon name="add" size={18} />
                  {t("createWorkspace")}
                </Button>
              </Link>
              <Link href="/admin/teams">
                <Button variant="ghost">
                  <Icon name="add" size={18} />
                  {t("createTeam")}
                </Button>
              </Link>
            </div>
          </div>
        </CardBody>
      </Card>
    );
  }

  const currentFolderName = breadcrumbs.at(-1)?.name ?? "";
  const workspaceName = selectedWorkspace?.name ?? "";
  const isEmpty = childFolders.length === 0 && documents.length === 0;

  // Drive-style in-folder search: live-filter the current folder's sub-folders
  // and documents by name (Turkish-aware lowercasing). Scoped to this folder.
  const q = query.trim().toLocaleLowerCase("tr");
  const searching = q.length > 0;
  const shownFolders = searching
    ? childFolders.filter((f) => f.name.toLocaleLowerCase("tr").includes(q))
    : childFolders;
  const shownDocuments = searching
    ? documents.filter((d) => d.filename.toLocaleLowerCase("tr").includes(q))
    : documents;
  const noResults = searching && shownFolders.length === 0 && shownDocuments.length === 0;

  return (
    <div className="space-y-4">
      {/* Calm confirmation after a manual retry — auto-clears on next refresh. */}
      {retryResult != null ? (
        <div
          role="status"
          className="rounded-2xl border border-border bg-surface px-4 py-2.5 text-sm text-ink-muted"
        >
          {t("retryFailedResult", { count: retryResult })}
        </div>
      ) : null}

      {/* Drive layout: a workspace + folder nav rail (left) + the contents (right). */}
      <div className="grid gap-4 lg:grid-cols-[17rem_1fr]">
        <Card className="h-fit">
          <CardBody className="space-y-1">
            <DocumentTree
              workspaces={workspaces}
              foldersByWs={foldersByWs}
              selectedWorkspaceId={selectedWorkspaceId}
              currentFolderId={currentFolderId}
              expandedWorkspaces={expandedWorkspaces}
              expandedFolders={expandedFolders}
              onSelectWorkspace={selectWorkspace}
              onToggleWorkspace={toggleWorkspace}
              onSelectFolder={selectFolder}
              onToggleFolder={toggleFolder}
              onFolderAction={onFolderAction}
              onNewRootFolder={onNewRootFolder}
            />
          </CardBody>
        </Card>

        {/* The main "My Drive" surface: breadcrumbs + toolbar + contents. The
            whole surface is a dropzone; dragging files reveals an overlay. */}
        <Card
          className="relative overflow-hidden"
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={(e) => {
            // Only clear when the pointer truly leaves the surface, not when it
            // crosses a child element.
            if (!e.currentTarget.contains(e.relatedTarget as Node)) setDragOver(false);
          }}
          onDrop={onDrop}
        >
          {/* Toolbar row: clickable breadcrumbs + view toggle + primary actions. */}
          <div className="@container flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-3.5">
            <nav
              aria-label={t("kbBreadcrumbs")}
              className="flex min-w-0 flex-wrap items-center gap-0.5 text-sm"
            >
              {/* First crumb = the selected workspace's root. */}
              <button
                type="button"
                onClick={() => selectFolder(null)}
                className={`flex items-center gap-1.5 rounded-lg px-2 py-1 transition hover:bg-surface-2 ${
                  currentFolderId === null ? "font-semibold text-ink" : "text-ink-muted"
                }`}
              >
                <Icon name="workspaces" size={16} className="shrink-0" fill={currentFolderId === null} />
                <span className="max-w-[12rem] truncate">{workspaceName}</span>
              </button>
              {breadcrumbs.map((f, i) => (
                <span key={f.id} className="flex items-center gap-0.5">
                  <Icon name="chevron_right" size={16} className="shrink-0 text-ink-muted" />
                  <button
                    type="button"
                    onClick={() => selectFolder(f.id)}
                    className={`max-w-[12rem] truncate rounded-lg px-2 py-1 transition hover:bg-surface-2 ${
                      i === breadcrumbs.length - 1 ? "font-semibold text-ink" : "text-ink-muted"
                    }`}
                  >
                    {f.name}
                  </button>
                </span>
              ))}
            </nav>

            {/* The basis drops the whole action group below the breadcrumbs on a
                narrow panel instead of squeezing it into a tall column. */}
            <div className="flex min-w-0 flex-1 basis-[22rem] flex-wrap items-center justify-end gap-2">
              {/* In-folder search — live-filters the current folder's contents. */}
              <div className="relative min-w-[11rem] flex-1 sm:max-w-[16rem]">
                <Icon
                  name="search"
                  size={16}
                  className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-muted"
                />
                <input
                  type="text"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder={t("kbSearchPlaceholder")}
                  aria-label={t("kbSearch")}
                  className="h-9 w-full rounded-full border border-border bg-surface pl-8 pr-8 text-sm text-ink outline-none transition placeholder:text-ink-muted focus-visible:border-brand focus-visible:ring-4 focus-visible:ring-brand/15"
                />
                {query ? (
                  <button
                    type="button"
                    onClick={() => setQuery("")}
                    aria-label={t("kbSearchClear")}
                    className="absolute right-1.5 top-1/2 grid h-6 w-6 -translate-y-1/2 place-items-center rounded-full text-ink-muted transition hover:bg-surface-2 hover:text-ink"
                  >
                    <Icon name="close" size={14} />
                  </button>
                ) : null}
              </div>
              {/* Quiet maintenance actions: reindex + (when needed) retry. Inline on
                  wide screens; below 2xl they move into the "more actions" menu so
                  the primary actions never get pushed off the toolbar. */}
              <div className="2xl:hidden">
                <DropdownMenu
                  items={maintenanceItems}
                  ariaLabel={t("kbMoreActions")}
                  renderTrigger={(props) => (
                    <button
                      {...props}
                      type="button"
                      title={t("kbMoreActions")}
                      className="grid h-9 w-9 place-items-center rounded-full border border-border bg-surface text-ink-muted transition hover:bg-surface-2 hover:text-ink"
                    >
                      <Icon name={reindexing || retrying ? "progress_activity" : "more_horiz"} size={18} className={reindexing || retrying ? "animate-spin" : ""} />
                    </button>
                  )}
                />
              </div>
              <div className="hidden items-center gap-2 2xl:flex">
                {canRetryFailed && failedCount > 0 ? (
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={retrying}
                    onClick={handleRetryFailed}
                    title={t("retryFailedHint")}
                  >
                    <Icon
                      name="restart_alt"
                      size={16}
                      className={`text-danger ${retrying ? "animate-spin" : ""}`}
                    />
                    {retrying
                      ? t("retryFailedPending")
                      : t("retryFailed", { count: failedCount })}
                  </Button>
                ) : null}
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={reindexing || !selectedWorkspaceId}
                  onClick={handleReindex}
                  title={t("reindexHint")}
                >
                  <Icon
                    name="autorenew"
                    size={16}
                    className={reindexing ? "animate-spin" : ""}
                  />
                  {reindexing ? t("reindexing") : t("reindex")}
                </Button>
              </div>

              {/* View toggle — grid (default) / list. */}
              <div className="flex items-center rounded-xl border border-border bg-surface p-0.5">
                <button
                  type="button"
                  onClick={() => setView("grid")}
                  aria-pressed={view === "grid"}
                  aria-label={t("kbViewGrid")}
                  title={t("kbViewGrid")}
                  className={`grid h-7 w-7 place-items-center rounded-lg transition ${
                    view === "grid" ? "bg-surface-3 text-ink" : "text-ink-muted hover:text-ink"
                  }`}
                >
                  <Icon name="grid_view" size={16} fill={view === "grid"} />
                </button>
                <button
                  type="button"
                  onClick={() => setView("list")}
                  aria-pressed={view === "list"}
                  aria-label={t("kbViewList")}
                  title={t("kbViewList")}
                  className={`grid h-7 w-7 place-items-center rounded-lg transition ${
                    view === "list" ? "bg-surface-3 text-ink" : "text-ink-muted hover:text-ink"
                  }`}
                >
                  <Icon name="view_list" size={16} fill={view === "list"} />
                </button>
              </div>

              <Button
                variant="outline"
                size="sm"
                onClick={() => setFolderDialog({ kind: "create", parentFolderId: currentFolderId })}
                aria-label={t("kbNewFolder")}
                title={t("kbNewFolder")}
              >
                <Icon name="create_new_folder" size={16} />
                {/* Icon-only on a narrow toolbar; the label returns once it fits. */}
                <span className="hidden @[44rem]:inline">{t("kbNewFolder")}</span>
              </Button>
              <Button size="sm" onClick={() => fileInputRef.current?.click()}>
                <Icon name="upload" size={16} />
                {t("kbUpload")}
              </Button>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept=".pdf,.docx,.xlsx,.pptx,.txt,.md,.png,.jpg,.jpeg,.tif,.tiff,.webp,.bmp"
                className="hidden"
                onChange={(e) => {
                  handleFileList(e.target.files);
                  e.target.value = "";
                }}
              />
            </div>
          </div>

          {/* Active / recent uploads with per-file progress (collapses when idle). */}
          {uploads.length > 0 ? (
            <div className="space-y-3 border-b border-border px-5 py-4">
              <div className="flex items-center justify-between">
                <span className="font-display text-sm font-semibold text-ink">
                  {t("uploadsTitle")}
                </span>
                {uploads.some((u) => u.status === "done" || u.status === "failed") ? (
                  <Button variant="subtle" size="sm" onClick={clearCompleted}>
                    {t("clearCompleted")}
                  </Button>
                ) : null}
              </div>
              {uploads.map((u) => (
                <UploadRow
                  key={u.id}
                  item={u}
                  t={t}
                  onCancel={() => cancelUpload(u.id)}
                  onRetry={() => retryUpload(u.id)}
                />
              ))}
            </div>
          ) : null}

          {/* Contents: empty-state, else the grid (default) or the list view. */}
          {isEmpty ? (
            <div
              role="button"
              tabIndex={0}
              aria-labelledby={dropzoneLabelId}
              onClick={() => fileInputRef.current?.click()}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  fileInputRef.current?.click();
                }
              }}
              className="flex cursor-pointer flex-col items-center justify-center gap-3 px-6 py-16 text-center outline-none focus-visible:bg-surface-2/50"
            >
              <span className="grid h-14 w-14 place-items-center rounded-2xl bg-surface-2 text-ink-muted">
                <Icon name={loadingDocs ? "hourglass_empty" : "folder_open"} size={28} />
              </span>
              <div className="space-y-1" id={dropzoneLabelId}>
                <h3 className="font-display text-base font-semibold tracking-tight text-ink">
                  {loadingDocs ? t("kbLoading") : t("kbEmptyTitle")}
                </h3>
                {!loadingDocs ? (
                  <p className="max-w-xs text-sm text-ink-muted">{t("kbEmptyHint")}</p>
                ) : null}
              </div>
            </div>
          ) : noResults ? (
            <div className="flex flex-col items-center justify-center gap-3 px-6 py-16 text-center">
              <span className="grid h-14 w-14 place-items-center rounded-2xl bg-surface-2 text-ink-muted">
                <Icon name="search_off" size={28} />
              </span>
              <div className="space-y-1">
                <h3 className="font-display text-base font-semibold tracking-tight text-ink">
                  {t("kbNoResultsTitle")}
                </h3>
                <p className="max-w-xs text-sm text-ink-muted">
                  {t("kbNoResultsHint", { query: query.trim() })}
                </p>
              </div>
              <Button variant="ghost" size="sm" onClick={() => setQuery("")}>
                <Icon name="close" size={16} />
                {t("kbSearchClear")}
              </Button>
            </div>
          ) : view === "grid" ? (
            <div className="space-y-6 px-5 py-5">
              {shownFolders.length > 0 ? (
                <section className="space-y-3">
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-muted">
                    {t("kbFoldersSection")}
                  </h3>
                  <div className={GRID_CLASS}>
                    {shownFolders.map((f) => (
                      <FolderTile
                        key={f.id}
                        folder={f}
                        t={t}
                        onOpen={() => selectFolder(f.id)}
                        onRename={() => setFolderDialog({ kind: "rename", folder: f })}
                        onMove={() => setFolderDialog({ kind: "move", folder: f })}
                        onDelete={() => setFolderDialog({ kind: "delete", folder: f })}
                      />
                    ))}
                  </div>
                </section>
              ) : null}

              {shownDocuments.length > 0 ? (
                <section className="space-y-3">
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-muted">
                    {t("kbFilesSection")}
                  </h3>
                  <div className={GRID_CLASS}>
                    {shownDocuments.map((doc) => (
                      <FileTile
                        key={doc.id}
                        doc={doc}
                        t={t}
                        onMove={() => setMoveDoc(doc)}
                        onArchive={() => setDocConfirm({ doc, kind: "archive" })}
                        onDelete={() => setDocConfirm({ doc, kind: "delete" })}
                      />
                    ))}
                  </div>
                </section>
              ) : null}
            </div>
          ) : (
            <>
              {/* List view: a calm, Drive-like column header + rows. */}
              <div className="flex items-center gap-3 px-5 py-2.5 text-xs font-medium uppercase tracking-wide text-ink-muted">
                <span className="flex-1">{t("kbName")}</span>
                <span className="hidden w-28 shrink-0 sm:block">{t("colStatus")}</span>
                <span className="hidden w-20 shrink-0 text-right md:block">{t("colSize")}</span>
                <span className="hidden w-24 shrink-0 text-right lg:block">{t("colAdded")}</span>
                <span className="w-8 shrink-0" />
              </div>
              <div className="divide-y divide-border">
                {shownFolders.map((f) => (
                  <FolderListRow
                    key={f.id}
                    folder={f}
                    t={t}
                    onOpen={() => selectFolder(f.id)}
                    onRename={() => setFolderDialog({ kind: "rename", folder: f })}
                    onMove={() => setFolderDialog({ kind: "move", folder: f })}
                    onDelete={() => setFolderDialog({ kind: "delete", folder: f })}
                  />
                ))}
                {shownDocuments.map((doc) => (
                  <DocumentListRow
                    key={doc.id}
                    doc={doc}
                    t={t}
                    onMove={() => setMoveDoc(doc)}
                    onArchive={() => setDocConfirm({ doc, kind: "archive" })}
                    onDelete={() => setDocConfirm({ doc, kind: "delete" })}
                  />
                ))}
              </div>
            </>
          )}

          {/* Quiet footer count (shown whenever there's content). */}
          {!isEmpty && !noResults ? (
            <div className="border-t border-border px-5 py-2.5 text-xs text-ink-muted">
              {t("kbItemCount", {
                folders: shownFolders.length,
                documents: shownDocuments.length,
              })}
            </div>
          ) : null}

          {/* Drag overlay — appears over the whole surface while dragging files. */}
          {dragOver ? (
            <div className="pointer-events-none absolute inset-0 z-10 flex flex-col items-center justify-center gap-3 rounded-[inherit] border-2 border-dashed border-brand bg-brand/5 backdrop-blur-[1px]">
              <span className="grid h-14 w-14 place-items-center rounded-2xl bg-brand/10 text-brand">
                <Icon name="upload_file" size={28} />
              </span>
              <p className="text-sm font-medium text-ink">
                {currentFolderId
                  ? t("kbUploadIntoFolder", { folder: currentFolderName })
                  : t("kbDropToUpload")}
              </p>
            </div>
          ) : null}
        </Card>
      </div>

      {/* ── Folder create / rename / move / delete ── */}
      {folderDialog ? (
        <FolderDialogModal
          dialog={folderDialog}
          folders={folders}
          onClose={() => setFolderDialog(null)}
          onCreate={async (name, parentFolderId) => {
            const created = await createFolderAction(selectedWorkspaceId, name, parentFolderId);
            setFolderDialog(null);
            await refreshFolders();
            if (created) selectFolder(created.id);
          }}
          onRename={async (folder, name) => {
            await renameFolderAction(selectedWorkspaceId, folder.id, { name });
            setFolderDialog(null);
            await refreshFolders();
          }}
          onMoveFolder={async (folder, parentFolderId) => {
            await renameFolderAction(selectedWorkspaceId, folder.id, { parent_folder_id: parentFolderId });
            setFolderDialog(null);
            await refreshFolders();
          }}
          onDelete={async (folder) => {
            await deleteFolderAction(selectedWorkspaceId, folder.id);
            setFolderDialog(null);
            // If we were inside the deleted subtree, fall back to root.
            if (currentFolderId === folder.id) setCurrentFolderId(null);
            await refreshFolders();
            await refreshDocuments();
          }}
        />
      ) : null}

      {/* ── Move a document to a folder ── */}
      {moveDoc ? (
        <MoveDocumentModal
          doc={moveDoc}
          folders={folders}
          t={t}
          onClose={() => setMoveDoc(null)}
          onMove={async (folderId) => {
            await moveDocumentAction(selectedWorkspaceId, moveDoc.id, folderId);
            setMoveDoc(null);
            await refreshDocuments();
          }}
        />
      ) : null}

      {/* ── Confirm archive / delete a document ── */}
      {docConfirm ? (
        <Modal
          open
          onClose={() => setDocConfirm(null)}
          title={docConfirm.kind === "archive" ? t("kbArchiveTitle") : t("kbDeleteDocTitle")}
          description={
            docConfirm.kind === "archive"
              ? t("kbArchiveConfirm", { name: docConfirm.doc.filename })
              : t("kbDeleteDocConfirm", { name: docConfirm.doc.filename })
          }
          footer={
            <>
              <Button variant="ghost" onClick={() => setDocConfirm(null)}>
                {t("cancel")}
              </Button>
              <Button
                variant={docConfirm.kind === "delete" ? "danger" : "primary"}
                onClick={confirmDocAction}
              >
                {docConfirm.kind === "archive" ? t("kbArchive") : t("kbDelete")}
              </Button>
            </>
          }
        >
          <p className="text-sm text-ink-muted">
            {docConfirm.kind === "archive" ? t("kbArchiveHint") : t("kbDeleteDocHint")}
          </p>
        </Modal>
      ) : null}
    </div>
  );
}

// ───────────────────────── Drive grid tiles ─────────────────────────

function FolderTile({
  folder,
  t,
  onOpen,
  onRename,
  onMove,
  onDelete,
}: {
  folder: DocumentFolder;
  t: ReturnType<typeof useTranslations>;
  onOpen: () => void;
  onRename: () => void;
  onMove: () => void;
  onDelete: () => void;
}) {
  const items: DropdownItem[] = [
    { key: "open", label: t("kbOpen"), icon: "folder_open", onSelect: onOpen },
    { key: "rename", label: t("kbRename"), icon: "edit", onSelect: onRename },
    { key: "move", label: t("kbMove"), icon: "drive_file_move", onSelect: onMove },
    { key: "delete", label: t("kbDelete"), icon: "delete", danger: true, onSelect: onDelete },
  ];
  return (
    <div className="group relative rounded-2xl border border-border bg-surface p-3 transition hover:bg-surface-2 hover:shadow-[var(--shadow-lift)]">
      <button
        type="button"
        onClick={onOpen}
        onDoubleClick={onOpen}
        className="flex w-full items-center gap-3 text-left"
      >
        <span className="grid h-12 w-12 shrink-0 place-items-center rounded-xl bg-brand/10 text-brand">
          <Icon name="folder" size={26} fill />
        </span>
        <span className="min-w-0 flex-1 break-words pr-5 font-medium leading-snug text-ink line-clamp-2" title={folder.name}>
          {folder.name}
        </span>
      </button>
      <div className="absolute right-2 top-2">
        <DropdownMenu
          items={items}
          ariaLabel={t("kbFolderActions")}
          renderTrigger={(props) => (
            <button
              {...props}
              type="button"
              className="grid h-8 w-8 place-items-center rounded-full text-ink-muted opacity-0 transition hover:bg-surface-3 hover:text-ink focus-visible:opacity-100 group-hover:opacity-100 aria-expanded:opacity-100"
            >
              <Icon name="more_vert" size={18} />
            </button>
          )}
        />
      </div>
    </div>
  );
}

function FileTile({
  doc,
  t,
  onMove,
  onArchive,
  onDelete,
}: {
  doc: DocumentRow;
  t: ReturnType<typeof useTranslations>;
  onMove: () => void;
  onArchive: () => void;
  onDelete: () => void;
}) {
  const locale = useLocale();
  const items: DropdownItem[] = [
    { key: "move", label: t("kbMove"), icon: "drive_file_move", onSelect: onMove },
    // Archived docs cannot be archived again.
    ...(doc.status === "ARCHIVED"
      ? []
      : [{ key: "archive", label: t("kbArchive"), icon: "archive", onSelect: onArchive } as DropdownItem]),
    { key: "delete", label: t("kbDelete"), icon: "delete", danger: true, onSelect: onDelete },
  ];

  const indexing = isActive(doc.status);
  const archived = doc.status === "ARCHIVED";
  const failed = doc.status === "FAILED";
  // Indexing + archived tiles read as "not ready": dimmed; indexing also sweeps.
  const dim = indexing || archived;

  return (
    <div
      className={`group relative overflow-hidden rounded-2xl border bg-surface p-3 transition hover:bg-surface-2 hover:shadow-[var(--shadow-lift)] ${
        failed ? "border-danger/40" : "border-border"
      }`}
      title={indexing ? t("kbIndexingHint") : undefined}
    >
      {/* Slow light sweep across the tile while it is being indexed. */}
      {indexing ? <span className="kb-sweep" aria-hidden /> : null}

      <div>
        <div className="flex items-start gap-3">
          <FileGlyph filename={doc.filename} className={`h-12 w-12 shrink-0 ${dim ? "opacity-55" : ""}`} />
          <span
            className={`min-w-0 flex-1 break-words pr-5 text-sm font-medium leading-snug line-clamp-3 ${
              dim ? "text-ink-muted" : "text-ink"
            }`}
            title={doc.filename}
          >
            {breakableName(doc.filename)}
          </span>
        </div>
        <div className="mt-2 text-xs tabular-nums text-ink-muted">
          {humanSize(doc.file_size)} · {fmtDate(doc.created_at, locale)}
        </div>
      </div>

      {/* Status area: indexing spinner / failed attempts / status chip. */}
      <div className="mt-2.5">
        {indexing ? (
          <span className="inline-flex items-center gap-1.5 text-xs font-medium text-brand">
            <Icon name="progress_activity" size={14} className="animate-spin" />
            {t("kbIndexing")}
          </span>
        ) : failed ? (
          <span className="inline-flex items-center gap-1.5">
            <Badge tone={STATUS_TONE.FAILED ?? "danger"} dot>
              {t("statusFAILED")}
            </Badge>
            {doc.retry_count != null ? (
              <span className="text-xs tabular-nums text-ink-muted">
                {t("retryAttempts", { count: doc.retry_count, max: MAX_DOC_RETRIES })}
              </span>
            ) : null}
          </span>
        ) : (
          <span>
            <Badge tone={STATUS_TONE[doc.status] ?? "neutral"} dot>
              {t(`status${doc.status}`)}
            </Badge>
          </span>
        )}
        {failed ? <DocumentFailureReason doc={doc} className="mt-1.5" /> : null}
      </div>

      <div className="absolute right-2 top-2">
        <DropdownMenu
          items={items}
          ariaLabel={t("kbDocActions")}
          renderTrigger={(props) => (
            <button
              {...props}
              type="button"
              className="relative z-10 grid h-8 w-8 place-items-center rounded-full text-ink-muted opacity-0 transition hover:bg-surface-3 hover:text-ink focus-visible:opacity-100 group-hover:opacity-100 aria-expanded:opacity-100"
            >
              <Icon name="more_vert" size={18} />
            </button>
          )}
        />
      </div>
    </div>
  );
}

// ───────────────────────── List-view rows ─────────────────────────

function FolderListRow({
  folder,
  t,
  onOpen,
  onRename,
  onMove,
  onDelete,
}: {
  folder: DocumentFolder;
  t: ReturnType<typeof useTranslations>;
  onOpen: () => void;
  onRename: () => void;
  onMove: () => void;
  onDelete: () => void;
}) {
  const items: DropdownItem[] = [
    { key: "open", label: t("kbOpen"), icon: "folder_open", onSelect: onOpen },
    { key: "rename", label: t("kbRename"), icon: "edit", onSelect: onRename },
    { key: "move", label: t("kbMove"), icon: "drive_file_move", onSelect: onMove },
    { key: "delete", label: t("kbDelete"), icon: "delete", danger: true, onSelect: onDelete },
  ];
  return (
    <div className="group flex items-center gap-3 px-3 py-2.5 transition hover:bg-surface-2">
      <button
        type="button"
        onDoubleClick={onOpen}
        onClick={onOpen}
        className="flex min-w-0 flex-1 items-center gap-3 text-left"
      >
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-brand/10 text-brand">
          <Icon name="folder" size={20} fill />
        </span>
        <span className="truncate font-medium text-ink">{folder.name}</span>
      </button>
      {/* Status / size / date columns are document-only; folders keep them blank
          so the grid stays aligned. */}
      <span className="hidden w-28 shrink-0 sm:block" aria-hidden />
      <span className="hidden w-20 shrink-0 md:block" aria-hidden />
      <span className="hidden w-24 shrink-0 text-right text-xs text-ink-muted lg:block">
        {t("kbFolder")}
      </span>
      <DropdownMenu
        items={items}
        ariaLabel={t("kbFolderActions")}
        renderTrigger={(props) => (
          <button
            {...props}
            type="button"
            className="grid h-8 w-8 shrink-0 place-items-center rounded-full text-ink-muted opacity-0 transition hover:bg-surface-3 hover:text-ink focus-visible:opacity-100 group-hover:opacity-100 aria-expanded:opacity-100"
          >
            <Icon name="more_vert" size={18} />
          </button>
        )}
      />
    </div>
  );
}

function DocumentListRow({
  doc,
  t,
  onMove,
  onArchive,
  onDelete,
}: {
  doc: DocumentRow;
  t: ReturnType<typeof useTranslations>;
  onMove: () => void;
  onArchive: () => void;
  onDelete: () => void;
}) {
  const locale = useLocale();
  const items: DropdownItem[] = [
    { key: "move", label: t("kbMove"), icon: "drive_file_move", onSelect: onMove },
    // Archived docs cannot be archived again.
    ...(doc.status === "ARCHIVED"
      ? []
      : [{ key: "archive", label: t("kbArchive"), icon: "archive", onSelect: onArchive } as DropdownItem]),
    { key: "delete", label: t("kbDelete"), icon: "delete", danger: true, onSelect: onDelete },
  ];

  const indexing = isActive(doc.status);
  const archived = doc.status === "ARCHIVED";
  // Indexing + archived rows read as "not ready": dimmed; indexing also sweeps.
  const dim = indexing || archived;

  return (
    <div
      className="group relative flex items-center gap-3 px-3 py-2.5 transition hover:bg-surface-2"
      title={indexing ? t("kbIndexingHint") : undefined}
    >
      {/* Slow light sweep across the row while it is being indexed. */}
      {indexing ? <span className="kb-sweep" aria-hidden /> : null}

      <div className="flex min-w-0 flex-1 items-center gap-3">
        <FileGlyph filename={doc.filename} className={`h-9 w-9 shrink-0 ${dim ? "opacity-55" : ""}`} />
        <span className="min-w-0">
          <span className={`block truncate font-medium ${dim ? "text-ink-muted" : "text-ink"}`}>{doc.filename}</span>
          <DocumentFailureReason doc={doc} variant="compact" />
        </span>
      </div>

      {/* Status column: indexing gets a spinner + label; others a status chip. */}
      <div className="hidden w-28 shrink-0 sm:flex sm:items-center">
        {indexing ? (
          <span className="inline-flex items-center gap-1.5 text-xs font-medium text-brand">
            <Icon name="progress_activity" size={14} className="animate-spin" />
            {t("kbIndexing")}
          </span>
        ) : (
          <span className="inline-flex items-center gap-1.5">
            <Badge tone={STATUS_TONE[doc.status] ?? "neutral"} dot>
              {t(`status${doc.status}`)}
            </Badge>
            {doc.status === "FAILED" && doc.retry_count != null ? (
              <span className="hidden text-xs tabular-nums text-ink-muted lg:inline">
                {t("retryAttempts", { count: doc.retry_count, max: MAX_DOC_RETRIES })}
              </span>
            ) : null}
          </span>
        )}
      </div>

      <span
        className="hidden w-20 shrink-0 text-right tabular-nums text-xs text-ink-muted md:block"
      >
        {humanSize(doc.file_size)}
      </span>
      <span
        className="hidden w-24 shrink-0 whitespace-nowrap text-right text-xs text-ink-muted lg:block"
      >
        {fmtDate(doc.created_at, locale)}
      </span>

      <DropdownMenu
        items={items}
        ariaLabel={t("kbDocActions")}
        renderTrigger={(props) => (
          <button
            {...props}
            type="button"
            className="relative z-10 grid h-8 w-8 shrink-0 place-items-center rounded-full text-ink-muted opacity-0 transition hover:bg-surface-3 hover:text-ink focus-visible:opacity-100 group-hover:opacity-100 aria-expanded:opacity-100"
          >
            <Icon name="more_vert" size={18} />
          </button>
        )}
      />
    </div>
  );
}

// ───────────────────────── Folder dialogs ─────────────────────────

// Folders that may receive `folder` as a parent: everything except itself and
// its own descendants (which would create a cycle).
function eligibleParents(folders: DocumentFolder[], folderId: string): DocumentFolder[] {
  const childrenOf = new Map<string, DocumentFolder[]>();
  for (const f of folders) {
    if (!f.parent_folder_id) continue;
    const list = childrenOf.get(f.parent_folder_id) ?? [];
    list.push(f);
    childrenOf.set(f.parent_folder_id, list);
  }
  // Ban the folder itself + every descendant (re-parenting under them = a cycle).
  const banned = new Set<string>([folderId]);
  const stack = [folderId];
  while (stack.length) {
    const id = stack.pop()!;
    for (const child of childrenOf.get(id) ?? []) {
      if (!banned.has(child.id)) {
        banned.add(child.id);
        stack.push(child.id);
      }
    }
  }
  return folders.filter((f) => !banned.has(f.id));
}

function FolderDialogModal({
  dialog,
  folders,
  onClose,
  onCreate,
  onRename,
  onMoveFolder,
  onDelete,
}: {
  dialog: FolderDialog;
  folders: DocumentFolder[];
  onClose: () => void;
  onCreate: (name: string, parentFolderId: string | null) => Promise<void>;
  onRename: (folder: DocumentFolder, name: string) => Promise<void>;
  onMoveFolder: (folder: DocumentFolder, parentFolderId: string | null) => Promise<void>;
  onDelete: (folder: DocumentFolder) => Promise<void>;
}) {
  const t = useTranslations("admin");
  const [name, setName] = useState(dialog.kind === "rename" ? dialog.folder.name : "");
  const [parent, setParent] = useState<string>(
    dialog.kind === "move" ? (dialog.folder.parent_folder_id ?? "") : "",
  );
  const [busy, setBusy] = useState(false);
  const inputId = useId();

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    try {
      await fn();
    } finally {
      setBusy(false);
    }
  };

  if (dialog.kind === "delete") {
    return (
      <Modal
        open
        onClose={onClose}
        title={t("kbDeleteFolderTitle")}
        description={t("kbDeleteFolderConfirm", { name: dialog.folder.name })}
        footer={
          <>
            <Button variant="ghost" disabled={busy} onClick={onClose}>
              {t("cancel")}
            </Button>
            <Button variant="danger" disabled={busy} onClick={() => run(() => onDelete(dialog.folder))}>
              {busy ? t("kbDeleting") : t("kbDelete")}
            </Button>
          </>
        }
      >
        <p className="text-sm text-danger">{t("kbDeleteFolderHint")}</p>
      </Modal>
    );
  }

  if (dialog.kind === "move") {
    const options = [
      { value: "", label: t("kbRootDestination"), icon: "workspaces" },
      ...eligibleParents(folders, dialog.folder.id).map((f) => ({
        value: f.id,
        label: f.name,
        icon: "folder",
      })),
    ];
    return (
      <Modal
        open
        onClose={onClose}
        title={t("kbMoveFolderTitle")}
        description={t("kbMoveFolderHint", { name: dialog.folder.name })}
        footer={
          <>
            <Button variant="ghost" disabled={busy} onClick={onClose}>
              {t("cancel")}
            </Button>
            <Button
              disabled={busy}
              onClick={() => run(() => onMoveFolder(dialog.folder, parent || null))}
            >
              {busy ? t("kbMoving") : t("kbMove")}
            </Button>
          </>
        }
      >
        <Select
          options={options}
          value={parent}
          onValueChange={setParent}
          ariaLabel={t("kbDestination")}
          placeholder={t("kbRootDestination")}
        />
      </Modal>
    );
  }

  // create / rename share a single name field.
  const isRename = dialog.kind === "rename";
  const submit = () => {
    const trimmed = name.trim();
    if (!trimmed) return;
    if (isRename) void run(() => onRename(dialog.folder, trimmed));
    else void run(() => onCreate(trimmed, dialog.parentFolderId));
  };

  return (
    <Modal
      open
      onClose={onClose}
      title={isRename ? t("kbRenameFolderTitle") : t("kbNewFolderTitle")}
      footer={
        <>
          <Button variant="ghost" disabled={busy} onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button disabled={busy || !name.trim()} onClick={submit}>
            {busy ? t("kbSaving") : isRename ? t("kbRename") : t("kbCreate")}
          </Button>
        </>
      }
    >
      <label htmlFor={inputId} className="mb-1.5 block text-sm font-medium text-ink">
        {t("kbFolderName")}
      </label>
      <input
        id={inputId}
        autoFocus
        value={name}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            submit();
          }
        }}
        placeholder={t("kbFolderNamePlaceholder")}
        className="h-10 w-full rounded-xl border border-border bg-surface px-3.5 text-sm text-ink outline-none transition focus-visible:border-brand focus-visible:ring-4 focus-visible:ring-brand/15"
      />
    </Modal>
  );
}

function MoveDocumentModal({
  doc,
  folders,
  t,
  onClose,
  onMove,
}: {
  doc: DocumentRow;
  folders: DocumentFolder[];
  t: ReturnType<typeof useTranslations>;
  onClose: () => void;
  onMove: (folderId: string | null) => Promise<void>;
}) {
  const [target, setTarget] = useState<string>(doc.folder_id ?? "");
  const [busy, setBusy] = useState(false);
  const options = [
    { value: "", label: t("kbRootDestination"), icon: "workspaces" },
    ...folders
      .slice()
      .sort((a, b) => a.name.localeCompare(b.name))
      .map((f) => ({ value: f.id, label: f.name, icon: "folder" })),
  ];
  return (
    <Modal
      open
      onClose={onClose}
      title={t("kbMoveDocTitle")}
      description={t("kbMoveDocHint", { name: doc.filename })}
      footer={
        <>
          <Button variant="ghost" disabled={busy} onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await onMove(target || null);
              } finally {
                setBusy(false);
              }
            }}
          >
            {busy ? t("kbMoving") : t("kbMove")}
          </Button>
        </>
      }
    >
      <Select
        options={options}
        value={target}
        onValueChange={setTarget}
        ariaLabel={t("kbDestination")}
        placeholder={t("kbRootDestination")}
      />
    </Modal>
  );
}

function UploadRow({
  item,
  t,
  onCancel,
  onRetry,
}: {
  item: UploadItem;
  t: ReturnType<typeof useTranslations>;
  onCancel: () => void;
  onRetry: () => void;
}) {
  const pct =
    item.size > 0 ? Math.min(100, Math.round((item.sent / item.size) * 100)) : 0;

  const statusLabel =
    item.status === "queued"
      ? t("queued")
      : item.status === "uploading"
        ? `${pct}%`
        : item.status === "done"
          ? t("done")
          : t("uploadFailedShort");

  const active = item.status === "uploading" || item.status === "queued";

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <Icon
            name={
              item.status === "done"
                ? "check_circle"
                : item.status === "failed"
                  ? "error"
                  : "description"
            }
            size={16}
            className={`shrink-0 ${
              item.status === "done"
                ? "text-success"
                : item.status === "failed"
                  ? "text-danger"
                  : "text-ink-muted"
            }`}
          />
          <span className="truncate text-sm font-medium text-ink">{item.name}</span>
          <span className="shrink-0 text-xs text-ink-muted">{humanSize(item.size)}</span>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <span
            className={`text-xs tabular-nums ${
              item.status === "failed" ? "text-danger" : "text-ink-muted"
            }`}
          >
            {statusLabel}
          </span>
          {active ? (
            <Button
              variant="subtle"
              size="icon"
              aria-label={t("cancelUpload")}
              onClick={onCancel}
            >
              <Icon name="close" size={16} />
            </Button>
          ) : null}
          {item.status === "failed" ? (
            <Button
              variant="subtle"
              size="icon"
              aria-label={t("retryUpload")}
              onClick={onRetry}
            >
              <Icon name="autorenew" size={16} />
            </Button>
          ) : null}
        </div>
      </div>
      {active ? (
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-2">
          <div
            className="h-full rounded-full bg-brand transition-[width] duration-300 ease-out"
            style={{ width: `${pct}%` }}
            role="progressbar"
            aria-valuenow={pct}
            aria-valuemin={0}
            aria-valuemax={100}
          />
        </div>
      ) : null}
      {item.status === "failed" && item.error ? (
        <p className="text-xs text-danger">{item.error}</p>
      ) : null}
    </div>
  );
}
