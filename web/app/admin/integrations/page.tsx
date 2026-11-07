// SPDX-License-Identifier: Apache-2.0

import { redirect } from "next/navigation";

// Integrations were merged into the Marketplace. Keep this route as a permanent
// redirect so old links (and the connect deep-links) still land somewhere sane.
export default function IntegrationsPage() {
  redirect("/admin/marketplace");
}
