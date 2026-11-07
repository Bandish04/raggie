// SPDX-License-Identifier: Apache-2.0

import { redirect } from "next/navigation";

// Directory moved into the consolidated Organization page (#13). Keep this route
// as a permanent redirect so old links/bookmarks and in-app hrefs still resolve.
export default function DirectoryPage() {
  redirect("/admin/organization?tab=directory");
}
