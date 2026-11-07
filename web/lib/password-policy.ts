// SPDX-License-Identifier: Apache-2.0

// Client/server mirror of the control-plane password policy (bootstrap, invite
// accept, change-password, admin create-user). The control plane stays the
// authority and answers 422 with a reason; this only gives early feedback.

export const PASSWORD_MIN_LENGTH = 12;
export const PASSWORD_MAX_LENGTH = 1024;

export type PasswordPolicyError = "short" | "long" | "blank";

export function passwordPolicyError(password: string): PasswordPolicyError | null {
  if (!password.trim()) return "blank";
  // Count characters (code points) like the control plane, not UTF-16 units.
  const length = [...password].length;
  if (length < PASSWORD_MIN_LENGTH) return "short";
  if (length > PASSWORD_MAX_LENGTH) return "long";
  return null;
}

const PASSWORD_FIELDS = new Set(["password", "new_password"]);

/** True when a control-plane response is a policy rejection of the password:
 *  a 422 whose FastAPI validation detail points at a password field. Other 422s
 *  (e.g. a malformed email) are not reported as password problems. */
export function isPasswordPolicyRejection(status: number, body: unknown): boolean {
  if (status !== 422) return false;
  const detail = (body as { detail?: unknown } | undefined)?.detail;
  if (!Array.isArray(detail)) return false;
  return detail.some((d: { loc?: unknown }) => {
    const loc = Array.isArray(d?.loc) ? d.loc : [];
    return PASSWORD_FIELDS.has(String(loc[loc.length - 1]));
  });
}
