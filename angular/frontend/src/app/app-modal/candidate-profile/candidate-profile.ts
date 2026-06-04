import { Component, Inject, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { MAT_DIALOG_DATA, MatDialog, MatDialogRef } from '@angular/material/dialog';
import { catchError, of } from 'rxjs';
import { AppToastService } from '../../core/app-toast.service';
import { CandidateCallTracker } from '../candidate-call-tracker/candidate-call-tracker';

interface CandidateData {
  id: number;
  name: string;
  email: string;
  recruiter: string;
  interviewer?: string;
  role: string;
  role_id?: number | null;
  status: string;
  score?: number | null;
  date: string;
  phone?: string;
  candidate_phone_masked?: string;
  profile_picture?: string;
  public_resume_downloads?: number;
  can_call_candidate?: boolean;
}

interface ResumeSection {
  section_key: string;
  title: string;
  section_type: string;
  display_order: number;
  content: {
    text?: string;
    items?: Array<string | Record<string, unknown>>;
  };
  raw_text: string;
}

interface ResumeSectionView {
  section: ResumeSection;
  objectItems: Array<{
    item: Record<string, unknown>;
    primary: string;
    secondary: string[];
    inlineText: string;
  }>;
  textItems: string[];
  paragraphText: string;
}

interface ResumeData {
  available: boolean;
  status: string;
  error_message: string;
  headline: string;
  summary: string;
  candidate_type: string;
  contact: {
    email?: string;
    phone?: string;
    location?: string;
  };
  skills: string[];
  sections: ResumeSection[];
  file_url?: string;
  processed_at?: string;
  source_file?: string;
  parser_provider?: string;
  parser_version?: string;
  raw_text_preview?: string;
  ai_configured?: boolean;
  ai_attempted?: boolean;
  ai_model?: string;
  ai_error?: string;
  ai_raw_preview?: string;
  fallback_used?: boolean;
  fallback_provider?: string;
}

interface CandidateProfileResponse {
  Success: boolean;
  Error?: string | null;
  Data?: {
    candidate?: CandidateData;
    verification?: VerificationData;
    insights?: InsightData;
    resume?: ResumeData;
  };
}

interface CandidateCallResponse {
  Success: boolean;
  Error?: string | null;
  Data?: {
    call_sid?: string;
    caller_phone_masked?: string;
    candidate_phone_masked?: string;
    session?: {
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
    };
  };
}

interface VerificationData {
  phone_verified: boolean;
  email_verified: boolean;
  identity_verified: boolean;
  phone_verified_at?: string;
  email_verified_at?: string;
  identity_verified_at?: string;
  identity_status?: string;
}

interface InsightData {
  status: string;
  loading: boolean;
  available: boolean;
  executive_summary?: string;
  resume_score?: number | null;
  current_skills_impact_score?: number | null;
  current_skills_impact_summary?: string;
}

@Component({
  selector: 'app-candidate-profile',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './candidate-profile.html',
  styleUrl: './candidate-profile.scss',
})
export class CandidateProfile implements OnInit {
  private readonly toast = inject(AppToastService);
  candidate: CandidateData;
  loading = false;
  resumeLoading = false;
  reprocessingResume = false;
  errorMessage = '';
  statusActions: Array<{ key: string; label: string }> = [];
  verification: VerificationData = {
    phone_verified: false,
    email_verified: false,
    identity_verified: false,
    phone_verified_at: '',
    email_verified_at: '',
    identity_verified_at: '',
    identity_status: 'not_started',
  };
  insights: InsightData = {
    status: 'not_started',
    loading: false,
    available: false,
    executive_summary: '',
    resume_score: null,
    current_skills_impact_score: null,
    current_skills_impact_summary: '',
  };
  resumeData: ResumeData = {
    available: false,
    status: 'missing',
    error_message: '',
    headline: '',
    summary: '',
    candidate_type: '',
    contact: {},
    skills: [],
    sections: [],
    parser_provider: '',
    parser_version: '',
    raw_text_preview: '',
    ai_configured: false,
    ai_attempted: false,
    ai_model: '',
    ai_error: '',
    ai_raw_preview: '',
    fallback_used: false,
    fallback_provider: '',
  };
  displaySectionViews: ResumeSectionView[] = [];
  skillTags: string[] = [];
  verificationViewItems: Array<{ label: string; verified: boolean; date?: string }> = [];
  callingCandidate = false;

  constructor(
    private http: HttpClient,
    private dialog: MatDialog,
    public dialogRef: MatDialogRef<CandidateProfile>,
    @Inject(MAT_DIALOG_DATA) public data: { candidate: CandidateData }
  ) {
    this.candidate = { ...data.candidate };
    this.statusActions = this.getStatusActions(this.candidate.status);
  }

  ngOnInit(): void {
    this.loadCandidateProfile();
  }

  get initials(): string {
    const parts = (this.candidate?.name || '').trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return 'NA';
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
  }

  get formattedStatus(): string {
    return this.candidate.status.replace(/_/g, ' ').replace(/\b\w/g, (m) => m.toUpperCase());
  }

  get resumeSubline(): string {
    const phone = this.resumeData.contact?.phone || this.candidate.phone || 'Phone unavailable';
    const location = this.resumeData.contact?.location || 'Location unavailable';
    return `${phone} | ${location}`;
  }

  get headline(): string {
    return this.resumeData.headline || 'Resume profile';
  }

  get canCallCandidate(): boolean {
    return !!this.candidate?.can_call_candidate && !!(this.candidate?.phone || '').trim();
  }

  get resumeStatusLabel(): string {
    const status = this.resumeData.status || 'missing';
    return status.replace(/_/g, ' ').replace(/\b\w/g, (m) => m.toUpperCase());
  }

  get resumeStatusClass(): string {
    const status = this.resumeData.status || 'missing';
    if (status === 'completed') return 'resume-pill resume-pill--success';
    if (status === 'failed') return 'resume-pill resume-pill--error';
    return 'resume-pill';
  }

  get verificationItems(): Array<{ label: string; verified: boolean; date?: string }> {
    return this.verificationViewItems;
  }

  get summarySection(): string {
    return this.resumeData.summary || this.getSectionText('summary') || this.getSectionText('objective');
  }

  get initialProfileLoading(): boolean {
    return this.resumeLoading && !this.resumeData.available && !this.resumeData.error_message && !this.displaySectionViews.length;
  }

  get readinessInsightScore(): string {
    return this.insights.resume_score != null ? `${this.insights.resume_score}` : '--';
  }

  get skillsImpactScore(): string {
    return this.insights.current_skills_impact_score != null ? `${this.insights.current_skills_impact_score}` : '--';
  }

  get readinessInsightSummary(): string {
    return this.insights.executive_summary || 'AI readiness insight will appear here once the candidate snapshot is generated.';
  }

  get skillsImpactSummary(): string {
    return this.insights.current_skills_impact_summary || 'Skill impact insight will appear here once the AI snapshot is generated.';
  }

  get skillList(): string[] {
    return this.skillTags;
  }

  get displaySections(): ResumeSection[] {
    return (this.resumeData.sections || []).filter((section) => !['summary', 'objective', 'skills', 'contact'].includes(section.section_key));
  }

  formatRoleWithId(role: string, roleId?: number | null): string {
    const roleName = (role || '').toString().trim();
    const id = (roleId ?? '').toString().trim();
    if (!roleName) return id;
    return id ? `${roleName} - ${id}` : roleName;
  }

  close(): void {
    this.dialogRef.close(null);
  }

  openRole(): void {
    this.dialogRef.close({ action: 'openRole', candidate: this.candidate });
  }

  openOriginalResume(): void {
    if (!this.resumeData.file_url) {
      return;
    }
    window.open(this.resumeData.file_url, '_blank', 'noopener');
  }

  callCandidate(): void {
    if (this.callingCandidate || !this.canCallCandidate) {
      if (!this.canCallCandidate) {
        this.toast.showError('Call unavailable', 'Candidate phone number is not available for calling.');
      }
      return;
    }

    this.callingCandidate = true;
    const apiBaseUrl = this.getApiBaseUrl();
    this.http.post<CandidateCallResponse>(
      `${apiBaseUrl}/candidate-profile-data/${this.candidate.id}/call/`,
      {}
    )
      .pipe(
        catchError((error) => {
          console.error('Error starting candidate call', error);
          this.callingCandidate = false;
          this.toast.showError('Call failed', 'Unable to connect the Exotel call right now.');
          return of({ Success: false, Error: 'Request failed' } as CandidateCallResponse);
        })
      )
      .subscribe((response) => {
        this.callingCandidate = false;
        if (!response?.Success) {
          this.toast.showError('Call failed', response?.Error || 'Unable to connect the Exotel call right now.');
          return;
        }
        const callerPhone = response.Data?.caller_phone_masked || 'your registered number';
        const candidatePhone = response.Data?.candidate_phone_masked || this.candidate.candidate_phone_masked || 'the candidate number';
        const session = response.Data?.session;
        if (!session) {
          this.toast.showSuccess('Calling candidate', `Connecting ${callerPhone} with ${candidatePhone} via Exotel.`);
          return;
        }
        this.dialog.open(CandidateCallTracker, {
          disableClose: true,
          width: 'min(460px, 92vw)',
          maxWidth: '92vw',
          panelClass: 'candidate-call-tracker-dialog',
          autoFocus: false,
          data: {
            interviewId: this.candidate.id,
            session,
          },
        });
      });
  }

  reprocessResume(): void {
    this.reprocessingResume = true;
    this.resumeData = { ...this.resumeData, error_message: '' };
    const apiBaseUrl = this.getApiBaseUrl();
    this.http.post<{ Success: boolean; Error?: string | null }>(`${apiBaseUrl}/candidate-profile-data/${this.candidate.id}/reprocess/`, {})
      .pipe(
        catchError((error) => {
          console.error('Error reprocessing resume', error);
          this.reprocessingResume = false;
          this.resumeData = { ...this.resumeData, error_message: 'Unable to reprocess resume right now.' };
          this.toast.showError('Resume update failed', this.resumeData.error_message);
          return of({ Success: false, Error: 'Request failed' });
        })
      )
      .subscribe((response) => {
        this.reprocessingResume = false;
        if (!response?.Success) {
          this.resumeData = { ...this.resumeData, error_message: response?.Error || 'Unable to reprocess resume right now.' };
          this.toast.showError('Resume update failed', this.resumeData.error_message);
          return;
        }
        this.toast.showSuccess('Resume reprocessing started', `We are refreshing ${this.candidate.name}'s resume details.`);
        this.loadCandidateProfile();
      });
  }

  changeStatus(next: string): void {
    this.loading = true;
    this.errorMessage = '';
    const apiBaseUrl = this.getApiBaseUrl();
    const formData = new FormData();
    formData.append('candidateId', String(this.candidate.id));
    formData.append('newStatus', next);

    this.http.post<{ Success: boolean; Error?: string; Data?: { status?: string; date?: string } }>(`${apiBaseUrl}/update-candidate-status/`, formData)
      .pipe(
        catchError((error) => {
          console.error('Error updating candidate status', error);
          this.loading = false;
          this.errorMessage = 'Unable to update status. Please try again.';
          this.toast.showError('Status update failed', this.errorMessage);
          return of({ Success: false, Error: 'Request failed', Data: {} });
        })
      )
      .subscribe((response: any) => {
        if (!response?.Success) {
          this.errorMessage = response?.Error || 'Unable to update status.';
          this.loading = false;
          this.toast.showError('Status update failed', this.errorMessage);
          return;
        }

        this.candidate.status = response?.Data?.status || next;
        if (response?.Data?.date) {
          this.candidate.date = response.Data.date;
        }
        this.statusActions = this.getStatusActions(this.candidate.status);
        this.loading = false;
        window.dispatchEvent(new CustomEvent('candidate-status-updated', {
          detail: {
            candidateId: this.candidate.id,
            status: this.candidate.status,
            updatedAt: new Date().toISOString(),
          }
        }));
        const statusLabel = this.normalizeStatus(this.candidate.status).replace(/\b\w/g, (match) => match.toUpperCase());
        this.toast.showSuccess('Candidate updated', `${this.candidate.name} is now ${statusLabel}.`);
      });
  }

  saveAndClose(): void {
    window.dispatchEvent(new CustomEvent('global-data-refresh', {
      detail: {
        entity: 'candidate',
        action: 'save',
        candidateId: this.candidate?.id,
        updatedAt: new Date().toISOString(),
      }
    }));
    this.dialogRef.close({ action: 'updated', candidate: this.candidate });
  }

  getSectionText(sectionKey: string): string {
    const section = (this.resumeData.sections || []).find((item) => item.section_key === sectionKey);
    return section?.content?.text || section?.raw_text || '';
  }

  getStringItems(sectionKey: string): string[] {
    const section = (this.resumeData.sections || []).find((item) => item.section_key === sectionKey);
    const items = section?.content?.items || [];
    return items.filter((item): item is string => typeof item === 'string' && !!item.trim());
  }

  trackSection = (_index: number, item: ResumeSectionView): string =>
    `${item.section.section_key}-${item.section.display_order}`;

  trackString = (_index: number, item: string): string => item;

  trackObjectItem = (index: number, _item: { item: Record<string, unknown>; primary: string; secondary: string[] }): number => index;

  private getObjectPrimary(item: Record<string, unknown>): string {
    const preferred = ['title', 'degree', 'label', 'value'];
    for (const key of preferred) {
      const value = item[key];
      if (typeof value === 'string' && value.trim()) return value;
    }
    const first = Object.values(item).find((value) => typeof value === 'string' && value.trim());
    return typeof first === 'string' ? first : 'Entry';
  }

  private getObjectSecondary(item: Record<string, unknown>): string[] {
    const rows: string[] = [];
    Object.entries(item).forEach(([key, value]) => {
      if (key === 'title') return;
      if (Array.isArray(value) && value.length) {
        rows.push(`${this.labelize(key)}: ${value.join(', ')}`);
        return;
      }
      if (typeof value === 'string' && value.trim()) {
        rows.push(`${this.labelize(key)}: ${value}`);
      }
    });
    return rows;
  }

  private getInlineObjectText(item: Record<string, unknown>): string {
    const primary = this.getObjectPrimary(item);
    const preferredValue = item['value'];
    const normalizedValue = Array.isArray(preferredValue)
      ? preferredValue.map((value) => `${value ?? ''}`.trim()).filter(Boolean).join(', ')
      : typeof preferredValue === 'string'
        ? preferredValue.trim()
        : '';

    if (primary && normalizedValue && normalizedValue.toLowerCase() !== primary.toLowerCase()) {
      return `${primary}: ${normalizedValue}`;
    }
    if (normalizedValue) {
      return normalizedValue;
    }

    const secondary = this.getObjectSecondary(item)
      .map((value) => value.replace(/^[^:]+:\s*/, '').trim())
      .filter(Boolean);
    if (primary && secondary.length) {
      return `${primary}: ${secondary.join(', ')}`;
    }
    return primary;
  }

  private loadCandidateProfile(): void {
    this.resumeLoading = true;
    const apiBaseUrl = this.getApiBaseUrl();
    this.http.get<CandidateProfileResponse>(`${apiBaseUrl}/candidate-profile-data/${this.candidate.id}/`)
      .pipe(
        catchError((error) => {
          console.error('Error loading candidate profile', error);
          this.resumeLoading = false;
          this.resumeData = { ...this.resumeData, error_message: 'Unable to load parsed resume data.' };
          return of({ Success: false, Error: 'Request failed', Data: {} } as CandidateProfileResponse);
        })
      )
      .subscribe((response) => {
        this.resumeLoading = false;
        if (!response?.Success) {
          this.resumeData = { ...this.resumeData, error_message: response?.Error || 'Unable to load parsed resume data.' };
          return;
        }
        if (response.Data?.candidate) {
          this.candidate = { ...this.candidate, ...response.Data.candidate };
          this.statusActions = this.getStatusActions(this.candidate.status);
        }
        if (response.Data?.verification) {
          this.verification = { ...this.verification, ...response.Data.verification };
          this.verificationViewItems = this.buildVerificationItems();
        }
        if (response.Data?.insights) {
          this.insights = { ...this.insights, ...response.Data.insights };
        }
        if (response.Data?.resume) {
          this.resumeData = response.Data.resume;
          this.skillTags = this.buildSkillTags();
          this.displaySectionViews = this.buildDisplaySectionViews(this.resumeData.sections || []);
        }
      });
  }

  private buildVerificationItems(): Array<{ label: string; verified: boolean; date?: string }> {
    return [
      {
        label: 'Phone',
        verified: !!this.verification.phone_verified,
        date: this.verification.phone_verified_at,
      },
      {
        label: 'Email',
        verified: !!this.verification.email_verified,
        date: this.verification.email_verified_at,
      },
      {
        label: 'Aadhaar',
        verified: !!this.verification.identity_verified,
        date: this.verification.identity_verified_at,
      },
    ];
  }

  private buildSkillTags(): string[] {
    if (this.resumeData.skills?.length) {
      return this.resumeData.skills;
    }
    return this.getStringItems('skills');
  }

  private buildDisplaySectionViews(sections: ResumeSection[]): ResumeSectionView[] {
    return sections
      .filter((section) => !['summary', 'objective', 'skills', 'contact'].includes(section.section_key))
      .map((section) => {
        const items = section?.content?.items || [];
        const objectItems = items
          .filter((item): item is Record<string, unknown> => typeof item === 'object' && item !== null)
          .map((item) => ({
            item,
            primary: this.getObjectPrimary(item),
            secondary: this.getObjectSecondary(item),
            inlineText: this.getInlineObjectText(item),
          }));
        const textItems = items.filter((item): item is string => typeof item === 'string' && !!item.trim());
        return {
          section,
          objectItems,
          textItems,
          paragraphText: section.content.text || section.raw_text || 'No details available.',
        };
      });
  }

  private normalizeStatus(value: string): string {
    return (value || '')
      .toString()
      .trim()
      .toLowerCase()
      .replace(/_/g, ' ')
      .replace(/\s+/g, ' ')
      .replace(/assesment/g, 'assessment');
  }

  private getStatusActions(statusRaw: string): Array<{ key: string; label: string }> {
    const status = this.normalizeStatus(statusRaw);

    const transitions: Record<string, Array<{ key: string; label: string }>> = {
      'scheduled': [
        { key: 'shortlisted', label: 'Shortlist' },
        { key: 'rejected', label: 'Disqualify' },
        { key: 'cancelled', label: 'Cancel' }
      ],
      'shortlisted': [
        { key: 'offer_made', label: 'Send Offer' },
        { key: 'rejected', label: 'Disqualify' },
        { key: 'cancelled', label: 'Cancel' }
      ],
      'offer made': [
        { key: 'offer_accepted', label: 'Mark Offer Accepted' },
        { key: 'offer_declined', label: 'Mark Offer Declined' },
        { key: 'cancelled', label: 'Cancel' }
      ],
      'offer accepted': [
        { key: 'hired', label: 'Mark Hired' },
        { key: 'offer_declined', label: 'Mark Offer Declined' }
      ],
      'offer declined': [
        { key: 'offer_made', label: 'Re-open Offer' },
        { key: 'assessment_pending', label: 'Move Back to Assessment' }
      ],
      'assessment pending': [
        { key: 'scheduled', label: 'Move to Scheduled' },
        { key: 'rejected', label: 'Disqualify' },
        { key: 'cancelled', label: 'Cancel' }
      ],
      'assessment completed': [
        { key: 'scheduled', label: 'Move to Scheduled' },
        { key: 'shortlisted', label: 'Shortlist' },
        { key: 'rejected', label: 'Disqualify' }
      ],
      'auto screening scheduled': [
        { key: 'assessment_pending', label: 'Move to Assessment' },
        { key: 'rejected', label: 'Disqualify' }
      ],
      'rejected': [
        { key: 'assessment_pending', label: 'Reopen' }
      ],
      'cancelled': [
        { key: 'assessment_pending', label: 'Reopen' }
      ],
      'completed': [],
      'hired': []
    };

    return transitions[status] || [];
  }

  private getApiBaseUrl(): string {
    let portNumber = '';
    if (window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost') {
      portNumber = '8080';
    }
    return `${window.location.protocol}//${window.location.hostname}:${portNumber}`;
  }

  private labelize(key: string): string {
    return key.replace(/_/g, ' ').replace(/\b\w/g, (m) => m.toUpperCase());
  }
}
