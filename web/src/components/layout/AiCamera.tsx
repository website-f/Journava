import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import {
  Camera, X, RefreshCw, Sparkles, Video, Newspaper, Globe, Share, Compass, CheckCircle2, Image as ImageIcon,
} from "@/components/ui/icons";
import type { IconType } from "@/components/ui/icons";
import { Button } from "@/components/ui";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";

/**
 * AI camera — a native-feeling capture surface for visual search.
 *
 * Live camera (getUserMedia) with a shutter + flash; on capture the frame is
 * compressed and sent to /vision/identify (a vision model + Camofox references).
 * A progress ring runs to ~10s. The result — what it is, interesting facts, and
 * TikTok/YouTube/news/web links — can be saved to the Discovery page. When the
 * camera isn't available (permissions / desktop) it falls back to the device's
 * native photo picker.
 */

type VisionLink = { type: string; title: string; url: string };
type VisionResult = {
  is_random: boolean; title: string; category: string; confidence: number;
  description: string; facts: string[]; links: VisionLink[]; query?: string;
};

const LINK_ICON: Record<string, IconType> = { video: Video, social: Share, news: Newspaper, web: Globe };
const CAT_TONE: Record<string, string> = {
  place: "var(--brand-500)", landmark: "var(--brand-500)", food: "var(--accent)", drink: "var(--accent)",
  nature: "var(--success)", animal: "var(--success)", art: "var(--warm)", object: "var(--muted)",
};

export function AiCamera({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate();
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const [stage, setStage] = useState<"camera" | "analyzing" | "result">("camera");
  const [captured, setCaptured] = useState<string | null>(null);
  const [result, setResult] = useState<VisionResult | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [flash, setFlash] = useState(false);
  const [camError, setCamError] = useState(false);
  const [facing, setFacing] = useState<"environment" | "user">("environment");
  const [saved, setSaved] = useState(false);

  const stopStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }, []);

  const startCamera = useCallback(async () => {
    stopStream();
    if (!navigator.mediaDevices?.getUserMedia) { setCamError(true); return; }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: facing }, audio: false });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play().catch(() => {});
      }
      setCamError(false);
    } catch {
      setCamError(true);
    }
  }, [facing, stopStream]);

  // Open/close + (re)start when returning to the camera stage or flipping.
  useEffect(() => {
    if (!open) { stopStream(); return; }
    if (stage === "camera") void startCamera();
    else stopStream();
    return () => { if (!open) stopStream(); };
  }, [open, stage, facing, startCamera, stopStream]);
  useEffect(() => () => stopStream(), [stopStream]);

  // Escape closes.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  // Elapsed timer while analyzing (progress indication, target < 10s).
  useEffect(() => {
    if (stage !== "analyzing") return;
    setElapsed(0);
    const t = window.setInterval(() => setElapsed((e) => Math.min(e + 0.1, 15)), 100);
    return () => window.clearInterval(t);
  }, [stage]);

  const analyze = useCallback(async (dataUrl: string) => {
    setCaptured(dataUrl);
    setResult(null);
    setSaved(false);
    setStage("analyzing");
    stopStream();
    try {
      const r = await api.post<VisionResult>("/vision/identify", { image: dataUrl });
      setResult(r);
    } catch {
      setResult({ is_random: true, title: "Couldn't analyze", category: "unclear", confidence: 0, description: "Something went wrong — try again.", facts: [], links: [] });
    } finally {
      setStage("result");
    }
  }, [stopStream]);

  const capture = () => {
    const v = videoRef.current;
    if (!v || !v.videoWidth) return;
    const scale = Math.min(1, 1280 / Math.max(v.videoWidth, v.videoHeight));
    const cw = Math.round(v.videoWidth * scale), ch = Math.round(v.videoHeight * scale);
    const c = document.createElement("canvas");
    c.width = cw; c.height = ch;
    const ctx = c.getContext("2d");
    if (!ctx) return;
    ctx.drawImage(v, 0, 0, cw, ch);
    setFlash(true);
    window.setTimeout(() => setFlash(false), 220);
    void analyze(c.toDataURL("image/jpeg", 0.82));
  };

  const onFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    const fr = new FileReader();
    fr.onload = () => void analyze(String(fr.result));
    fr.readAsDataURL(f);
  };

  const retake = () => { setResult(null); setCaptured(null); setStage("camera"); };
  const save = async () => {
    if (!result || result.is_random) return;
    try {
      await api.post("/discoveries", {
        image_url: captured, title: result.title, category: result.category,
        description: result.description, facts: result.facts, links: result.links,
      });
      setSaved(true);
      toast.success("Saved to your Discovery page");
    } catch {
      toast.error("Couldn't save that.");
    }
  };
  const close = () => { stopStream(); onClose(); };

  const progress = useMemo(() => Math.min(100, (elapsed / 10) * 100), [elapsed]);
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[95] flex flex-col bg-black text-white" style={{ paddingTop: "env(safe-area-inset-top)", paddingBottom: "env(safe-area-inset-bottom)" }}>
      {/* Top bar */}
      <div className="flex items-center gap-2 px-4 py-3">
        <span className="flex items-center gap-1.5 text-sm font-semibold"><Camera className="h-4 w-4" weight="fill" /> AI Camera</span>
        {stage === "camera" && !camError && (
          <button onClick={() => setFacing((f) => (f === "environment" ? "user" : "environment"))} aria-label="Flip camera" className="ml-auto grid h-9 w-9 place-items-center rounded-full bg-white/10 hover:bg-white/20">
            <RefreshCw className="h-4 w-4" />
          </button>
        )}
        <button onClick={close} aria-label="Close" className={cn("grid h-9 w-9 place-items-center rounded-full bg-white/10 hover:bg-white/20", stage !== "camera" || camError ? "ml-auto" : "")}>
          <X className="h-5 w-5" />
        </button>
      </div>

      {/* Viewport */}
      <div className="relative min-h-0 flex-1 overflow-hidden">
        {/* Live video (camera stage) */}
        {stage === "camera" && !camError && (
          <video ref={videoRef} playsInline muted className="h-full w-full object-cover" />
        )}
        {/* Camera unavailable → native picker fallback */}
        {stage === "camera" && camError && (
          <div className="grid h-full place-items-center px-8 text-center">
            <div className="space-y-3">
              <ImageIcon className="mx-auto h-10 w-10 text-white/70" weight="duotone" />
              <p className="text-sm text-white/80">Camera not available here. Pick a photo and I'll identify it.</p>
              <Button variant="secondary" onClick={() => fileRef.current?.click()}>Choose a photo</Button>
            </div>
          </div>
        )}
        {/* Frozen frame during analyze + result */}
        {stage !== "camera" && captured && (
          <img src={captured} alt="captured" className={cn("h-full w-full object-cover", stage === "analyzing" && "opacity-60")} />
        )}
        {/* Shutter flash */}
        {flash && <div className="absolute inset-0 animate-[journava-out_220ms_ease] bg-white" />}

        {/* Analyzing overlay */}
        {stage === "analyzing" && (
          <div className="absolute inset-0 grid place-items-center bg-black/40 backdrop-blur-[2px]">
            <div className="flex flex-col items-center gap-3">
              <span className="grid h-16 w-16 place-items-center rounded-full bg-white/10">
                <span className="h-9 w-9 animate-spin rounded-full border-[3px] border-white/30 border-t-white" />
              </span>
              <p className="flex items-center gap-1.5 text-sm font-medium"><Sparkles className="h-4 w-4" /> Looking it up… {elapsed.toFixed(1)}s</p>
              <div className="h-1 w-48 overflow-hidden rounded-full bg-white/20">
                <div className="h-full bg-white transition-[width] duration-100" style={{ width: `${progress}%` }} />
              </div>
              <p className="text-[0.7rem] text-white/60">vision + live web via Camofox</p>
            </div>
          </div>
        )}
      </div>

      {/* Shutter (camera stage) */}
      {stage === "camera" && !camError && (
        <div className="grid place-items-center py-6">
          <button onClick={capture} aria-label="Capture" className="grid h-[4.5rem] w-[4.5rem] place-items-center rounded-full ring-4 ring-white/40 transition-transform active:scale-90">
            <span className="h-[3.6rem] w-[3.6rem] rounded-full bg-white" />
          </button>
          <p className="mt-2 text-[0.7rem] text-white/60">Point at a place, food, landmark, plant or object</p>
        </div>
      )}

      {/* Result sheet */}
      {stage === "result" && result && (
        <div className="max-h-[62%] overflow-y-auto rounded-t-[var(--r-xl)] bg-[var(--surface)] p-5 text-[var(--text)]">
          {result.is_random ? (
            <div className="text-center">
              <p className="text-4xl">🤔</p>
              <p className="mt-2 text-base font-semibold">{result.title}</p>
              <p className="mt-1 text-sm text-[var(--muted)]">{result.description}</p>
              <div className="mt-4 flex justify-center gap-2">
                <Button variant="secondary" onClick={retake}><RefreshCw className="h-4 w-4" /> Snap again</Button>
              </div>
            </div>
          ) : (
            <>
              <div className="flex items-start gap-2">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="font-[family-name:var(--font-display)] text-xl font-bold tracking-tight">{result.title}</h3>
                    <span className="rounded-[var(--r-pill)] px-2 py-0.5 text-[0.6rem] font-semibold uppercase text-white" style={{ background: CAT_TONE[result.category] ?? "var(--muted)" }}>{result.category}</span>
                    {result.confidence >= 0.4 && <span className="text-[0.65rem] text-[var(--muted)]">{Math.round(result.confidence * 100)}% sure</span>}
                  </div>
                  <p className="mt-1 text-sm text-[var(--muted)]">{result.description}</p>
                </div>
              </div>

              {result.facts.length > 0 && (
                <ul className="mt-3 space-y-1.5">
                  {result.facts.map((f, i) => (
                    <li key={i} className="flex items-start gap-1.5 text-sm"><Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[var(--accent)]" /> {f}</li>
                  ))}
                </ul>
              )}

              {result.links.length > 0 && (
                <div className="mt-3">
                  <p className="mb-1.5 text-[0.65rem] font-semibold uppercase tracking-wide text-[var(--muted)]">Watch · read · explore</p>
                  <div className="flex flex-wrap gap-1.5">
                    {result.links.map((l, i) => {
                      const Icon = LINK_ICON[l.type] ?? Globe;
                      return (
                        <a key={i} href={l.url} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1.5 rounded-[var(--r-pill)] border border-[var(--border)] bg-[var(--bg)] px-2.5 py-1 text-xs hover:border-[var(--brand-400)]">
                          <Icon className="h-3.5 w-3.5 text-[var(--brand-500)]" /> {l.title}
                        </a>
                      );
                    })}
                  </div>
                </div>
              )}

              <div className="mt-4 flex flex-wrap gap-2">
                <Button variant="secondary" onClick={retake}><RefreshCw className="h-4 w-4" /> Snap again</Button>
                {saved ? (
                  <Button onClick={() => { close(); navigate("/discover"); }}><CheckCircle2 className="h-4 w-4" /> View in Discovery</Button>
                ) : (
                  <Button onClick={() => void save()}><Compass className="h-4 w-4" /> Save to Discovery</Button>
                )}
              </div>
            </>
          )}
        </div>
      )}

      <input ref={fileRef} type="file" accept="image/*" capture="environment" hidden onChange={onFile} />
    </div>
  );
}
