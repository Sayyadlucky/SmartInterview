import { Injectable, signal } from '@angular/core';

export type AppToastTone = 'success' | 'error' | 'info' | 'warning';

export interface AppToastItem {
  id: number;
  tone: AppToastTone;
  title: string;
  message: string;
  createdAt: number;
  duration: number;
}

type AppToastConfig = Omit<AppToastItem, 'id' | 'createdAt'> & { duration?: number };

@Injectable({ providedIn: 'root' })
export class AppToastService {
  readonly toasts = signal<AppToastItem[]>([]);
  private nextId = 1;
  private readonly timers = new Map<number, ReturnType<typeof window.setTimeout>>();

  show(config: AppToastConfig): number {
    const id = this.nextId++;
    const toast: AppToastItem = {
      id,
      tone: config.tone,
      title: config.title,
      message: config.message,
      createdAt: Date.now(),
      duration: config.duration ?? 4800,
    };

    this.toasts.update((items) => [...items, toast]);
    const timer = window.setTimeout(() => this.dismiss(id), toast.duration);
    this.timers.set(id, timer);
    return id;
  }

  showSuccess(title: string, message: string, duration = 4400): number {
    return this.show({ tone: 'success', title, message, duration });
  }

  showError(title: string, message: string, duration = 5600): number {
    return this.show({ tone: 'error', title, message, duration });
  }

  showInfo(title: string, message: string, duration = 4200): number {
    return this.show({ tone: 'info', title, message, duration });
  }

  showWarning(title: string, message: string, duration = 5200): number {
    return this.show({ tone: 'warning', title, message, duration });
  }

  dismiss(id: number): void {
    const timer = this.timers.get(id);
    if (timer) {
      window.clearTimeout(timer);
      this.timers.delete(id);
    }
    this.toasts.update((items) => items.filter((item) => item.id !== id));
  }
}
