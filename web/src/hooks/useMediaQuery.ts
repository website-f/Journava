import { useEffect, useState } from "react";

/** Reactive media query — used to swap the shell between desktop and mobile. */
export function useMediaQuery(query: string) {
  const [matches, setMatches] = useState(
    () => window.matchMedia(query).matches,
  );

  useEffect(() => {
    const mql = window.matchMedia(query);
    const onChange = (event: MediaQueryListEvent) => setMatches(event.matches);
    setMatches(mql.matches);
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, [query]);

  return matches;
}

/** Breakpoints mirror the design system (sm 640 · md 768 · lg 1024 · xl 1280). */
export const useIsDesktop = () => useMediaQuery("(min-width: 64rem)");
export const useIsMobile = () => useMediaQuery("(max-width: 47.99rem)");
