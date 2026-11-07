// SPDX-License-Identifier: Apache-2.0

import { redirect } from "next/navigation";

// Teams moved into the consolidated Organization page (#13). Keep this route as
// a permanent redirect so old links/bookmarks and in-app hrefs still resolve.
// Note: the team detail route /admin/teams/[id] is unaffected.
export default function TeamsPage() {
  redirect("/admin/organization?tab=teams");
}
