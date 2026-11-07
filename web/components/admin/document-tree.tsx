// SPDX-License-Identifier: Apache-2.0

"use client";

// The Drive nav rail of the Knowledge Base. Lists every workspace as a
// top-level, expandable root; expanding a workspace reveals that workspace's
// document folders as an expand/collapse tree (built from a flat list via
// parent_folder_id). Selecting a workspace opens its root (folder_id IS NULL);
// selecting a folder opens that folder. A per-folder "…" menu exposes rename /
// move / new subfolder / delete, and a small "+" per workspace creates a root
// folder there. Purely presentational — all mutations + data live in the parent
// KnowledgeBaseClient, which lazy-loads each workspace's folders on demand.

import { useMemo } from "react";
import { useTranslations } from "next-intl";

import type { DocumentFolder, WorkspaceSummary } from "@/lib/api";
import { Icon } from "@/components/ui/icon";
import DropdownMenu, { type DropdownItem } from "@/components/ui/dropdown-menu";

export type FolderAction = "rename" | "move" | "newSub" | "delete";

// A folder plus its already-resolved children, for cheap recursive rendering.
type TreeNode = DocumentFolder & { children: TreeNode[] };

function buildTree(folders: DocumentFolder[]): TreeNode[] {
  const byId = new Map<string, TreeNode>();
  for (const f of folders) byId.set(f.id, { ...f, children: [] });
  const roots: TreeNode[] = [];
  for (const node of byId.values()) {
    const parent = node.parent_folder_id ? byId.get(node.parent_folder_id) : null;
    if (parent) parent.children.push(node);
    else roots.push(node);
  }
  const sortRec = (nodes: TreeNode[]) => {
    nodes.sort((a, b) => a.name.localeCompare(b.name));
    nodes.forEach((n) => sortRec(n.children));
  };
  sortRec(roots);
  return roots;
}

export default function DocumentTree({
  workspaces,
  foldersByWs,
  selectedWorkspaceId,
  currentFolderId,
  expandedWorkspaces,
  expandedFolders,
  onSelectWorkspace,
  onToggleWorkspace,
  onSelectFolder,
  onToggleFolder,
  onFolderAction,
  onNewRootFolder,
}: {
  workspaces: WorkspaceSummary[];
  // Per-workspace folder lists, lazily populated by the parent.
  foldersByWs: Map<string, DocumentFolder[]>;
  selectedWorkspaceId: string;
  // null = the selected workspace's root.
  currentFolderId: string | null;
  expandedWorkspaces: Set<string>;
  expandedFolders: Set<string>;
  onSelectWorkspace: (workspaceId: string) => void;
  onToggleWorkspace: (workspaceId: string) => void;
  onSelectFolder: (folderId: string | null) => void;
  onToggleFolder: (folderId: string) => void;
  onFolderAction: (action: FolderAction, folder: DocumentFolder) => void;
  onNewRootFolder: (workspaceId: string) => void;
}) {
  const t = useTranslations("admin");

  return (
    <nav aria-label={t("kbWorkspaces")} className="space-y-1">
      <div className="px-1 pb-1">
        <span className="text-xs font-semibold uppercase tracking-wide text-ink-muted">
          {t("kbWorkspaces")}
        </span>
      </div>

      {workspaces.map((ws) => (
        <WorkspaceRow
          key={ws.id}
          workspace={ws}
          folders={foldersByWs.get(ws.id)}
          isActiveWorkspace={ws.id === selectedWorkspaceId}
          isOpen={expandedWorkspaces.has(ws.id)}
          currentFolderId={currentFolderId}
          expandedFolders={expandedFolders}
          onSelectWorkspace={onSelectWorkspace}
          onToggleWorkspace={onToggleWorkspace}
          onSelectFolder={onSelectFolder}
          onToggleFolder={onToggleFolder}
          onFolderAction={onFolderAction}
          onNewRootFolder={onNewRootFolder}
        />
      ))}
    </nav>
  );
}

function WorkspaceRow({
  workspace,
  folders,
  isActiveWorkspace,
  isOpen,
  currentFolderId,
  expandedFolders,
  onSelectWorkspace,
  onToggleWorkspace,
  onSelectFolder,
  onToggleFolder,
  onFolderAction,
  onNewRootFolder,
}: {
  workspace: WorkspaceSummary;
  // undefined = not fetched yet; [] = fetched and empty.
  folders: DocumentFolder[] | undefined;
  isActiveWorkspace: boolean;
  isOpen: boolean;
  currentFolderId: string | null;
  expandedFolders: Set<string>;
  onSelectWorkspace: (workspaceId: string) => void;
  onToggleWorkspace: (workspaceId: string) => void;
  onSelectFolder: (folderId: string | null) => void;
  onToggleFolder: (folderId: string) => void;
  onFolderAction: (action: FolderAction, folder: DocumentFolder) => void;
  onNewRootFolder: (workspaceId: string) => void;
}) {
  const t = useTranslations("admin");
  const tree = useMemo(() => buildTree(folders ?? []), [folders]);
  // The workspace root is "current" when this workspace is active and no folder
  // is selected.
  const rootCurrent = isActiveWorkspace && currentFolderId === null;

  return (
    <div>
      <div
        className={`group flex items-center gap-1 rounded-full pr-1 transition ${
          isActiveWorkspace ? "bg-brand/10" : "hover:bg-surface-2"
        }`}
      >
        {/* Expand/collapse caret — toggling also lazy-loads this workspace. */}
        <button
          type="button"
          onClick={() => onToggleWorkspace(workspace.id)}
          aria-label={isOpen ? t("kbCollapse") : t("kbExpand")}
          aria-expanded={isOpen}
          className="grid h-9 w-6 shrink-0 place-items-center rounded-lg text-ink-muted transition hover:text-ink"
        >
          <Icon name={isOpen ? "expand_more" : "chevron_right"} size={18} />
        </button>

        <button
          type="button"
          onClick={() => onSelectWorkspace(workspace.id)}
          aria-current={rootCurrent ? "true" : undefined}
          className={`flex min-w-0 flex-1 items-center gap-2.5 py-2 text-left text-sm transition ${
            isActiveWorkspace ? "font-semibold text-brand" : "text-ink"
          }`}
        >
          <Icon
            name="workspaces"
            size={18}
            fill={isActiveWorkspace}
            className={`shrink-0 ${isActiveWorkspace ? "text-brand" : "text-ink-muted"}`}
          />
          <span className="truncate">{workspace.name}</span>
        </button>

        {/* New root folder in this workspace. */}
        <button
          type="button"
          onClick={() => onNewRootFolder(workspace.id)}
          aria-label={t("kbNewFolder")}
          title={t("kbNewFolder")}
          className="grid h-7 w-7 shrink-0 place-items-center rounded-full text-ink-muted opacity-0 transition hover:bg-surface-3 hover:text-ink focus-visible:opacity-100 group-hover:opacity-100"
        >
          <Icon name="create_new_folder" size={18} />
        </button>
      </div>

      {isOpen ? (
        <div className="mt-0.5 space-y-0.5 pl-3">
          {folders === undefined ? (
            <p className="px-3 py-1.5 text-xs text-ink-muted">{t("kbLoading")}</p>
          ) : tree.length === 0 ? (
            <p className="px-3 py-1.5 text-xs text-ink-muted">{t("kbNoFolders")}</p>
          ) : (
            tree.map((node) => (
              <TreeRow
                key={node.id}
                node={node}
                depth={0}
                currentFolderId={isActiveWorkspace ? currentFolderId : null}
                expanded={expandedFolders}
                onSelect={onSelectFolder}
                onToggle={onToggleFolder}
                onFolderAction={onFolderAction}
              />
            ))
          )}
        </div>
      ) : null}
    </div>
  );
}

function TreeRow({
  node,
  depth,
  currentFolderId,
  expanded,
  onSelect,
  onToggle,
  onFolderAction,
}: {
  node: TreeNode;
  depth: number;
  currentFolderId: string | null;
  expanded: Set<string>;
  onSelect: (folderId: string) => void;
  onToggle: (folderId: string) => void;
  onFolderAction: (action: FolderAction, folder: DocumentFolder) => void;
}) {
  const t = useTranslations("admin");
  const isOpen = expanded.has(node.id);
  const isCurrent = currentFolderId === node.id;
  const hasChildren = node.children.length > 0;

  const menuItems: DropdownItem[] = [
    { key: "rename", label: t("kbRename"), icon: "edit", onSelect: () => onFolderAction("rename", node) },
    { key: "newSub", label: t("kbNewSubfolder"), icon: "create_new_folder", onSelect: () => onFolderAction("newSub", node) },
    { key: "move", label: t("kbMove"), icon: "drive_file_move", onSelect: () => onFolderAction("move", node) },
    { key: "delete", label: t("kbDelete"), icon: "delete", danger: true, onSelect: () => onFolderAction("delete", node) },
  ];

  return (
    <div>
      <div
        className={`group flex items-center gap-1 rounded-full pr-1 transition ${
          isCurrent ? "bg-brand/10" : "hover:bg-surface-2"
        }`}
        style={{ paddingLeft: `${depth * 14}px` }}
      >
        {/* Expand/collapse caret — a spacer when the folder has no children. */}
        {hasChildren ? (
          <button
            type="button"
            onClick={() => onToggle(node.id)}
            aria-label={isOpen ? t("kbCollapse") : t("kbExpand")}
            aria-expanded={isOpen}
            className="grid h-8 w-6 shrink-0 place-items-center rounded-lg text-ink-muted transition hover:text-ink"
          >
            <Icon name={isOpen ? "expand_more" : "chevron_right"} size={18} />
          </button>
        ) : (
          <span className="h-8 w-6 shrink-0" />
        )}

        <button
          type="button"
          onClick={() => onSelect(node.id)}
          aria-current={isCurrent ? "true" : undefined}
          className={`flex min-w-0 flex-1 items-center gap-2.5 py-2 text-left text-sm transition ${
            isCurrent ? "font-semibold text-brand" : "text-ink"
          }`}
        >
          <Icon
            name={isOpen && hasChildren ? "folder_open" : "folder"}
            size={18}
            fill={isCurrent}
            className={`shrink-0 ${isCurrent ? "text-brand" : "text-ink-muted"}`}
          />
          <span className="truncate">{node.name}</span>
        </button>

        <DropdownMenu
          items={menuItems}
          ariaLabel={t("kbFolderActions")}
          renderTrigger={(props) => (
            <button
              {...props}
              type="button"
              className="grid h-7 w-7 shrink-0 place-items-center rounded-full text-ink-muted opacity-0 transition hover:bg-surface-3 hover:text-ink focus-visible:opacity-100 group-hover:opacity-100 aria-expanded:opacity-100"
            >
              <Icon name="more_vert" size={18} />
            </button>
          )}
        />
      </div>

      {isOpen && hasChildren ? (
        <div className="mt-0.5 space-y-0.5">
          {node.children.map((child) => (
            <TreeRow
              key={child.id}
              node={child}
              depth={depth + 1}
              currentFolderId={currentFolderId}
              expanded={expanded}
              onSelect={onSelect}
              onToggle={onToggle}
              onFolderAction={onFolderAction}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}
