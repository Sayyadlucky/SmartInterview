import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { Component, Inject, OnDestroy, OnInit } from '@angular/core';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { catchError, of } from 'rxjs';

interface CallSessionData {
  id: number;
  interview_id: number;
  call_sid?: string;
  status: string;
  caller_phone_masked?: string;
  candidate_phone_masked?: string;
  billing_started_at?: string;
  candidate_connected_at?: string;
  ended_at?: string;
  billable_seconds?: number;
  connected_seconds?: number;
  disconnect_requested_at?: string;
  error_message?: string;
  can_close?: boolean;
  can_disconnect?: boolean;
  disconnect_unavailable_reason?: string;
}

@Component({
  selector: 'app-candidate-call-tracker',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './candidate-call-tracker.html',
  styleUrl: './candidate-call-tracker.scss',
})
export class CandidateCallTracker implements OnInit, OnDestroy {
  session: CallSessionData;
  loading = false;
  disconnecting = false;
  errorMessage = '';
  displayBillableSeconds = 0;
  displayConnectedSeconds = 0;
  private pollTimer?: number;
  private clockTimer?: number;

  constructor(
    private http: HttpClient,
    private dialogRef: MatDialogRef<CandidateCallTracker>,
    @Inject(MAT_DIALOG_DATA) public data: { interviewId: number; session: CallSessionData }
  ) {
    this.session = data.session;
    this.applySession(data.session);
    this.dialogRef.disableClose = true;
  }

  ngOnInit(): void {
    this.startClock();
    this.startPolling();
  }

  ngOnDestroy(): void {
    this.stopPolling();
    this.stopClock();
  }

  get isTerminal(): boolean {
    return !!this.session?.can_close;
  }

  get title(): string {
    switch (this.session?.status) {
      case 'dialing_agent':
        return 'Dialing your number';
      case 'connecting_candidate':
        return 'Connecting candidate';
      case 'in_progress':
        return 'Call in progress';
      case 'completed':
        return 'Call completed';
      case 'disconnected':
        return 'Call disconnected';
      case 'busy':
      case 'no_answer':
      case 'failed':
      case 'cancelled':
        return 'Unable to connect';
      default:
        return 'Preparing call';
    }
  }

  get description(): string {
    switch (this.session?.status) {
      case 'dialing_agent':
        return `Please receive the call on ${this.session?.caller_phone_masked || 'your registered number'}.`;
      case 'connecting_candidate':
        return `Your line is active. We are now connecting ${this.session?.candidate_phone_masked || 'the candidate'}.`;
      case 'in_progress':
        return `You are connected with ${this.session?.candidate_phone_masked || 'the candidate'}.`;
      case 'completed':
        return 'The Exotel session ended successfully.';
      case 'disconnected':
        return 'The call was disconnected and the session is closed.';
      case 'busy':
        return 'The candidate line appears busy right now.';
      case 'no_answer':
        return 'The candidate did not answer the call.';
      case 'cancelled':
        return 'The call was cancelled before it could complete.';
      case 'failed':
        return this.session?.error_message || 'The call could not be completed.';
      default:
        return 'Preparing the Exotel session.';
    }
  }

  get liveBillableSeconds(): number {
    return this.displayBillableSeconds;
  }

  get liveConnectedSeconds(): number {
    return this.displayConnectedSeconds;
  }

  get billableLabel(): string {
    return this.formatDuration(this.liveBillableSeconds);
  }

  get connectedLabel(): string {
    return this.formatDuration(this.liveConnectedSeconds);
  }

  close(): void {
    if (!this.isTerminal) {
      return;
    }
    this.dialogRef.close({ action: 'closed' });
  }

  disconnectCall(): void {
    if (this.disconnecting || !this.session?.can_disconnect) {
      return;
    }
    this.disconnecting = true;
    this.http.post<{ Success: boolean; Error?: string | null; Data?: CallSessionData }>(
      `${this.getApiBaseUrl()}/candidate-profile-data/${this.data.interviewId}/call-session/${this.session.id}/disconnect/`,
      {}
    ).pipe(
      catchError((error) => {
        this.disconnecting = false;
        this.errorMessage = error?.error?.Error || 'Unable to disconnect the Exotel call right now.';
        return of({ Success: false, Error: this.errorMessage, Data: undefined as CallSessionData | undefined });
      })
    ).subscribe((response) => {
      this.disconnecting = false;
      if (!response?.Success) {
        this.errorMessage = response?.Error || 'Unable to disconnect the Exotel call right now.';
        return;
      }
      if (response.Data) {
        this.applySession(response.Data);
      }
      this.errorMessage = '';
      this.fetchSession();
    });
  }

  private fetchSession(): void {
    if (!this.session?.id) return;
    this.loading = true;
    this.http.get<{ Success: boolean; Error?: string | null; Data?: CallSessionData }>(
      `${this.getApiBaseUrl()}/candidate-profile-data/${this.data.interviewId}/call-session/${this.session.id}/`
    ).pipe(
      catchError((error) => {
        this.loading = false;
        this.errorMessage = error?.error?.Error || 'Unable to fetch the current call status.';
        return of({ Success: false, Error: this.errorMessage, Data: undefined as CallSessionData | undefined });
      })
    ).subscribe((response) => {
      this.loading = false;
      if (!response?.Success || !response.Data) {
        this.errorMessage = response?.Error || this.errorMessage || 'Unable to fetch the current call status.';
        return;
      }
      this.applySession(response.Data);
      this.errorMessage = '';
      if (this.isTerminal) {
        this.stopPolling();
      }
    });
  }

  private startPolling(): void {
    this.stopPolling();
    this.pollTimer = window.setInterval(() => this.fetchSession(), 3000);
  }

  private stopPolling(): void {
    if (this.pollTimer) {
      window.clearInterval(this.pollTimer);
      this.pollTimer = undefined;
    }
  }

  private startClock(): void {
    this.stopClock();
    this.clockTimer = window.setInterval(() => {
      this.updateLiveDurations();
    }, 1000);
  }

  private stopClock(): void {
    if (this.clockTimer) {
      window.clearInterval(this.clockTimer);
      this.clockTimer = undefined;
    }
  }

  private formatDuration(totalSeconds: number): string {
    const seconds = Math.max(0, Math.floor(totalSeconds || 0));
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const remainder = seconds % 60;
    if (hours > 0) {
      return `${hours}:${minutes.toString().padStart(2, '0')}:${remainder.toString().padStart(2, '0')}`;
    }
    return `${minutes.toString().padStart(2, '0')}:${remainder.toString().padStart(2, '0')}`;
  }

  private getApiBaseUrl(): string {
    let port = '';
    if (window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost') {
      port = '8080';
    }
    return `${window.location.protocol}//${window.location.hostname}:${port}`;
  }

  private applySession(session: CallSessionData): void {
    this.session = session;
    this.displayBillableSeconds = Math.max(this.displayBillableSeconds, Math.max(0, session.billable_seconds || 0));
    this.displayConnectedSeconds = Math.max(this.displayConnectedSeconds, Math.max(0, session.connected_seconds || 0));
    this.updateLiveDurations();
  }

  private updateLiveDurations(): void {
    if (!this.session) {
      return;
    }
    const nowMs = Date.now();
    const billedFromClock = this.deriveSecondsFromTimestamp(this.session.billing_started_at, nowMs);
    const connectedFromClock = this.deriveSecondsFromTimestamp(this.session.candidate_connected_at, nowMs);
    const billedFromTerminal = this.deriveRangeSeconds(this.session.billing_started_at, this.session.ended_at);
    const connectedFromTerminal = this.deriveRangeSeconds(this.session.candidate_connected_at, this.session.ended_at);

    this.displayBillableSeconds = Math.max(
      this.displayBillableSeconds,
      Math.max(0, this.session.billable_seconds || 0),
      billedFromTerminal,
      !this.isTerminal ? billedFromClock : 0,
    );
    this.displayConnectedSeconds = Math.max(
      this.displayConnectedSeconds,
      Math.max(0, this.session.connected_seconds || 0),
      connectedFromTerminal,
      !this.isTerminal ? connectedFromClock : 0,
    );

    if (this.isTerminal) {
      this.displayBillableSeconds = Math.max(this.displayBillableSeconds, Math.max(0, this.session.billable_seconds || 0));
      this.displayConnectedSeconds = Math.max(this.displayConnectedSeconds, Math.max(0, this.session.connected_seconds || 0));
    }
  }

  private deriveSecondsFromTimestamp(rawValue?: string, nowMs: number = Date.now()): number {
    if (!rawValue) {
      return 0;
    }
    const startedMs = new Date(rawValue).getTime();
    if (Number.isNaN(startedMs)) {
      return 0;
    }
    return Math.max(0, Math.floor((nowMs - startedMs) / 1000));
  }

  private deriveRangeSeconds(startValue?: string, endValue?: string): number {
    if (!startValue || !endValue) {
      return 0;
    }
    const startMs = new Date(startValue).getTime();
    const endMs = new Date(endValue).getTime();
    if (Number.isNaN(startMs) || Number.isNaN(endMs)) {
      return 0;
    }
    return Math.max(0, Math.floor((endMs - startMs) / 1000));
  }
}
