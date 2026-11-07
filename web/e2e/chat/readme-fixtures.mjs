// SPDX-License-Identifier: Apache-2.0

// Data for the README visuals (capture-readme.spec.ts), taken from the synthetic
// "Nebula Teknoloji" demo: file names from examples/sample-corpus, questions,
// answers and quotes from examples/golden/golden.yaml (arge-005, arge-001,
// md-002), people from the demo seed (raggie_control_plane/demo.py). Nothing
// here is a real person, customer or mailbox.

export const DEMO_USER = {
  id: "demo",
  email: "ayse.demir@nebulacrm.example",
  role: "SUPER_ADMIN",
  org_id: "org1",
  full_name: "Ayşe Demir",
  job_title: "Ar-Ge Müdürü",
  locale: "en",
  timezone: "Europe/Istanbul",
  answer_style: "balanced",
  preferred_chat_model: null,
  is_platform_admin: true,
  is_active: true,
};

export const DEMO_WORKSPACES = [
  { id: "ws-company", name: "Tüm Şirket", type: "INTERNAL" },
  { id: "ws-support", name: "Nebula Destek", type: "EXTERNAL" },
];

const LOAD_TEST = {
  type: "doc",
  document_id: "doc-load-test",
  filename: "Load_Test_Report_2026_Q2.docx",
  title: "Load_Test_Report_2026_Q2.docx",
  score: 0.89,
  text:
    "At 3,000 RPS sustained for 60 minutes the API recorded a p95 latency of 212 ms. " +
    "The test environment mirrored production topology: 34 services on Kubernetes.",
};
const ARCHITECTURE = {
  type: "doc",
  document_id: "doc-architecture",
  filename: "Teknik_Mimari_NebulaCRM_2026.pdf",
  title: "Teknik_Mimari_NebulaCRM_2026.pdf",
  score: 0.74,
  text: "NebulaCRM, Kubernetes 1.30 üzerinde koşan 34 mikroservisten oluşur.",
};
const SLA_MATRIX = {
  type: "doc",
  document_id: "doc-sla",
  filename: "Destek_SLA_Matrisi_2026.xlsx",
  title: "Destek_SLA_Matrisi_2026.xlsx",
  score: 0.92,
  text: "Kurumsal Plus | 15 dakika | 2 saat | 8 iş saati | 2 iş günü",
};

export const README_QUESTIONS = {
  en: "In the Q2 2026 load test, what p95 latency did the API reach at 3,000 RPS?",
  tr: "NebulaCRM platformu şu an kaç mikroservisten oluşuyor?",
  widget: "What is the first-response target for a P1 ticket on the Kurumsal Plus plan?",
};

// Answer text streamed in word-sized deltas so the hero clip reads as a stream.
const words = (text) => text.match(/\S+\s*/g) ?? [];
const answer = (meta, thinking, sources, text, delay = 45) => [
  ["meta", meta],
  ["thinking", { delta: thinking }, 120],
  ["sources", { sources }, 250],
  ...words(text).map((w) => [null, { delta: w }, delay]),
  ["done", { message_id: meta.message_id }],
];

export const README_SCENARIOS = {
  [README_QUESTIONS.en]: answer(
    { conversation_id: "conv-readme-en", message_id: "msg-readme-en" },
    "The load test report has the Q2 2026 latency table; the architecture document confirms the topology. ",
    [LOAD_TEST, ARCHITECTURE],
    "At a sustained **3,000 RPS**, the API recorded a **p95 latency of 212 ms** [1].\n\n" +
      "The test environment mirrored the production topology — 34 services on Kubernetes [1] — " +
      "which matches the architecture document [2].",
  ),
  [README_QUESTIONS.tr]: answer(
    { conversation_id: "conv-readme-tr", message_id: "msg-readme-tr" },
    "Teknik mimari belgesi servis sayısını veriyor; yük testi raporu aynı topolojiyi doğruluyor. ",
    // Scores are per question: here the architecture document is the best match.
    [
      { ...ARCHITECTURE, score: 0.91 },
      { ...LOAD_TEST, score: 0.71 },
    ],
    "NebulaCRM, Kubernetes 1.30 üzerinde çalışan **34 mikroservisten** oluşuyor [1].\n\n" +
      "Q2 2026 yük testi de üretimle aynı topolojide, 34 servisle yapıldı [2].",
  ),
  [README_QUESTIONS.widget]: answer(
    { conversation_id: "conv-readme-widget", message_id: "msg-readme-widget" },
    "",
    [SLA_MATRIX],
    // The widget renders safe minimal markdown, [n] chips and a sources list.
    "On the **Kurumsal Plus** plan, a P1 ticket has these targets [1]:\n\n" +
      "- **First response:** 15 minutes\n" +
      "- **Resolution:** 2 hours",
    30,
  ).filter(([event]) => event !== "thinking"),
};

const FOLDERS = [
  ["arge", "Ar-Ge"],
  ["bilgi-teknolojileri", "Bilgi Teknolojileri"],
  ["finans", "Finans"],
  ["hukuk-uyum", "Hukuk ve Uyum"],
  ["insan-kaynaklari", "İnsan Kaynakları"],
  ["musteri-deneyimi", "Müşteri Deneyimi"],
];

export const DEMO_FOLDERS = FOLDERS.map(([id, name]) => ({
  id: `folder-${id}`,
  workspace_id: "ws-company",
  parent_folder_id: null,
  name,
  created_at: "2026-10-01T09:00:00Z",
}));

const doc = (id, filename, file_size, status, extra = {}) => ({
  id,
  workspace_id: "ws-company",
  filename,
  file_size,
  status,
  error_code: null,
  error_params: null,
  error_message: null,
  created_at: "2026-10-14T09:30:00Z",
  retry_count: 0,
  folder_id: null,
  ...extra,
});

export const DEMO_DOCUMENTS = [
  doc("doc-load-test", "Load_Test_Report_2026_Q2.docx", 48_211, "SUCCESS"),
  doc("doc-architecture", "Teknik_Mimari_NebulaCRM_2026.pdf", 312_904, "SUCCESS"),
  doc("doc-leave", "Izin_Yonetmeligi_2026.pdf", 156_388, "SUCCESS"),
  doc("doc-sla", "Destek_SLA_Matrisi_2026.xlsx", 22_540, "SUCCESS"),
  doc("doc-release", "Release_Notes_NebulaCRM_v3.4.md", 9_870, "PROCESSING"),
  doc("doc-strategy", "Stratejik_Plan_2026_2028.pptx", 4_812_330, "FAILED", {
    error_code: "parse_timeout",
    error_params: { seconds: 120 },
    error_message: "Document parsing exceeded 120 seconds.",
    retry_count: 3,
  }),
];

// The embeddings card in local mode (the default): nothing leaves the server.
export const DEMO_EMBEDDINGS = {
  status: "ok",
  policy: "block_ingest",
  ingest_blocked: false,
  detail: null,
  profile: {
    provider: "local",
    model: "intfloat/multilingual-e5-large",
    dim: 1024,
    fingerprint: "2872ae6a",
    collection: "raggie_chunks_d1024",
    sparse_model: "Qdrant/bm25",
    reranker: { provider: "local", model: "Alibaba-NLP/gte-multilingual-reranker-base" },
    egress: { dense_host: null, rerank_host: null },
  },
  stored_fingerprint: "2872ae6a",
  mismatch: false,
  checked_at: "2026-11-04T09:00:00Z",
  gateway_error: null,
  documents: [{ fingerprint: "2872ae6a", count: 39 }],
  reembed: {
    target_fingerprint: "2872ae6a",
    total: 39,
    completed: 39,
    pending: 0,
    processing: 0,
    failed: 0,
    stale: 0,
    in_progress: false,
    last_started_at: null,
  },
};

export const DEMO_AI_CONFIG = {
  default_model: "qwen3:4b-instruct",
  allowed_models: ["qwen3:4b-instruct", "qwen3:8b"],
};

// A plain "customer website" that embeds the widget from the stub (the edge).
export function demoHostPage(origin) {
  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Nebula Teknoloji — Support</title>
    <style>
      body { margin: 0; font-family: system-ui, -apple-system, "Segoe UI", sans-serif; color: #1a1f2b; background: #f7f8fb; }
      header { background: #fff; border-bottom: 1px solid #e5e7ef; padding: 18px 48px; font-weight: 700; font-size: 18px; }
      main { max-width: 760px; padding: 48px; }
      h1 { font-size: 30px; margin: 0 0 12px; }
      p { line-height: 1.6; color: #4b5266; }
      .card { background: #fff; border: 1px solid #e5e7ef; border-radius: 16px; padding: 20px 24px; margin-top: 24px; }
    </style>
  </head>
  <body>
    <header>Nebula Teknoloji</header>
    <main>
      <h1>Help center</h1>
      <p>Plans, support hours and response targets for NebulaCRM customers.</p>
      <div class="card"><strong>Kurumsal Plus</strong><p>Priority support with a dedicated success manager.</p></div>
      <div class="card"><strong>Need an answer now?</strong><p>Ask the assistant in the corner — it answers from our published support documents.</p></div>
    </main>
    <script src="${origin}/widgets/embed.js?id=ws-support"></script>
  </body>
</html>`;
}
