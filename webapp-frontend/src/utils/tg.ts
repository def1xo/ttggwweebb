export type HapticImpact = "light" | "medium" | "heavy" | "rigid" | "soft";

export type HapticNotify = "error" | "success" | "warning";

export function hapticImpact(type: HapticImpact = "light") {
  try {
    const tg: any = (window as any).Telegram?.WebApp;
    const api = tg?.HapticFeedback;
    if (!api || typeof api.impactOccurred !== "function") return;
    api.impactOccurred(type);
  } catch {
    // ignore
  }
}

export function hapticSelection() {
  try {
    const tg: any = (window as any).Telegram?.WebApp;
    const api = tg?.HapticFeedback;
    if (!api || typeof api.selectionChanged !== "function") return;
    api.selectionChanged();
  } catch {
    // ignore
  }
}

export function hapticNotify(type: HapticNotify = "success") {
  try {
    const tg: any = (window as any).Telegram?.WebApp;
    const api = tg?.HapticFeedback;
    if (!api || typeof api.notificationOccurred !== "function") return;
    api.notificationOccurred(type);
  } catch {
    // ignore
  }
}
