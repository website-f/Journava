import { create } from "zustand";

type Theme = "light" | "dark";

const STORAGE_KEY = "journava.theme";

function readInitial(): Theme {
  const attr = document.documentElement.dataset.theme;
  return attr === "dark" ? "dark" : "light";
}

function apply(theme: Theme) {
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    /* storage blocked — theme stays for this session only */
  }
}

type ThemeStore = {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  toggle: () => void;
};

/** Theme is applied to <html data-theme> before first paint (see index.html). */
export const useTheme = create<ThemeStore>((set, get) => ({
  theme: readInitial(),
  setTheme: (theme) => {
    apply(theme);
    set({ theme });
  },
  toggle: () => get().setTheme(get().theme === "dark" ? "light" : "dark"),
}));
