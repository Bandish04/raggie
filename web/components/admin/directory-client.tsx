// SPDX-License-Identifier: Apache-2.0

"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useActionState, useEffect, useState, useTransition } from "react";

import {
  createDepartmentAction,
  createLocationAction,
  deleteDepartmentAction,
  deleteLocationAction,
  type DirectoryActionState,
  updateDepartmentAction,
  updateLocationAction,
} from "@/app/admin/directory/actions";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { Column, DataTable } from "@/components/ui/data-table";
import { EmptyState } from "@/components/ui/empty-state";
import { Icon } from "@/components/ui/icon";
import { Modal } from "@/components/ui/modal";
import Select from "@/components/ui/select";
import type { Department, Location, OrgUser } from "@/lib/api";
import { ui } from "@/lib/ui";

function userLabel(u: OrgUser): string {
  return u.full_name || u.email;
}

// ───────────────────────── Department modal ─────────────────────────
function DepartmentModal({
  open,
  onClose,
  editing,
  users,
  departments,
}: {
  open: boolean;
  onClose: () => void;
  editing: Department | null;
  users: OrgUser[];
  departments: Department[];
}) {
  const t = useTranslations("admin");
  const tc = useTranslations("common");
  const router = useRouter();
  const action = editing ? updateDepartmentAction : createDepartmentAction;
  const [state, formAction, pending] = useActionState<DirectoryActionState, FormData>(action, {});

  // Close + refresh once the server action reports success.
  useEffect(() => {
    if (state.ok) {
      onClose();
      router.refresh();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.ok]);

  const ownerOptions = [
    { value: "", label: t("dirOwnerNone"), icon: "block" },
    ...users.map((u) => ({ value: u.id, label: userLabel(u), icon: "person" })),
  ];
  // A department cannot be its own parent.
  const parentOptions = [
    { value: "", label: t("dirParentNone"), icon: "block" },
    ...departments
      .filter((d) => d.id !== editing?.id)
      .map((d) => ({ value: d.id, label: d.name, icon: "apartment" })),
  ];

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={editing ? t("dirEditDepartment") : t("dirNewDepartment")}
    >
      <form action={formAction} className="space-y-4">
        {editing && <input type="hidden" name="dept_id" value={editing.id} />}
        <div className="space-y-1.5">
          <label htmlFor="dir-dept-name" className={ui.label}>
            {t("dirName")}
          </label>
          <input
            id="dir-dept-name"
            name="name"
            required
            defaultValue={editing?.name ?? ""}
            className={ui.input}
            placeholder={t("dirDepartmentPlaceholder")}
          />
        </div>
        <div className="space-y-1.5">
          <label className={ui.label}>{t("dirOwner")}</label>
          <Select
            name="owner_user_id"
            ariaLabel={t("dirOwner")}
            defaultValue={editing?.owner_user_id ?? ""}
            options={ownerOptions}
          />
        </div>
        <div className="space-y-1.5">
          <label className={ui.label}>{t("dirParentDepartment")}</label>
          <Select
            name="parent_department_id"
            ariaLabel={t("dirParentDepartment")}
            defaultValue={editing?.parent_department_id ?? ""}
            options={parentOptions}
          />
        </div>
        {state.duplicate && (
          <p className="rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger" role="alert">
            {t("dirDuplicateName")}
          </p>
        )}
        {state.error && (
          <p className="rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger" role="alert">
            {t("saveError")}
          </p>
        )}
        <div className="flex items-center justify-end gap-3 pt-1">
          <Button type="button" variant="ghost" onClick={onClose}>
            {tc("cancel")}
          </Button>
          <Button type="submit" disabled={pending}>
            {pending ? tc("loading") : tc("save")}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

// ───────────────────────── Location modal ─────────────────────────
function LocationModal({
  open,
  onClose,
  editing,
}: {
  open: boolean;
  onClose: () => void;
  editing: Location | null;
}) {
  const t = useTranslations("admin");
  const tc = useTranslations("common");
  const router = useRouter();
  const action = editing ? updateLocationAction : createLocationAction;
  const [state, formAction, pending] = useActionState<DirectoryActionState, FormData>(action, {});

  useEffect(() => {
    if (state.ok) {
      onClose();
      router.refresh();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.ok]);

  return (
    <Modal open={open} onClose={onClose} title={editing ? t("dirEditLocation") : t("dirNewLocation")}>
      <form action={formAction} className="space-y-4">
        {editing && <input type="hidden" name="loc_id" value={editing.id} />}
        <div className="space-y-1.5">
          <label htmlFor="dir-loc-name" className={ui.label}>
            {t("dirName")}
          </label>
          <input
            id="dir-loc-name"
            name="name"
            required
            defaultValue={editing?.name ?? ""}
            className={ui.input}
            placeholder={t("dirLocationPlaceholder")}
          />
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <label htmlFor="dir-loc-city" className={ui.label}>
              {t("dirCity")}
            </label>
            <input
              id="dir-loc-city"
              name="city"
              defaultValue={editing?.city ?? ""}
              className={ui.input}
            />
          </div>
          <div className="space-y-1.5">
            <label htmlFor="dir-loc-country" className={ui.label}>
              {t("dirCountry")}
            </label>
            <input
              id="dir-loc-country"
              name="country"
              defaultValue={editing?.country ?? ""}
              className={ui.input}
            />
          </div>
        </div>
        {state.duplicate && (
          <p className="rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger" role="alert">
            {t("dirDuplicateName")}
          </p>
        )}
        {state.error && (
          <p className="rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger" role="alert">
            {t("saveError")}
          </p>
        )}
        <div className="flex items-center justify-end gap-3 pt-1">
          <Button type="button" variant="ghost" onClick={onClose}>
            {tc("cancel")}
          </Button>
          <Button type="submit" disabled={pending}>
            {pending ? tc("loading") : tc("save")}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function IconButton({
  icon,
  label,
  danger = false,
  disabled = false,
  onClick,
}: {
  icon: string;
  label: string;
  danger?: boolean;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className={`grid h-8 w-8 place-items-center rounded-lg text-ink-muted hover:bg-surface-2 ${
        danger ? "hover:text-danger" : "hover:text-ink"
      } disabled:opacity-40`}
    >
      <Icon name={icon} size={18} />
    </button>
  );
}

export default function DirectoryClient({
  departments,
  locations,
  users,
}: {
  departments: Department[];
  locations: Location[];
  users: OrgUser[];
}) {
  const t = useTranslations("admin");
  const router = useRouter();
  const [pending, start] = useTransition();

  const [deptModal, setDeptModal] = useState<{ open: boolean; editing: Department | null }>({
    open: false,
    editing: null,
  });
  const [locModal, setLocModal] = useState<{ open: boolean; editing: Location | null }>({
    open: false,
    editing: null,
  });

  const userName = new Map(users.map((u) => [u.id, userLabel(u)]));
  const deptName = new Map(departments.map((d) => [d.id, d.name]));

  function removeDept(d: Department) {
    if (!window.confirm(t("dirConfirmDeleteDepartment", { name: d.name }))) return;
    start(async () => {
      await deleteDepartmentAction(d.id);
      router.refresh();
    });
  }
  function removeLoc(l: Location) {
    if (!window.confirm(t("dirConfirmDeleteLocation", { name: l.name }))) return;
    start(async () => {
      await deleteLocationAction(l.id);
      router.refresh();
    });
  }

  const deptColumns: Column<Department>[] = [
    {
      key: "name",
      header: t("dirName"),
      cell: (d) => <span className="font-medium text-ink">{d.name}</span>,
    },
    {
      key: "owner",
      header: t("dirOwner"),
      cell: (d) =>
        d.owner_user_id ? (
          <span className="text-ink-muted">{userName.get(d.owner_user_id) ?? "—"}</span>
        ) : (
          <span className="text-ink-muted">—</span>
        ),
    },
    {
      key: "parent",
      header: t("dirParentDepartment"),
      cell: (d) =>
        d.parent_department_id ? (
          <Badge tone="neutral">{deptName.get(d.parent_department_id) ?? "—"}</Badge>
        ) : (
          <span className="text-ink-muted">—</span>
        ),
    },
    {
      key: "actions",
      header: "",
      align: "right",
      cell: (d) => (
        <div className="flex items-center justify-end gap-1">
          <IconButton
            icon="edit"
            label={t("dirEditDepartment")}
            onClick={() => setDeptModal({ open: true, editing: d })}
          />
          <IconButton
            icon="delete"
            label={t("dirDeleteDepartment")}
            danger
            disabled={pending}
            onClick={() => removeDept(d)}
          />
        </div>
      ),
    },
  ];

  const locColumns: Column<Location>[] = [
    {
      key: "name",
      header: t("dirName"),
      cell: (l) => <span className="font-medium text-ink">{l.name}</span>,
    },
    {
      key: "city",
      header: t("dirCity"),
      cell: (l) => <span className="text-ink-muted">{l.city || "—"}</span>,
    },
    {
      key: "country",
      header: t("dirCountry"),
      cell: (l) => <span className="text-ink-muted">{l.country || "—"}</span>,
    },
    {
      key: "actions",
      header: "",
      align: "right",
      cell: (l) => (
        <div className="flex items-center justify-end gap-1">
          <IconButton
            icon="edit"
            label={t("dirEditLocation")}
            onClick={() => setLocModal({ open: true, editing: l })}
          />
          <IconButton
            icon="delete"
            label={t("dirDeleteLocation")}
            danger
            disabled={pending}
            onClick={() => removeLoc(l)}
          />
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-8">
      {/* Departments */}
      <Card>
        <CardHeader>
          <div>
            <CardTitle>{t("dirDepartments")}</CardTitle>
            <p className="mt-1 text-sm text-ink-muted">{t("dirDepartmentsHint")}</p>
          </div>
          <Button size="sm" onClick={() => setDeptModal({ open: true, editing: null })}>
            <Icon name="add" size={18} />
            {t("dirNewDepartment")}
          </Button>
        </CardHeader>
        <CardBody>
          <DataTable
            columns={deptColumns}
            rows={departments}
            rowKey={(d) => d.id}
            empty={
              <EmptyState
                icon="apartment"
                title={t("dirNoDepartments")}
                description={t("dirNoDepartmentsHint")}
                action={
                  <Button size="sm" onClick={() => setDeptModal({ open: true, editing: null })}>
                    <Icon name="add" size={18} />
                    {t("dirNewDepartment")}
                  </Button>
                }
              />
            }
          />
        </CardBody>
      </Card>

      {/* Locations */}
      <Card>
        <CardHeader>
          <div>
            <CardTitle>{t("dirLocations")}</CardTitle>
            <p className="mt-1 text-sm text-ink-muted">{t("dirLocationsHint")}</p>
          </div>
          <Button size="sm" onClick={() => setLocModal({ open: true, editing: null })}>
            <Icon name="add" size={18} />
            {t("dirNewLocation")}
          </Button>
        </CardHeader>
        <CardBody>
          <DataTable
            columns={locColumns}
            rows={locations}
            rowKey={(l) => l.id}
            empty={
              <EmptyState
                icon="location_on"
                title={t("dirNoLocations")}
                description={t("dirNoLocationsHint")}
                action={
                  <Button size="sm" onClick={() => setLocModal({ open: true, editing: null })}>
                    <Icon name="add" size={18} />
                    {t("dirNewLocation")}
                  </Button>
                }
              />
            }
          />
        </CardBody>
      </Card>

      {/* Modals — keyed so each open resets the form's internal action state. */}
      {deptModal.open && (
        <DepartmentModal
          key={deptModal.editing?.id ?? "new-dept"}
          open={deptModal.open}
          onClose={() => setDeptModal({ open: false, editing: null })}
          editing={deptModal.editing}
          users={users}
          departments={departments}
        />
      )}
      {locModal.open && (
        <LocationModal
          key={locModal.editing?.id ?? "new-loc"}
          open={locModal.open}
          onClose={() => setLocModal({ open: false, editing: null })}
          editing={locModal.editing}
        />
      )}
    </div>
  );
}
