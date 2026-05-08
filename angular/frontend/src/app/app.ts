import { Component, ElementRef, OnDestroy, OnInit, ViewChild, inject, signal } from '@angular/core';
import { NgIf } from '@angular/common';
import { Title } from '@angular/platform-browser';
import { NavigationEnd, Router, TitleStrategy } from '@angular/router';
import { RouterOutlet } from '@angular/router';
import { filter } from 'rxjs';
import { ParticleBackgroundComponent } from './particle-background/particle-background';
import { AppToastStackComponent } from './core/app-toast-stack.component';

declare global {
  interface Window {
    shortlistiiIdleConfig?: {
      timeoutSeconds?: number;
      warningSeconds?: number;
      pingUrl?: string;
      logoutUrl?: string;
    };
  }
}

@Component({
  selector: 'app-root',
  imports: [NgIf, RouterOutlet, ParticleBackgroundComponent, AppToastStackComponent],
  templateUrl: './app.html',
  styleUrl: './app.scss'
}
)
export class App implements OnInit, OnDestroy {
  private readonly pageTitle = inject(Title);
  private readonly router = inject(Router);
  private readonly titleStrategy = inject(TitleStrategy);
  protected readonly appName = signal('frontend');
  protected idleWarningOpen = false;
  protected idleCountdownSeconds = 0;
  protected idleContinuePending = false;
  @ViewChild('idleContinueButton') private idleContinueButton?: ElementRef<HTMLButtonElement>;

  private readonly idleConfig = typeof window === 'undefined' ? null : window.shortlistiiIdleConfig ?? null;
  private readonly activityEvents = ['mousedown', 'keydown', 'scroll', 'touchstart', 'pointerdown'];
  private warningTimerId: number | null = null;
  private logoutTimerId: number | null = null;
  private countdownIntervalId: number | null = null;
  private lastActivityAt = 0;

  constructor() {
    this.applyRouteTitle();
    this.router.events
      .pipe(filter((event) => event instanceof NavigationEnd))
      .subscribe(() => this.applyRouteTitle());
  }

  ngOnInit(): void {
    this.startIdleTracking();
  }

  ngOnDestroy(): void {
    this.stopIdleTracking();
  }

  private applyRouteTitle(): void {
    const nextTitle = this.titleStrategy.buildTitle(this.router.routerState.snapshot) || 'Hiring Dashboard | Shortlistii';
    this.pageTitle.setTitle(nextTitle);
  }

  protected async continueSession(): Promise<void> {
    if (!this.idleConfig?.pingUrl || this.idleContinuePending) {
      return;
    }

    this.idleContinuePending = true;

    try {
      const response = await fetch(this.idleConfig.pingUrl, {
        method: 'GET',
        credentials: 'same-origin',
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
      });
      const contentType = response.headers.get('content-type') || '';
      if (!response.ok || !contentType.includes('application/json')) {
        throw new Error('Session refresh failed.');
      }

      const payload = await response.json() as { authenticated?: boolean };
      if (!payload?.authenticated) {
        throw new Error('Session expired.');
      }

      this.idleWarningOpen = false;
      this.idleContinuePending = false;
      this.lastActivityAt = Date.now();
      this.resetIdleTimers();
    } catch {
      this.forceLogout();
    }
  }

  protected logoutNow(): void {
    this.forceLogout();
  }

  protected formatIdleCountdown(totalSeconds: number): string {
    const safeSeconds = Math.max(0, Math.floor(totalSeconds || 0));
    const minutes = Math.floor(safeSeconds / 60);
    const seconds = safeSeconds % 60;
    return `${minutes}:${String(seconds).padStart(2, '0')}`;
  }

  private startIdleTracking(): void {
    if (typeof window === 'undefined' || !this.idleConfig?.timeoutSeconds) {
      return;
    }

    this.lastActivityAt = Date.now();
    this.activityEvents.forEach((eventName) => {
      window.addEventListener(eventName, this.handleUserActivity, { passive: true });
    });
    document.addEventListener('visibilitychange', this.handleVisibilityChange);
    this.resetIdleTimers();
  }

  private stopIdleTracking(): void {
    if (typeof window === 'undefined') {
      return;
    }

    this.activityEvents.forEach((eventName) => {
      window.removeEventListener(eventName, this.handleUserActivity);
    });
    document.removeEventListener('visibilitychange', this.handleVisibilityChange);
    this.clearIdleTimers();
  }

  private readonly handleUserActivity = (): void => {
    if (this.idleWarningOpen) {
      return;
    }

    const now = Date.now();
    if (now - this.lastActivityAt < 5000) {
      return;
    }

    this.lastActivityAt = now;
    this.resetIdleTimers();
  };

  private readonly handleVisibilityChange = (): void => {
    if (document.visibilityState === 'visible' && !this.idleWarningOpen) {
      this.lastActivityAt = Date.now();
      this.resetIdleTimers();
    }
  };

  private resetIdleTimers(): void {
    if (!this.idleConfig?.timeoutSeconds) {
      return;
    }

    const timeoutSeconds = Math.max(1, Math.floor(this.idleConfig.timeoutSeconds));
    const warningSeconds = Math.max(1, Math.min(Math.floor(this.idleConfig.warningSeconds || 60), timeoutSeconds - 1));
    const warningDelayMs = Math.max(1000, (timeoutSeconds - warningSeconds) * 1000);

    this.clearIdleTimers();
    this.warningTimerId = window.setTimeout(() => this.openIdleWarning(warningSeconds), warningDelayMs);
  }

  private openIdleWarning(warningSeconds: number): void {
    this.idleWarningOpen = true;
    this.idleContinuePending = false;
    this.idleCountdownSeconds = warningSeconds;
    this.countdownIntervalId = window.setInterval(() => {
      this.idleCountdownSeconds = Math.max(0, this.idleCountdownSeconds - 1);
    }, 1000);
    this.logoutTimerId = window.setTimeout(() => this.forceLogout(), warningSeconds * 1000);
    window.setTimeout(() => this.idleContinueButton?.nativeElement.focus(), 0);
  }

  private clearIdleTimers(): void {
    if (this.warningTimerId !== null) {
      window.clearTimeout(this.warningTimerId);
      this.warningTimerId = null;
    }
    if (this.logoutTimerId !== null) {
      window.clearTimeout(this.logoutTimerId);
      this.logoutTimerId = null;
    }
    if (this.countdownIntervalId !== null) {
      window.clearInterval(this.countdownIntervalId);
      this.countdownIntervalId = null;
    }
  }

  private forceLogout(): void {
    this.clearIdleTimers();
    const logoutUrl = this.idleConfig?.logoutUrl || '/logout/';
    window.location.assign(logoutUrl);
  }
}
