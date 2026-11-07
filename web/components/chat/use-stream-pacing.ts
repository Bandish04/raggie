// SPDX-License-Identifier: Apache-2.0

"use client";

import { useEffect, useRef } from "react";

import { takeStreamingPrefix } from "@/lib/streaming";

import type { Msg, StreamDelta } from "@/components/chat/chat-model";

/* Paced rendering of streamed reasoning/answer text: deltas are queued and
   drained a bounded chunk per animation frame (takeStreamingPrefix), so a burst
   from the upstream still reads as a stream. `patchLast` applies each chunk to
   the in-flight assistant message. */
export function useStreamPacing(patchLast: (fn: (m: Msg) => Msg) => void) {
  const pendingStreamRef = useRef<StreamDelta[]>([]);
  const streamFrameRef = useRef<number | null>(null);
  const streamDrainWaitersRef = useRef<Array<() => void>>([]);

  function resolveStreamDrainWaiters() {
    const waiters = streamDrainWaitersRef.current;
    streamDrainWaitersRef.current = [];
    for (const resolve of waiters) resolve();
  }

  function drainStreamDeltas() {
    streamFrameRef.current = null;
    const current = pendingStreamRef.current[0];
    if (!current) {
      resolveStreamDrainWaiters();
      return;
    }

    const { chunk, rest } = takeStreamingPrefix(current.text);
    if (rest) {
      pendingStreamRef.current[0] = { ...current, text: rest };
    } else {
      pendingStreamRef.current.shift();
    }

    if (chunk && current.kind === "thinking") {
      patchLast((m) => ({
        ...m,
        thinking: (m.thinking ?? "") + chunk,
        webSearching: false,
        deepSearching: false,
        searchStatus: undefined,
      }));
    } else if (chunk) {
      patchLast((m) => ({
        ...m,
        content: m.content + chunk,
        webSearching: m.webSearching ? false : m.webSearching,
        deepSearching: m.deepSearching ? false : m.deepSearching,
        thinkingDone: m.thinking ? true : m.thinkingDone,
        searchStatus: undefined,
      }));
    }

    if (pendingStreamRef.current.length > 0) {
      streamFrameRef.current = requestAnimationFrame(drainStreamDeltas);
    } else {
      resolveStreamDrainWaiters();
    }
  }

  function scheduleStreamDrain() {
    if (streamFrameRef.current === null) {
      streamFrameRef.current = requestAnimationFrame(drainStreamDeltas);
    }
  }

  function flushStreamDeltas() {
    if (streamFrameRef.current !== null) {
      cancelAnimationFrame(streamFrameRef.current);
      streamFrameRef.current = null;
    }
    const pending = pendingStreamRef.current;
    pendingStreamRef.current = [];
    if (pending.length === 0) {
      resolveStreamDrainWaiters();
      return;
    }

    let thinking = "";
    let answer = "";
    for (const delta of pending) {
      if (delta.kind === "thinking") thinking += delta.text;
      else answer += delta.text;
    }
    patchLast((m) => ({
      ...m,
      thinking: (m.thinking ?? "") + thinking,
      content: m.content + answer,
      webSearching: m.webSearching ? false : m.webSearching,
      deepSearching: m.deepSearching ? false : m.deepSearching,
      thinkingDone: m.thinking || thinking ? true : m.thinkingDone,
      searchStatus: undefined,
    }));
    resolveStreamDrainWaiters();
  }

  function enqueueStreamDelta(kind: StreamDelta["kind"], text: string) {
    const pending = pendingStreamRef.current;
    const last = pending[pending.length - 1];
    if (last?.kind === kind) last.text += text;
    else pending.push({ kind, text });
    scheduleStreamDrain();
  }

  function waitForStreamDrain(): Promise<void> {
    if (pendingStreamRef.current.length === 0 && streamFrameRef.current === null) {
      return Promise.resolve();
    }
    scheduleStreamDrain();
    return new Promise((resolve) => {
      streamDrainWaitersRef.current.push(resolve);
    });
  }

  useEffect(
    () => () => {
      if (streamFrameRef.current !== null) {
        cancelAnimationFrame(streamFrameRef.current);
        streamFrameRef.current = null;
      }
      pendingStreamRef.current = [];
      resolveStreamDrainWaiters();
    },
    [],
  );

  return { enqueueStreamDelta, flushStreamDeltas, waitForStreamDrain };
}
