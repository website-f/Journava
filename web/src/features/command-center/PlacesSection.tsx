import {
  Badge,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui";
import { Rail, SectionHeader } from "@/components/layout/Page";
import { Video as VideoIcon } from "@/components/ui/icons";
import { VideoCarousel } from "@/components/ui/VideoCarousel";
import type { AgentPlanResult, PlanOption, VideoReview } from "@/lib/types";
import { PlaceCard } from "./PlaceCard";

/**
 * A places-to-visit / places-to-eat section with two tabs:
 *
 *  1. **Places / Restaurants** — every option independently, with its price,
 *     review snippet, source tag and a View button.
 *  2. **Video reviews** — the most-viewed YouTube (and best-effort TikTok) clips
 *     for the destination's top spots, in a tap-to-play carousel.
 */
export function PlacesSection({
  title,
  placesLabel,
  icon: Icon,
  result,
  extra,
  kind,
  videos,
}: {
  title: string;
  placesLabel: string;
  icon: typeof VideoIcon;
  result?: AgentPlanResult;
  extra?: AgentPlanResult;
  kind: PlanOption["kind"];
  videos: VideoReview[];
}) {
  const own = result?.options ?? [];
  const extras = extra?.options ?? [];
  const options = [...own, ...extras].filter((o) => o.kind === kind);

  if (options.length === 0 && videos.length === 0) return null;

  return (
    <section>
      <SectionHeader
        icon={<Icon className="h-[1.15rem] w-[1.15rem]" />}
        title={title}
        count={options.length}
        hint={result?.summary}
      />

      <Tabs defaultValue={options.length ? "places" : "videos"}>
        <TabsList>
          <TabsTrigger value="places">
            {placesLabel}
            {options.length > 0 && <Badge>{options.length}</Badge>}
          </TabsTrigger>
          <TabsTrigger value="videos">
            <VideoIcon className="h-4 w-4" /> Video reviews
            {videos.length > 0 && <Badge>{videos.length}</Badge>}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="places">
          {options.length > 0 ? (
            // A snap-scrolling rail on phones — a peek of the next card invites the
            // swipe — that becomes a real grid from md up, where a rail on a wide
            // screen just leaves the right half of the row empty.
            <Rail card="15.5rem" cols={2} colsLg={3} aria-label={placesLabel}>
              {options.map((option) => (
                <PlaceCard key={option.id} option={option} />
              ))}
            </Rail>
          ) : (
            <p className="py-6 text-center text-sm text-[var(--muted)]">
              No {placesLabel.toLowerCase()} found — check the video reviews tab.
            </p>
          )}
        </TabsContent>

        <TabsContent value="videos">
          <VideoCarousel videos={videos} />
        </TabsContent>
      </Tabs>

      {(result?.warnings ?? []).length > 0 && (
        <ul className="mt-3 space-y-1">
          {result!.warnings.map((warning, index) => (
            <li key={index} className="text-[0.7rem] text-[var(--warning)]">
              {warning}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
