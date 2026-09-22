/**
 * Voice input for the dashboard chat. Copyright (c) 2026 Ignitee Now.
 *
 * Click to talk, click again to stop. The recording is posted to
 * `/api/audio/transcribe` on the Robo process running on the user's own
 * computer (the one `robo dashboard` starts), which transcribes it locally by
 * default. The transcript is handed to `onTranscript`, which the chat page
 * types into the terminal's input line so it can be reviewed before Enter.
 *
 * There is no hosted service involved. The microphone is released the moment
 * recording stops or the page unmounts.
 */
import { Loader2, Mic, Square } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";

import { useToast } from "@igniteenow/ui/hooks/use-toast";
import { Button } from "@igniteenow/ui/ui/components/button";
import { Toast } from "@igniteenow/ui/ui/components/toast";

import { fetchJSON } from "@/lib/api";
import { cn } from "@/lib/utils";

type Phase = "idle" | "recording" | "transcribing";

interface TranscribeResponse {
  ok?: boolean;
  transcript?: string;
  provider?: string | null;
}

interface VoiceInputButtonProps {
  /** Receives the transcript once the server has it. Never called with empty text. */
  onTranscript: (text: string) => void;
  className?: string;
  style?: CSSProperties;
  /** Hide the label and show only the icon (narrow layouts). */
  compact?: boolean;
}

const PREFERRED_MIME = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];
const MAX_SECONDS = 120;

function pickMimeType(): string | undefined {
  if (typeof MediaRecorder === "undefined" || typeof MediaRecorder.isTypeSupported !== "function") return undefined;
  return PREFERRED_MIME.find((m) => MediaRecorder.isTypeSupported(m));
}

function blobToDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(reader.error ?? new Error("Could not read the recording"));
    reader.readAsDataURL(blob);
  });
}

export function VoiceInputButton({ onTranscript, className, style, compact = false }: VoiceInputButtonProps) {
  const [phase, setPhase] = useState<Phase>("idle");
  const { toast, showToast } = useToast();
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const supported = typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== "undefined";

  const releaseMic = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    recorderRef.current = null;
  }, []);

  useEffect(() => releaseMic, [releaseMic]);

  const transcribe = useCallback(
    async (blob: Blob, mimeType: string) => {
      setPhase("transcribing");
      try {
        if (blob.size < 1024) {
          showToast("Nothing was recorded. Hold the button a little longer.", "warning");
          return;
        }
        const data_url = await blobToDataUrl(blob);
        const result = await fetchJSON<TranscribeResponse>("/api/audio/transcribe", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ data_url, mime_type: mimeType }),
        });
        const text = (result.transcript ?? "").trim();
        if (!text) {
          showToast("Nothing was heard. Try again, closer to the microphone.", "warning");
          return;
        }
        onTranscript(text);
      } catch (error) {
        showToast(error instanceof Error ? error.message : "Transcription failed.", "error");
      } finally {
        setPhase("idle");
      }
    },
    [onTranscript, showToast],
  );

  const start = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = pickMimeType();
      const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (event: BlobEvent) => {
        if (event.data && event.data.size > 0) chunksRef.current.push(event.data);
      };
      recorder.onstop = () => {
        const type = recorder.mimeType || mimeType || "audio/webm";
        const blob = new Blob(chunksRef.current, { type });
        releaseMic();
        void transcribe(blob, type);
      };
      recorder.onerror = () => {
        releaseMic();
        setPhase("idle");
        showToast("The microphone stopped unexpectedly.", "error");
      };
      streamRef.current = stream;
      recorderRef.current = recorder;
      recorder.start();
      setPhase("recording");
      timerRef.current = setTimeout(() => {
        if (recorderRef.current?.state === "recording") recorderRef.current.stop();
      }, MAX_SECONDS * 1000);
    } catch (error) {
      releaseMic();
      setPhase("idle");
      const name = error instanceof DOMException ? error.name : "";
      if (name === "NotAllowedError" || name === "SecurityError") {
        showToast("Microphone access was denied. Allow it in the browser's site settings, then try again.", "error");
      } else if (name === "NotFoundError") {
        showToast("No microphone was found.", "error");
      } else {
        showToast(error instanceof Error ? error.message : "Could not start recording.", "error");
      }
    }
  }, [releaseMic, showToast, transcribe]);

  const stop = useCallback(() => {
    const recorder = recorderRef.current;
    if (recorder && recorder.state === "recording") recorder.stop();
    else releaseMic();
  }, [releaseMic]);

  if (!supported) return null;

  const recording = phase === "recording";
  const busy = phase === "transcribing";
  const label = recording ? "stop" : busy ? "transcribing" : "talk";

  return (
    <>
      <Button
        size="xs"
        aria-label={recording ? "Stop recording" : "Talk to Robo (records your voice and types it into the chat)"}
        aria-pressed={recording}
        title={recording ? "Stop and transcribe" : "Talk: the transcript is typed into the chat; press Enter to send"}
        disabled={busy}
        onClick={recording ? stop : start}
        className={cn(
          "normal-case tracking-normal font-normal rounded border border-current/30 bg-black/20",
          "opacity-70 hover:opacity-100 hover:border-current/60 transition-opacity duration-150",
          recording && "opacity-100 border-current/70",
          className,
        )}
        style={style}
      >
        <span className="inline-flex items-center gap-1.5">
          {busy ? (
            <Loader2 className="h-3 w-3 shrink-0 animate-spin" />
          ) : recording ? (
            <Square className="h-3 w-3 shrink-0" />
          ) : (
            <Mic className="h-3 w-3 shrink-0" />
          )}
          {!compact && <span className="hidden min-[400px]:inline tracking-wide">{label}</span>}
          {recording && <span className="h-1.5 w-1.5 rounded-full bg-[#D52734] animate-pulse" aria-hidden="true" />}
        </span>
      </Button>
      <Toast toast={toast} />
    </>
  );
}
