import { telegram } from "./telegram";

export function hapticSuccess(): void {
  telegram()?.HapticFeedback?.notificationOccurred("success");
}

export function hapticWarn(): void {
  telegram()?.HapticFeedback?.notificationOccurred("warning");
}

export function hapticTap(): void {
  telegram()?.HapticFeedback?.impactOccurred("light");
}
