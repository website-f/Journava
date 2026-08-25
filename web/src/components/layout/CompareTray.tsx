import { useNavigate, useLocation } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { Scales } from "@/components/ui/icons";
import { useCompareStore } from "@/stores/compareStore";

/**
 * A floating "compare cart": once the traveller has ticked trips to compare, a
 * pill sits above the nav showing the count and opening the comparison page.
 * Hidden when empty or already on the compare page.
 */
export function CompareTray() {
  const count = useCompareStore((s) => s.ids.length);
  const navigate = useNavigate();
  const { pathname } = useLocation();

  const show = count > 0 && pathname !== "/compare";

  return (
    <AnimatePresence>
      {show && (
        <motion.button
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: 12 }}
          onClick={() => navigate("/compare")}
          className="glass-strong fixed left-1/2 z-[70] flex -translate-x-1/2 items-center gap-2 rounded-[var(--r-pill)] px-4 py-2.5 text-sm font-semibold text-[var(--brand-600)] shadow-[var(--shadow-2)]"
          style={{ bottom: "calc(var(--safe-bottom) + 5.5rem)" }}
          aria-label={`Compare ${count} trips`}
        >
          <Scales className="h-4 w-4" weight="fill" />
          Compare
          <span className="grid h-5 min-w-5 place-items-center rounded-full bg-[var(--brand-500)] px-1 text-xs font-bold text-white tabular-nums">
            {count}
          </span>
        </motion.button>
      )}
    </AnimatePresence>
  );
}
