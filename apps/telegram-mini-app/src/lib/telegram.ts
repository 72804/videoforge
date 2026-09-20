export type TelegramWebApp = {
  initData: string;
  initDataUnsafe: { user?: { id: number } };
  colorScheme?: "light" | "dark";
  themeParams?: Record<string, string>;
  ready: () => void;
  expand: () => void;
  BackButton: {
    show: () => void;
    hide: () => void;
    onClick: (fn: () => void) => void;
    offClick: (fn: () => void) => void;
  };
  MainButton: {
    setText: (text: string) => void;
    show: () => void;
    hide: () => void;
    enable: () => void;
    disable: () => void;
    onClick: (fn: () => void) => void;
    offClick: (fn: () => void) => void;
  };
  HapticFeedback?: {
    notificationOccurred: (type: "error" | "success" | "warning") => void;
    impactOccurred: (style: "light" | "medium" | "heavy") => void;
  };
};

export function telegram(): TelegramWebApp | null {
  if (typeof window === "undefined") return null;
  const webapp = (window as unknown as { Telegram?: { WebApp?: TelegramWebApp } }).Telegram
    ?.WebApp;
  return webapp || null;
}

export function applyTelegramTheme(webapp: TelegramWebApp | null): void {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  const params = webapp?.themeParams || {};
  const set = (name: string, value?: string) => {
    if (value) root.style.setProperty(name, value);
  };
  set("--tg-bg", params.bg_color);
  set("--tg-text", params.text_color);
  set("--tg-hint", params.hint_color);
  set("--tg-link", params.link_color);
  set("--tg-button", params.button_color);
  set("--tg-button-text", params.button_text_color);
  set("--tg-secondary", params.secondary_bg_color);
  root.dataset.theme = webapp?.colorScheme === "light" ? "light" : "dark";
}
