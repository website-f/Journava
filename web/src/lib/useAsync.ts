import { useCallback, useRef, useState } from "react";

type AsyncState = { loading: boolean; error: unknown };

/**
 * Wraps an async handler so every button gets loading + error state for free
 * (spec §10.2 — "devs never forget"). Ignores re-entrant calls while pending.
 */
export function useAsync<A extends unknown[], R>(
  fn: (...args: A) => Promise<R>,
) {
  const [{ loading, error }, setState] = useState<AsyncState>({
    loading: false,
    error: null,
  });
  const pending = useRef(false);

  const run = useCallback(
    async (...args: A): Promise<R | undefined> => {
      if (pending.current) return undefined;
      pending.current = true;
      setState({ loading: true, error: null });
      try {
        return await fn(...args);
      } catch (err) {
        setState({ loading: false, error: err });
        throw err;
      } finally {
        pending.current = false;
        setState((prev) => ({ ...prev, loading: false }));
      }
    },
    [fn],
  );

  return { run, loading, error };
}
