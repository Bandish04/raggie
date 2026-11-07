// SPDX-License-Identifier: Apache-2.0

import { redirect } from "next/navigation";

import OnboardingFlow from "@/components/onboarding/flow";
import { onboardingState } from "@/lib/api";

export default async function OnboardingPage() {
  const state = await onboardingState();
  if (state.onboarded) redirect("/dashboard");
  return (
    <OnboardingFlow
      needsBootstrap={!state.has_super_admin}
      // true → required field; false → hidden; unknown (older control plane)
      // → shown but optional.
      setupTokenRequired={state.setup_token_required}
    />
  );
}
