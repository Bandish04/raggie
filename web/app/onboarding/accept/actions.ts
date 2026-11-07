// SPDX-License-Identifier: Apache-2.0

"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { acceptInvite } from "@/lib/api";
import { isPasswordPolicyRejection, passwordPolicyError } from "@/lib/password-policy";
import { setSession } from "@/lib/session";

export type AcceptState = {
  error?: "mismatch" | "short" | "policy" | "generic";
};

export async function acceptInviteAction(
  _prev: AcceptState,
  formData: FormData,
): Promise<AcceptState> {
  const token = String(formData.get("token") ?? "");
  const password = String(formData.get("password") ?? "");
  const confirm = String(formData.get("confirm_password") ?? "");
  const policy = passwordPolicyError(password);
  if (policy) return { error: policy === "long" ? "policy" : "short" };
  if (password !== confirm) return { error: "mismatch" };

  const str = (k: string) => String(formData.get(k) ?? "").trim();
  const val = (k: string) => str(k) || undefined;
  const res = await acceptInvite({
    token,
    password,
    full_name: val("full_name"),
    job_title: val("job_title"),
    department: val("department"),
    phone: val("phone"),
    location: val("location"),
    locale: val("locale"),
  });
  if (isPasswordPolicyRejection(res.status, res.data)) return { error: "policy" };
  if (!res.ok || !res.data) return { error: "generic" };

  await setSession(res.data);
  const locale = val("locale");
  if (locale === "tr" || locale === "en") {
    (await cookies()).set("NEXT_LOCALE", locale, {
      path: "/",
      sameSite: "lax",
      maxAge: 60 * 60 * 24 * 365,
    });
  }
  redirect("/dashboard");
}
