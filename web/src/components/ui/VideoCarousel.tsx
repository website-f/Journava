import { useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { motion } from "framer-motion";
import { Rail } from "@/components/layout/Page";
import { Play, Video, X } from "@/components/ui/icons";
import { cn } from "@/lib/cn";
import type { VideoReview } from "@/lib/types";

/**
 * A horizontally-scrollable strip of short-video reviews. Tapping one opens it in
 * a modal player — a YouTube iframe (16:9) or a TikTok embed (9:16). Kept as
 * iframes (not the TikTok script) so there's nothing external to load until the
 * viewer actually opens a clip.
 */

function views(n?: number): string {
  if (!n) return "";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M views`;
  if (n >= 1_000) return `${Math.round(n / 1_000)}K views`;
  return `${n} views`;
}

export function VideoCarousel({ videos }: { videos: VideoReview[] }) {
  const [active, setActive] = useState<VideoReview | null>(null);

  if (!videos?.length) {
    return (
      <p className="py-6 text-center text-sm text-[var(--muted)]">
        No video reviews found for this yet.
      </p>
    );
  }

  return (
    <>
      {/*
        `locked`: a video strip stays a carousel at every width. Turning it into a
        grid would be wrong — the whole point is that there are more clips than
        fit, and the partial card at the edge is what says "keep swiping".
      */}
      <Rail card="15rem" pad="0.25rem" locked aria-label="Video reviews">
        {videos.map((v) => (
          <button
            key={`${v.platform}-${v.id}`}
            onClick={() => setActive(v)}
            className={cn(
              "pressable group relative overflow-hidden rounded-[var(--r-lg)]",
              "surface-card p-0 text-left",
            )}
          >
            <div className="relative aspect-video w-full overflow-hidden bg-[var(--bg)]">
              {v.thumbnail ? (
                <img
                  src={v.thumbnail}
                  alt=""
                  loading="lazy"
                  className="h-full w-full object-cover"
                />
              ) : (
                <div className="grid h-full w-full place-items-center bg-[color-mix(in_srgb,var(--brand-400)_16%,var(--surface))]">
                  <Video className="h-8 w-8 text-[var(--brand-500)]" />
                </div>
              )}
              <span className="absolute inset-0 grid place-items-center bg-black/20 opacity-0 transition-opacity group-hover:opacity-100">
                <span className="grid h-11 w-11 place-items-center rounded-full bg-white/90 text-[var(--brand-600)] shadow-[var(--shadow-2)]">
                  <Play className="h-5 w-5" />
                </span>
              </span>
              <span className="absolute left-2 top-2 rounded-[var(--r-pill)] bg-black/70 px-1.5 py-0.5 text-[0.6rem] font-semibold uppercase tracking-wide text-white">
                {v.platform}
              </span>
            </div>
            <div className="p-2.5">
              <p className="line-clamp-2 text-xs font-medium leading-snug">{v.title}</p>
              <p className="mt-1 truncate text-[0.65rem] text-[var(--muted)]">
                {[v.channel, views(v.views)].filter(Boolean).join(" · ")}
              </p>
            </div>
          </button>
        ))}
      </Rail>

      {active && <VideoModal video={active} onClose={() => setActive(null)} />}
    </>
  );
}

function VideoModal({ video, onClose }: { video: VideoReview; onClose: () => void }) {
  const vertical = video.platform === "tiktok";
  return (
    <Dialog.Root open onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay asChild>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-[85] bg-black/60 backdrop-blur-sm"
          />
        </Dialog.Overlay>
        <Dialog.Content asChild>
          <motion.div
            initial={{ opacity: 0, scale: 0.97 }}
            animate={{ opacity: 1, scale: 1 }}
            className={cn(
              "fixed left-1/2 top-1/2 z-[86] w-[calc(100%-2rem)] -translate-x-1/2 -translate-y-1/2",
              "overflow-hidden rounded-[var(--r-lg)] border border-[var(--border)] bg-[var(--elevated)]",
              "shadow-[var(--shadow-2)]",
              vertical ? "max-w-sm" : "max-w-3xl",
            )}
          >
            <div className="flex items-center justify-between gap-2 p-3">
              <Dialog.Title className="min-w-0 truncate text-sm font-semibold">
                {video.title}
              </Dialog.Title>
              <Dialog.Close asChild>
                <button
                  aria-label="Close"
                  className="grid h-8 w-8 shrink-0 place-items-center rounded-full hover:bg-[var(--surface)]"
                >
                  <X className="h-4 w-4" />
                </button>
              </Dialog.Close>
            </div>
            <div className={cn("mx-auto w-full bg-black", vertical ? "aspect-[9/16] max-w-[360px]" : "aspect-video")}>
              <iframe
                src={video.embed_url}
                title={video.title}
                className="h-full w-full"
                allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; fullscreen"
                allowFullScreen
              />
            </div>
            <div className="p-3 text-right">
              <a
                href={video.watch_url}
                target="_blank"
                rel="noreferrer noopener"
                className="text-xs text-[var(--brand-500)] hover:underline"
              >
                Open on {video.platform}
              </a>
            </div>
          </motion.div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
