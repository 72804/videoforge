import { describe, expect, it } from "vitest";
import { applyTelegramChrome } from "./telegram";
import { getAppearance, resolvedTheme, setAppearance } from "./theme";

function memoryStorage() {
  const data = new Map<string, string>();
  const storage = {
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => {
      data.set(key, value);
    },
    removeItem: (key: string) => {
      data.delete(key);
    },
    clear: () => data.clear(),
    key: (index: number) => [...data.keys()][index] ?? null,
    get length() {
      return data.size;
    },
  };
  Object.defineProperty(globalThis, "localStorage", { value: storage, configurable: true });
  if (typeof window !== "undefined") {
    Object.defineProperty(window, "localStorage", { value: storage, configurable: true });
  }
}

describe("appearance", () => {
  it("defaults to dark even if Telegram reports light", () => {
    applyTelegramChrome({
      initData: "query_id=1",
      initDataUnsafe: { user: { id: 99 } },
      colorScheme: "light",
      themeParams: { bg_color: "#ffffff" },
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
    expect(resolvedTheme("dark", false)).toBe("dark");
    expect(document.documentElement.dataset.theme).not.toBe("light");
  });

  it("persists Light and System", () => {
    memoryStorage();
    expect(getAppearance()).toBe("dark");
    setAppearance("light");
    expect(getAppearance()).toBe("light");
    expect(resolvedTheme("system", true)).toBe("dark");
    expect(resolvedTheme("system", false)).toBe("light");
  });
});
