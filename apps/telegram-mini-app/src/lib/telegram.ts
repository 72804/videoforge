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
  openInvoice?: (url: string, callback?: (status: string) => void) => void;
};

export function telegram(): TelegramWebApp | null {
  if (typeof window === "undefined") return null;
  const webapp = (window as unknown as { Telegram?: { WebApp?: TelegramWebApp } }).Telegram
    ?.WebApp;
  return webapp || null;
}

export function applyTelegramChrome(webapp: TelegramWebApp | null): void {
  if (typeof document === "undefined") return;
  const params = webapp?.themeParams || {};
  const set = (name: string, value?: string) => {
    if (value) document.documentElement.style.setProperty(name, value);
  };
  set("--tg-button", params.button_color);
  set("--tg-button-text", params.button_text_color);
  set("--tg-hint", params.hint_color);
  set("--tg-link", params.link_color);
}
