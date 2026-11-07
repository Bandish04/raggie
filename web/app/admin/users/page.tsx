// SPDX-License-Identifier: Apache-2.0

import { redirect } from "next/navigation";

// People moved into the consolidated Organization page (#13). Keep this route as
// a permanent redirect so old links/bookmarks and in-app hrefs still resolve.
export default function AdminUsersPage() {
  redirect("/admin/organization?tab=people");
}
