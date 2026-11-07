// SPDX-License-Identifier: Apache-2.0

// Dependency-free resumable chunked (multipart) uploader for the browser.
//
// Talks to the same-origin Next.js route handlers under
// `/api/admin/workspaces/{workspaceId}/documents/uploads/*`, which add the
// Bearer token server-side and proxy to the control-plane.
//
// Flow: create session -> upload parts (bounded concurrency + per-part retry)
// -> complete. On abort or fatal error the session is aborted.

import { classifyUploadFailure, type UploadFailureCode } from "./upload-errors.ts";

export type UploadProgress = (sentBytes: number, totalBytes: number) => void;

export type UploadOptions = {
  onProgress?: UploadProgress;
  signal?: AbortSignal;
  // Optional Drive folder the finished document should land in (null = root).
  folderId?: string | null;
};

export type UploadResult =
  | { ok: true }
  | {
      ok: false;
      error: string;
      aborted?: boolean;
      // Set when the embedding profile refused the upload (see upload-errors).
      code?: UploadFailureCode;
      retryAfterSeconds?: number | null;
    };

type CreateSessionResponse = {
  upload_id: string;
  object_key: string;
  part_size: number;
  max_bytes: number;
};

type UploadedPart = {
  part_number: number;
  etag: string;
};

const MAX_PART_RETRIES = 3;
const PART_CONCURRENCY = 3;

class AbortedError extends Error {
  constructor() {
    super("aborted");
    this.name = "AbortedError";
  }
}

// A refused create/complete call, kept with its status and Retry-After.
class UploadHttpError extends Error {
  readonly status: number;
  readonly retryAfter: string | null;
  constructor(message: string, status: number, retryAfter: string | null) {
    super(message);
    this.name = "UploadHttpError";
    this.status = status;
    this.retryAfter = retryAfter;
  }
}

async function httpError(res: Response): Promise<UploadHttpError> {
  return new UploadHttpError(await readError(res), res.status, res.headers.get("retry-after"));
}

function uploadsBase(workspaceId: string): string {
  return `/api/admin/workspaces/${encodeURIComponent(workspaceId)}/documents/uploads`;
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new AbortedError());
      return;
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(timer);
      reject(new AbortedError());
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

async function readError(res: Response): Promise<string> {
  try {
    const text = await res.text();
    if (!text) return `HTTP ${res.status}`;
    try {
      const json = JSON.parse(text) as { error?: string; detail?: string };
      return json.error ?? json.detail ?? `HTTP ${res.status}`;
    } catch {
      return text.slice(0, 200);
    }
  } catch {
    return `HTTP ${res.status}`;
  }
}

async function createSession(
  workspaceId: string,
  file: File,
  signal?: AbortSignal,
): Promise<CreateSessionResponse> {
  const res = await fetch(`${uploadsBase(workspaceId)}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      filename: file.name,
      content_type: file.type || "application/octet-stream",
      size: file.size,
    }),
    signal,
  });
  if (!res.ok) {
    throw await httpError(res);
  }
  const data = (await res.json()) as CreateSessionResponse;
  if (!data.upload_id || !data.object_key || !data.part_size) {
    throw new Error("invalid upload session response");
  }
  return data;
}

async function uploadPartWithRetry(
  workspaceId: string,
  session: CreateSessionResponse,
  partNumber: number,
  chunk: Blob,
  onChunkBytes: (delta: number) => void,
  signal?: AbortSignal,
): Promise<UploadedPart> {
  let lastError = "upload failed";
  for (let attempt = 0; attempt < MAX_PART_RETRIES; attempt += 1) {
    if (signal?.aborted) throw new AbortedError();
    try {
      const res = await fetch(`${uploadsBase(workspaceId)}/parts`, {
        method: "PUT",
        headers: {
          "content-type": "application/octet-stream",
          "X-Upload-Id": session.upload_id,
          "X-Object-Key": session.object_key,
          "X-Part-Number": String(partNumber),
        },
        body: chunk,
        signal,
      });
      if (!res.ok) {
        lastError = await readError(res);
        throw new Error(lastError);
      }
      const data = (await res.json()) as UploadedPart;
      if (!data.etag) {
        lastError = "part response missing etag";
        throw new Error(lastError);
      }
      onChunkBytes(chunk.size);
      return { part_number: partNumber, etag: data.etag };
    } catch (err) {
      if (err instanceof AbortedError || signal?.aborted) {
        throw new AbortedError();
      }
      // DOMException AbortError from fetch when the signal fires mid-request.
      if (err instanceof DOMException && err.name === "AbortError") {
        throw new AbortedError();
      }
      lastError = err instanceof Error ? err.message : String(err);
      const isLast = attempt === MAX_PART_RETRIES - 1;
      if (isLast) break;
      // Exponential backoff: 500ms, 1000ms, ...
      await sleep(500 * 2 ** attempt, signal);
    }
  }
  throw new Error(`part ${partNumber} failed: ${lastError}`);
}

type PartTask = { partNumber: number; chunk: Blob };

function buildPartTasks(file: File, partSize: number): PartTask[] {
  const tasks: PartTask[] = [];
  let partNumber = 1;
  for (let start = 0; start < file.size; start += partSize) {
    const end = Math.min(start + partSize, file.size);
    tasks.push({ partNumber, chunk: file.slice(start, end) });
    partNumber += 1;
  }
  // An empty file yields zero tasks; still emit a single empty part so the
  // backend has something to complete.
  if (tasks.length === 0) {
    tasks.push({ partNumber: 1, chunk: file.slice(0, 0) });
  }
  return tasks;
}

async function uploadAllParts(
  workspaceId: string,
  session: CreateSessionResponse,
  tasks: PartTask[],
  totalBytes: number,
  opts: UploadOptions,
): Promise<UploadedPart[]> {
  const results: UploadedPart[] = [];
  let sentBytes = 0;
  let nextIndex = 0;

  const onChunkBytes = (delta: number) => {
    sentBytes += delta;
    opts.onProgress?.(sentBytes, totalBytes);
  };

  // Bounded-concurrency worker pool pulling from a shared index.
  async function worker(): Promise<void> {
    for (;;) {
      if (opts.signal?.aborted) throw new AbortedError();
      const index = nextIndex;
      nextIndex += 1;
      if (index >= tasks.length) return;
      const task = tasks[index];
      const part = await uploadPartWithRetry(
        workspaceId,
        session,
        task.partNumber,
        task.chunk,
        onChunkBytes,
        opts.signal,
      );
      results.push(part);
    }
  }

  const workerCount = Math.min(PART_CONCURRENCY, tasks.length);
  await Promise.all(Array.from({ length: workerCount }, () => worker()));

  results.sort((a, b) => a.part_number - b.part_number);
  return results;
}

async function completeSession(
  workspaceId: string,
  session: CreateSessionResponse,
  filename: string,
  parts: UploadedPart[],
  folderId: string | null | undefined,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${uploadsBase(workspaceId)}/complete`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      upload_id: session.upload_id,
      object_key: session.object_key,
      filename,
      parts,
      // Optional: land the document directly in a folder (null = root).
      folder_id: folderId ?? null,
    }),
    signal,
  });
  if (!res.ok) {
    throw await httpError(res);
  }
}

async function abortSession(
  workspaceId: string,
  session: CreateSessionResponse,
): Promise<void> {
  try {
    await fetch(`${uploadsBase(workspaceId)}/abort`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        upload_id: session.upload_id,
        object_key: session.object_key,
      }),
      // Best-effort: never let abort cleanup throw or be cancelled.
      keepalive: true,
    });
  } catch {
    // Swallow — abort is best-effort cleanup.
  }
}

export async function uploadFileResumable(
  workspaceId: string,
  file: File,
  opts: UploadOptions = {},
): Promise<UploadResult> {
  if (opts.signal?.aborted) {
    return { ok: false, error: "aborted", aborted: true };
  }

  let session: CreateSessionResponse | null = null;
  try {
    session = await createSession(workspaceId, file, opts.signal);

    if (file.size > session.max_bytes) {
      await abortSession(workspaceId, session);
      return {
        ok: false,
        error: `file exceeds maximum size (${session.max_bytes} bytes)`,
      };
    }

    // Emit an initial 0% tick so consumers can render immediately.
    opts.onProgress?.(0, file.size);

    const tasks = buildPartTasks(file, session.part_size);
    const parts = await uploadAllParts(
      workspaceId,
      session,
      tasks,
      file.size,
      opts,
    );

    await completeSession(workspaceId, session, file.name, parts, opts.folderId, opts.signal);
    opts.onProgress?.(file.size, file.size);
    return { ok: true };
  } catch (err) {
    const aborted =
      err instanceof AbortedError ||
      (err instanceof DOMException && err.name === "AbortError") ||
      Boolean(opts.signal?.aborted);
    if (session) {
      await abortSession(workspaceId, session);
    }
    const error = aborted ? "aborted" : err instanceof Error ? err.message : String(err);
    if (!aborted && err instanceof UploadHttpError) {
      const failure = classifyUploadFailure(err.status, err.message, err.retryAfter);
      if (failure.code === "embedding_unavailable") {
        return { ok: false, error, aborted, code: failure.code, retryAfterSeconds: failure.retryAfterSeconds };
      }
      if (failure.code) return { ok: false, error, aborted, code: failure.code };
    }
    return { ok: false, error, aborted };
  }
}
