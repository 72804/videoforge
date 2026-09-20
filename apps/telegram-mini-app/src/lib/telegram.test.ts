import { describe, expect, it } from "vitest";
import { applyTelegramTheme } from "./telegram";

describe("telegram theme", () => {
  it("applies dark fallback when no webapp", () => {
    applyTelegramTheme(null);
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("applies Telegram light scheme", () => {
    applyTelegramTheme({
      initData: "query_id=1",
      initDataUnsafe: { user: { id: 99 } },
      colorScheme: "light",
      themeParams: { bg_color: "#ffffff", text_color: "#111111" },
      ready: () => undefined,
      expand: () => undefined,
      BackButton: { show() {}, hide() {}, onClick() {}, offClick() {} },
      MainButton: {
        setText() {},
        show() {},
        hide() {},
        enable() {},
        disable() {},
        onClick() {},
        offClick() {},
      },
    });
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(document.documentElement.style.getPropertyValue("--tg-bg")).toBe("#ffffff");
  });
});
