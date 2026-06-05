import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { Component, Inject, OnDestroy, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { catchError, of } from 'rxjs';

interface CandidateSummaryData {
  id: number;
  name: string;
  email?: string;
  phone?: string;
  candidate_phone_masked?: string;
  role?: string;
  role_id?: number | null;
  status?: string;
  can_call_candidate?: boolean;
}

interface VerificationData {
  identity_verified?: boolean;
}

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
  created_at?: string;
  updated_at?: string;
  disconnect_requested_at?: string;
  outcome?: string;
  note?: string;
  note_updated_at?: string;
  initiated_by_name?: string;
  error_message?: string;
  can_close?: boolean;
  can_disconnect?: boolean;
  disconnect_unavailable_reason?: string;
}

interface CallHistoryResponse {
  Success: boolean;
  Error?: string | null;
  Data?: {
    candidate?: CandidateSummaryData;
    sessions?: CallSessionData[];
  };
}

interface CandidateCallResponse {
  Success: boolean;
  Error?: string | null;
  Data?: {
    call_sid?: string;
    caller_phone_masked?: string;
    candidate_phone_masked?: string;
    session?: CallSessionData;
  };
}

type OutcomeKey = 'connected' | 'no_answer' | 'busy' | 'wrong_number' | 'not_reachable';

@Component({
  selector: 'app-candidate-call-tracker',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './candidate-call-tracker.html',
  styleUrl: './candidate-call-tracker.scss',
})
export class CandidateCallTracker implements OnInit, OnDestroy {
  session?: CallSessionData;
  candidate: CandidateSummaryData;
  verification?: VerificationData;
  loading = false;
  historyLoading = false;
  startingCandidateCall = false;
  savingNote = false;
  disconnecting = false;
  errorMessage = '';
  noteMessage = '';
  noteText = '';
  selectedOutcome: OutcomeKey | '' = '';
  callHistory: CallSessionData[] = [];
  displayBillableSeconds = 0;
  displayConnectedSeconds = 0;
  readonly maxNoteLength = 500;
  readonly outcomeOptions: Array<{ key: OutcomeKey; label: string; icon: string; tone: string }> = [
    { key: 'connected', label: 'Connected', icon: 'ph-phone-call', tone: 'green' },
    { key: 'no_answer', label: 'No Answer', icon: 'ph-phone-slash', tone: 'orange' },
    { key: 'busy', label: 'Busy', icon: 'ph-phone-x', tone: 'purple' },
    { key: 'wrong_number', label: 'Wrong Number', icon: 'ph-phone-disconnect', tone: 'red' },
    { key: 'not_reachable', label: 'Not Reachable', icon: 'ph-x-circle', tone: 'muted' },
  ];
  private pollTimer?: number;
  private clockTimer?: number;

  constructor(
    private http: HttpClient,
    private dialogRef: MatDialogRef<CandidateCallTracker>,
    @Inject(MAT_DIALOG_DATA) public data: { interviewId: number; session?: CallSessionData; candidate?: CandidateSummaryData; verification?: VerificationData }
  ) {
    this.session = data.session;
    this.candidate = data.candidate || {
      id: data.interviewId,
      name: 'Candidate',
      candidate_phone_masked: data.session?.candidate_phone_masked || '',
    };
    this.verification = data.verification;
    if (data.session) {
      this.applySession(data.session);
    }
    this.dialogRef.disableClose = true;
  }

  ngOnInit(): void {
    this.startClock();
    this.startPolling();
    this.fetchCallHistory();
  }

  ngOnDestroy(): void {
    this.stopPolling();
    this.stopClock();
  }

  get isTerminal(): boolean {
    return !this.session || !!this.session.can_close;
  }

  get hasActiveCall(): boolean {
    return !!this.session && !this.session.can_close;
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
        return `Your line is active. We are now connecting ${this.session?.candidate_phone_masked || this.candidatePhoneLabel}.`;
      case 'in_progress':
        return `You are connected with ${this.session?.candidate_phone_masked || this.candidatePhoneLabel}.`;
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

  get candidateInitials(): string {
    return (this.candidate?.name || 'Candidate')
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0]?.toUpperCase())
      .join('') || 'C';
  }

  get roleLabel(): string {
    const role = (this.candidate?.role || '').trim();
    const roleId = this.candidate?.role_id;
    if (!role) return 'Role not available';
    return roleId ? `${role} - ${roleId}` : role;
  }

  get candidatePhoneLabel(): string {
    return this.candidate?.candidate_phone_masked || this.session?.candidate_phone_masked || 'Candidate phone unavailable';
  }

  get statusLabel(): string {
    return this.labelize(this.session?.status || 'ready to call');
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

  get totalCalls(): number {
    return this.callHistory.length;
  }

  get connectedCalls(): number {
    return this.callHistory.filter((item) => this.wasConnected(item)).length;
  }

  get unansweredCalls(): number {
    return this.callHistory.filter((item) => ['no_answer', 'busy', 'failed', 'cancelled'].includes(item.status)).length;
  }

  get responseRateLabel(): string {
    if (!this.totalCalls) return 'No call data';
    return `${Math.round((this.connectedCalls / this.totalCalls) * 100)}% (${this.connectedCalls}/${this.totalCalls} calls connected)`;
  }

  get totalTalkTimeLabel(): string {
    return this.formatDuration(this.callHistory.reduce((total, item) => total + this.getConnectedSeconds(item), 0));
  }

  get averageDurationLabel(): string {
    if (!this.totalCalls) return '00:00';
    const totalSeconds = this.callHistory.reduce((total, item) => total + this.getConnectedSeconds(item), 0);
    return this.formatDuration(Math.round(totalSeconds / this.totalCalls));
  }

  get latestCall(): CallSessionData | undefined {
    return this.callHistory[0] || this.session;
  }

  get latestCallDateLabel(): string {
    return this.formatDateTime(this.latestCall?.created_at || '');
  }

  get latestStatusLabel(): string {
    return this.latestCall ? this.labelize(this.latestCall.status) : 'No calls recorded';
  }

  get latestOutcomeLabel(): string {
    const latestOutcome = this.latestCall?.outcome || '';
    return latestOutcome ? this.labelize(latestOutcome) : 'No outcome saved';
  }

  get savedNotes(): CallSessionData[] {
    return this.callHistory.filter((item) => (item.note || '').trim());
  }

  get latestSavedNote(): CallSessionData | undefined {
    return this.savedNotes[0];
  }

  get noteCharactersRemaining(): number {
    return this.maxNoteLength - (this.noteText || '').length;
  }

  get canSaveNote(): boolean {
    return !!this.session?.id && !this.savingNote && (!!this.noteText.trim() || !!this.selectedOutcome);
  }

  get canCloseTracker(): boolean {
    return !this.hasActiveCall;
  }

  get canStartCandidateCall(): boolean {
    return !this.startingCandidateCall && !this.hasActiveCall && this.candidatePhoneLabel !== 'Candidate phone unavailable';
  }

  close(): void {
    if (!this.canCloseTracker) {
      return;
    }
    this.dialogRef.close({ action: 'closed' });
  }

  selectOutcome(outcome: OutcomeKey): void {
    this.selectedOutcome = this.selectedOutcome === outcome ? '' : outcome;
    this.noteMessage = '';
  }

  saveNote(): void {
    if (!this.canSaveNote || !this.session?.id) {
      return;
    }
    this.savingNote = true;
    this.noteMessage = '';
    this.http.post<{ Success: boolean; Error?: string | null; Data?: CallSessionData }>(
      `${this.getApiBaseUrl()}/candidate-profile-data/${this.data.interviewId}/call-session/${this.session.id}/note/`,
      {
        note: this.noteText.trim(),
        outcome: this.selectedOutcome,
      }
    ).pipe(
      catchError((error) => {
        this.savingNote = false;
        this.noteMessage = error?.error?.Error || 'Unable to save this call note right now.';
        return of({ Success: false, Error: this.noteMessage, Data: undefined as CallSessionData | undefined });
      })
    ).subscribe((response) => {
      this.savingNote = false;
      if (!response?.Success || !response.Data) {
        this.noteMessage = response?.Error || 'Unable to save this call note right now.';
        return;
      }
      this.applySession(response.Data, false);
      this.noteMessage = 'Call note saved.';
      this.fetchCallHistory();
    });
  }

  startCandidateCall(): void {
    if (!this.canStartCandidateCall) {
      return;
    }

    this.startingCandidateCall = true;
    this.errorMessage = '';
    this.noteMessage = '';
    this.http.post<CandidateCallResponse>(
      `${this.getApiBaseUrl()}/candidate-profile-data/${this.data.interviewId}/call/`,
      {}
    ).pipe(
      catchError((error) => {
        this.startingCandidateCall = false;
        this.errorMessage = error?.error?.Error || 'Unable to connect the Exotel call right now.';
        return of({ Success: false, Error: this.errorMessage } as CandidateCallResponse);
      })
    ).subscribe((response) => {
      this.startingCandidateCall = false;
      if (!response?.Success || !response.Data?.session) {
        this.errorMessage = response?.Error || 'Unable to connect the Exotel call right now.';
        return;
      }
      this.applySession(response.Data.session);
      this.errorMessage = '';
      this.fetchCallHistory();
      this.startPolling();
    });
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
      this.fetchCallHistory();
    });
  }

  trackSession = (_index: number, item: CallSessionData): number => item.id;

  fetchSession(): void {
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
        this.fetchCallHistory();
      }
    });
  }

  private fetchCallHistory(): void {
    this.historyLoading = true;
    this.http.get<CallHistoryResponse>(
      `${this.getApiBaseUrl()}/candidate-profile-data/${this.data.interviewId}/call-sessions/`
    ).pipe(
      catchError((error) => {
        this.historyLoading = false;
        this.errorMessage = error?.error?.Error || 'Unable to load call history.';
        return of({ Success: false, Error: this.errorMessage, Data: undefined });
      })
    ).subscribe((response) => {
      this.historyLoading = false;
      if (!response?.Success) {
        this.errorMessage = response?.Error || 'Unable to load call history.';
        return;
      }
      if (response.Data?.candidate) {
        this.candidate = { ...this.candidate, ...response.Data.candidate };
      }
      this.callHistory = response.Data?.sessions || [];
      const current = this.session?.id
        ? this.callHistory.find((item) => item.id === this.session?.id)
        : undefined;
      if (current) {
        this.applySession(current, false);
      }
    });
  }

  private startPolling(): void {
    this.stopPolling();
    if (this.session?.id && !this.isTerminal) {
      this.pollTimer = window.setInterval(() => this.fetchSession(), 3000);
    }
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

  private applySession(session: CallSessionData, syncNoteForm = true): void {
    this.session = session;
    this.displayBillableSeconds = Math.max(this.displayBillableSeconds, Math.max(0, session.billable_seconds || 0));
    this.displayConnectedSeconds = Math.max(this.displayConnectedSeconds, Math.max(0, session.connected_seconds || 0));
    if (syncNoteForm) {
      this.noteText = (session.note || '').slice(0, this.maxNoteLength);
      this.selectedOutcome = this.isOutcome(session.outcome) ? session.outcome : '';
    }
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

  getConnectedSeconds(item: CallSessionData): number {
    if (item.id === this.session?.id) {
      return this.displayConnectedSeconds;
    }
    return Math.max(0, item.connected_seconds || this.deriveRangeSeconds(item.candidate_connected_at, item.ended_at));
  }

  wasConnected(item: CallSessionData): boolean {
    return this.getConnectedSeconds(item) > 0 || !!item.candidate_connected_at;
  }

  formatDuration(totalSeconds: number): string {
    const seconds = Math.max(0, Math.floor(totalSeconds || 0));
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const remainder = seconds % 60;
    if (hours > 0) {
      return `${hours}:${minutes.toString().padStart(2, '0')}:${remainder.toString().padStart(2, '0')}`;
    }
    return `${minutes.toString().padStart(2, '0')}:${remainder.toString().padStart(2, '0')}`;
  }

  formatDateTime(rawValue: string): string {
    if (!rawValue) return 'No calls recorded';
    const date = new Date(rawValue);
    if (Number.isNaN(date.getTime())) return 'Date unavailable';
    return new Intl.DateTimeFormat(undefined, {
      month: 'short',
      day: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    }).format(date);
  }

  labelize(value: string): string {
    return (value || '').replace(/_/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
  }

  private isOutcome(value: string | undefined): value is OutcomeKey {
    return ['connected', 'no_answer', 'busy', 'wrong_number', 'not_reachable'].includes(value || '');
  }

  private getApiBaseUrl(): string {
    let port = '';
    if (window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost') {
      port = '8080';
    }
    return `${window.location.protocol}//${window.location.hostname}:${port}`;
  }
}
