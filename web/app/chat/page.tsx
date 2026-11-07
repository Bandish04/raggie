// SPDX-License-Identifier: Apache-2.0

import { redirect } from "next/navigation";

import ChatClient from "@/components/chat/chat-client";
import {
  getAvailableIntegrations,
  getModelsConfig,
  getProfile,
  listMyMemory,
  listMyWorkspaces,
  listNotifications,
  listScheduledTasks,
  listSkills,
  me,
} from "@/lib/api";
import { getAccessToken } from "@/lib/session";

function hasVisionModel(): boolean {
  if ((process.env.VISION_MODELS ?? "").trim().length > 0) return true;
  const registry = process.env.LLM_MODEL_PROFILES_JSON?.trim();
  if (!registry) return false;
  try {
    const profiles = JSON.parse(registry) as unknown;
    return (
      Array.isArray(profiles) &&
      profiles.some((profile) => {
        if (!profile || typeof profile !== "object") return false;
        const capabilities = (profile as Record<string, unknown>).capabilities;
        return Array.isArray(capabilities) && capabilities.includes("vision");
      })
    );
  } catch {
    // Edge rejects malformed registry JSON at boot; keep the web UI conservative.
    return false;
  }
}

export default async function ChatPage() {
  const token = await getAccessToken();
  if (!token) redirect("/login");
  // Fetch workspaces, the signed-in user (role + chat prefs), the allowed chat
  // models, the org's enabled skills (the /command picker), the data the in-chat
  // settings modal needs (full profile + the assistant's remembered facts), the
  // user's scheduled tasks, their notifications inbox, and the org's connected
  // MCP integrations (the sidebar "Araçlar" menu) — all server-side via lib/api,
  // in parallel.
  const [workspaces, user, models, skills, profile, memory, tasks, notifications, tools] =
    await Promise.all([
      listMyWorkspaces(token),
      me(token),
      getModelsConfig(token),
      listSkills(token),
      getProfile(token),
      listMyMemory(token),
      listScheduledTasks(token),
      listNotifications(token),
      getAvailableIntegrations(token),
    ]);
  // Default off: show attachment controls only when legacy config or the
  // provider-aware registry declares at least one vision-capable model.
  const visionEnabled = hasVisionModel();
  return (
    <ChatClient
      workspaces={workspaces}
      visionEnabled={visionEnabled}
      userRole={user?.role}
      userName={user?.full_name ?? null}
      userEmail={user?.email ?? ""}
      answerStyle={user?.answer_style}
      models={models}
      preferredModel={user?.preferred_chat_model ?? null}
      skills={skills}
      profile={profile}
      memory={memory}
      tasks={tasks}
      notifications={notifications}
      tools={tools}
      timezone={user?.timezone ?? null}
    />
  );
}
