import { Component, Inject, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { catchError, of } from 'rxjs';
import { AppToastService } from '../../core/app-toast.service';

type WorkflowActionMode = 'schedule' | 'bulk-assign' | 'evaluation-reviews';

interface WorkflowCandidate {
  id: number;
  candidate_id?: number;
  name: string;
  email?: string;
  phone?: string;
  recruiter?: string;
  recruiter_id?: number | null;
  interviewer?: string;
  interviewer_id?: number | null;
  interview_type?: 'manual' | 'auto' | string;
  status: string;
  score?: number | null;
  notes?: string;
  date?: string;
  role?: string;
  role_id?: number | null;
}

interface EvaluatorOption {
  id: number;
  user_id: number;
  name: string;
  email?: string;
  phone?: string;
  recruiter_id?: number | null;
  recruiter_name?: string;
}

interface ReviewGroup {
  key: 'needs-decision' | 'shortlisted' | 'closed';
  title: string;
  helper: string;
  items: ReviewCandidateView[];
}

interface ReviewDecisionAction {
  key: 'offer_made' | 'offer_accepted' | 'offer_declined' | 'hired' | 'rejected';
  label: string;
  tone: 'primary' | 'secondary';
}

interface ReviewCandidateView extends WorkflowCandidate {
  statusLabel: string;
  evaluatorLabel: string;
  dateLabel: string;
  decisionActions: ReviewDecisionAction[];
  canScheduleFurther: boolean;
}

@Component({
  selector: 'app-workflow-action',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './workflow-action.html',
  styleUrl: './workflow-action.scss'
})
export class WorkflowAction {
  private readonly toast = inject(AppToastService);
  mode: WorkflowActionMode;
  candidates: WorkflowCandidate[] = [];
  reviewGroupsList: ReviewGroup[] = [];
  filteredReviewCandidatesList: ReviewCandidateView[] = [];
  activeReviewGroupKey: ReviewGroup['key'] | null = null;
  saving = false;
  loadingEvaluators = false;
  errorMessage = '';
  successMessage = '';

  candidateSearch = '';
  reviewSearch = '';
  candidateSearchOpen = false;

  selectedInterviewId: number | null = null;
  selectedEvaluatorId: number | null = null;
  selectedBulkIds = new Set<number>();
  scheduledDate = '';
  scheduledTime = '';
  interviewType: 'manual' | 'auto' = 'manual';
  evaluatorSearch = '';
  evaluatorSearchOpen = false;

  evaluatorOptions: EvaluatorOption[] = [];

  constructor(
    private http: HttpClient,
    public dialogRef: MatDialogRef<WorkflowAction>,
    @Inject(MAT_DIALOG_DATA) public data: { mode: WorkflowActionMode; candidates: WorkflowCandidate[]; preselectedCandidateId?: number | null }
  ) {
    this.mode = data?.mode || 'schedule';
    this.candidates = (data?.candidates || []).map((candidate) => ({ ...candidate }));
  }

  ngOnInit(): void {
    if (this.mode !== 'evaluation-reviews') {
      this.loadEvaluatorOptions();
    }
    if (this.mode === 'evaluation-reviews') {
      this.refreshReviewData();
    }
    if (this.mode === 'schedule' && this.data?.preselectedCandidateId) {
      const preselected = this.candidates.find((candidate) => candidate.id === this.data.preselectedCandidateId);
      if (preselected) {
        this.selectCandidate(preselected);
        return;
      }
    }
    if (this.mode === 'schedule' && this.scheduleCandidates.length === 1) {
      this.selectCandidate(this.scheduleCandidates[0]);
    }
  }

  get title(): string {
    if (this.mode === 'schedule') return 'Schedule Interview';
    if (this.mode === 'bulk-assign') return 'Bulk Assign Evaluator';
    return 'Evaluation Reviews';
  }

  get subtitle(): string {
    if (this.mode === 'schedule') {
      return 'Configure the interview mode, assign ownership where required, and confirm a scheduled slot for the selected candidate.';
    }
    if (this.mode === 'bulk-assign') {
      return 'Assign an evaluator across multiple candidates in one controlled workflow update.';
    }
    return 'Review completed evaluations, scores, and interviewer notes from the current dashboard scope.';
  }

  get scheduleCandidates(): WorkflowCandidate[] {
    return this.filterCandidates(this.candidates.filter((candidate) =>
      ['assessment pending', 'scheduled', 'assessment completed', 'cancelled'].includes(this.normalizeStatus(candidate.status))
    ));
  }

  get showScheduleCandidateResults(): boolean {
    return this.mode === 'schedule'
      && this.candidateSearchOpen
      && this.candidateSearch.trim().length >= 3
      && !this.selectedCandidate
      && this.scheduleCandidates.length > 0;
  }

  get showScheduleCandidateEmpty(): boolean {
    return this.mode === 'schedule'
      && this.candidateSearchOpen
      && this.candidateSearch.trim().length >= 3
      && !this.selectedCandidate
      && this.scheduleCandidates.length === 0;
  }

  get bulkAssignableCandidates(): WorkflowCandidate[] {
    return this.filterCandidates(this.candidates.filter((candidate) =>
      !['hired', 'rejected', 'cancelled'].includes(this.normalizeStatus(candidate.status))
    ));
  }

  get reviewCandidates(): ReviewCandidateView[] {
    return this.filteredReviewCandidatesList;
  }

  get reviewAverageScore(): string {
    const scores = this.filteredReviewCandidatesList
      .map((candidate) => candidate.score)
      .filter((score): score is number => score !== null && score !== undefined)
      .map((score) => Number(score))
      .filter((score) => Number.isFinite(score));
    if (!scores.length) return '--';
    return (scores.reduce((sum, score) => sum + score, 0) / scores.length).toFixed(1);
  }

  get reviewsMissingFeedback(): number {
    return this.filteredReviewCandidatesList.filter((candidate) => !candidate.notes || candidate.score === null || candidate.score === undefined).length;
  }

  get reviewGroups(): ReviewGroup[] {
    return this.reviewGroupsList;
  }

  get activeReviewGroup(): ReviewGroup | null {
    return this.reviewGroupsList.find((group) => group.key === this.activeReviewGroupKey) || this.reviewGroupsList[0] || null;
  }

  private buildReviewCandidates(): ReviewCandidateView[] {
    const term = this.reviewSearch.trim().toLowerCase();
    return this.candidates
      .filter((candidate) => {
        const normalized = this.normalizeStatus(candidate.status);
        return (
          normalized !== 'assessment pending' && (
            candidate.notes ||
            (candidate.score !== null && candidate.score !== undefined) ||
            ['completed', 'shortlisted', 'offer made', 'offer accepted', 'offer declined', 'hired', 'rejected'].includes(normalized)
          )
        );
      })
      .filter((candidate) => {
        if (!term) return true;
        return [
          candidate.name,
          candidate.role,
          candidate.recruiter,
          candidate.interviewer,
          candidate.status,
          candidate.notes,
          candidate.email,
        ]
          .map((value) => (value || '').toString().toLowerCase())
          .some((value) => value.includes(term));
      })
      .sort((left, right) => this.toTime(right.date) - this.toTime(left.date))
      .map((candidate) => {
        const normalized = this.normalizeStatus(candidate.status);
        return {
          ...candidate,
          statusLabel: this.formatStatus(candidate.status),
          evaluatorLabel: candidate.interviewer || 'Last evaluator unavailable',
          dateLabel: this.formatDate(candidate.date),
          decisionActions: this.buildReviewDecisionActions(normalized),
          canScheduleFurther: !['shortlisted', 'offer made', 'offer accepted', 'offer declined', 'hired', 'completed', 'rejected', 'cancelled'].includes(normalized),
        };
      });
  }

  private buildReviewGroups(reviewCandidates: ReviewCandidateView[]): ReviewGroup[] {
    const grouped: ReviewGroup[] = [
      {
        key: 'needs-decision',
        title: 'Open Decisions',
        helper: 'Completed evaluations awaiting a final recruiter or hiring decision.',
        items: [],
      },
      {
        key: 'shortlisted',
        title: 'Advanced',
        helper: 'Candidates approved to move forward into the next interview or selection stage.',
        items: [],
      },
      {
        key: 'closed',
        title: 'Closed Outcomes',
        helper: 'Evaluations already concluded with a final hiring or rejection outcome.',
        items: [],
      },
    ];

    for (const candidate of reviewCandidates) {
      const normalized = this.normalizeStatus(candidate.status);
      if (['shortlisted', 'offer made', 'offer accepted'].includes(normalized)) {
        grouped[1].items.push(candidate);
      } else if (normalized === 'hired' || normalized === 'completed' || normalized === 'rejected' || normalized === 'offer declined') {
        grouped[2].items.push(candidate);
      } else {
        grouped[0].items.push(candidate);
      }
    }

    return grouped.filter((group) => group.items.length > 0);
  }

  get selectedCandidate(): WorkflowCandidate | null {
    return this.candidates.find((candidate) => candidate.id === this.selectedInterviewId) || null;
  }

  get selectedBulkCount(): number {
    return this.selectedBulkIds.size;
  }

  get allVisibleBulkSelected(): boolean {
    return !!this.bulkAssignableCandidates.length && this.bulkAssignableCandidates.every((candidate) => this.selectedBulkIds.has(candidate.id));
  }

  get canSubmitSchedule(): boolean {
    if (!this.selectedInterviewId || !this.scheduledDate || !this.scheduledTime || this.saving) {
      return false;
    }
    if (this.interviewType === 'manual') {
      return !!this.selectedEvaluatorId;
    }
    return true;
  }

  get filteredScheduleEvaluators(): EvaluatorOption[] {
    const term = this.evaluatorSearch.trim().toLowerCase();
    if (term.length < 3) {
      return [];
    }
    return this.evaluatorOptions.filter((item) =>
      [
        item.name,
        item.email,
        item.phone,
        item.recruiter_name,
      ]
        .map((value) => (value || '').toString().toLowerCase())
        .some((value) => value.includes(term))
    );
  }

  get showEvaluatorResults(): boolean {
    return this.evaluatorSearchOpen && this.evaluatorSearch.trim().length >= 3 && this.filteredScheduleEvaluators.length > 0;
  }

  get showEvaluatorEmpty(): boolean {
    return this.evaluatorSearchOpen && this.evaluatorSearch.trim().length >= 3 && this.filteredScheduleEvaluators.length === 0;
  }

  get canSubmitBulkAssign(): boolean {
    return !!(this.selectedBulkIds.size && this.selectedEvaluatorId && !this.saving);
  }

  close(result: any = null): void {
    this.dialogRef.close(result);
  }

  get evaluatorFieldMessage(): string {
    if (this.loadingEvaluators) {
      return 'Loading evaluator options...';
    }
    if (this.errorMessage) {
      return '';
    }
    if (!this.evaluatorOptions.length) {
      return 'No evaluator options are available right now.';
    }
    return `${this.evaluatorOptions.length} evaluator${this.evaluatorOptions.length === 1 ? '' : 's'} available.`;
  }

  loadEvaluatorOptions(): void {
    this.loadingEvaluators = true;
    this.errorMessage = '';
    this.http.get<any>(`${this.getApiBaseUrl()}/workflow-evaluator-options/`)
      .pipe(
        catchError((error) => {
          console.error('Error loading evaluator options', error);
          this.loadingEvaluators = false;
          this.errorMessage = 'Unable to load evaluator options right now.';
          return of(null);
        })
      )
      .subscribe((response) => {
        this.loadingEvaluators = false;
        if (!response?.Success) {
          if (response?.Error) {
            this.errorMessage = response.Error;
          }
          return;
        }
        this.evaluatorOptions = response.EvaluatorData || [];
      });
  }

  selectCandidate(candidate: WorkflowCandidate): void {
    this.selectedInterviewId = candidate.id;
    this.errorMessage = '';
    this.candidateSearch = candidate.name;
    this.candidateSearchOpen = false;
    this.interviewType = candidate.interview_type === 'auto' ? 'auto' : 'manual';
    this.selectedEvaluatorId = candidate.interviewer_id || null;
    this.evaluatorSearch = candidate.interviewer || '';
    this.evaluatorSearchOpen = false;
    if (candidate.date) {
      const local = this.toLocalDateFields(candidate.date);
      this.scheduledDate = local.date;
      this.scheduledTime = local.time;
      return;
    }
    this.scheduledDate = '';
    this.scheduledTime = '';
  }

  resetSelectedCandidate(): void {
    this.selectedInterviewId = null;
    this.candidateSearch = '';
    this.candidateSearchOpen = false;
    this.interviewType = 'manual';
    this.selectedEvaluatorId = null;
    this.evaluatorSearch = '';
    this.evaluatorSearchOpen = false;
    this.scheduledDate = '';
    this.scheduledTime = '';
    this.errorMessage = '';
  }

  openCandidateSearch(): void {
    if (this.mode !== 'schedule' || this.selectedCandidate) {
      return;
    }
    this.candidateSearchOpen = true;
  }

  closeCandidateSearch(): void {
    window.setTimeout(() => {
      this.candidateSearchOpen = false;
      if (this.selectedCandidate) {
        this.candidateSearch = this.selectedCandidate.name;
      }
    }, 120);
  }

  onCandidateSearchChange(value: string): void {
    this.candidateSearch = value;
    this.candidateSearchOpen = true;
  }

  onReviewSearchChange(value: string): void {
    this.reviewSearch = value;
    this.refreshReviewData();
  }

  setActiveReviewGroup(key: ReviewGroup['key']): void {
    this.activeReviewGroupKey = key;
  }

  setInterviewType(type: 'manual' | 'auto'): void {
    this.interviewType = type;
    this.errorMessage = '';
    if (type === 'auto') {
      this.selectedEvaluatorId = null;
      this.evaluatorSearch = '';
      this.evaluatorSearchOpen = false;
      return;
    }
    const currentName = this.filteredScheduleEvaluators.find((item) => item.id === this.selectedEvaluatorId)?.name;
    this.evaluatorSearch = currentName || this.selectedCandidate?.interviewer || '';
  }

  openEvaluatorSearch(): void {
    if (this.interviewType !== 'manual' || this.loadingEvaluators) {
      return;
    }
    this.evaluatorSearchOpen = true;
  }

  closeEvaluatorSearch(): void {
    window.setTimeout(() => {
      this.evaluatorSearchOpen = false;
      const selected = this.filteredScheduleEvaluators.find((item) => item.id === this.selectedEvaluatorId)
        || this.evaluatorOptions.find((item) => item.id === this.selectedEvaluatorId);
      this.evaluatorSearch = selected?.name || '';
    }, 120);
  }

  onEvaluatorSearchChange(): void {
    this.selectedEvaluatorId = null;
    this.evaluatorSearchOpen = true;
  }

  selectEvaluator(option: EvaluatorOption): void {
    this.selectedEvaluatorId = option.id;
    this.evaluatorSearch = option.name;
    this.evaluatorSearchOpen = false;
    this.errorMessage = '';
  }

  toggleBulkCandidate(candidateId: number): void {
    if (this.selectedBulkIds.has(candidateId)) {
      this.selectedBulkIds.delete(candidateId);
    } else {
      this.selectedBulkIds.add(candidateId);
    }
  }

  toggleSelectAllBulkCandidates(): void {
    const visibleIds = this.bulkAssignableCandidates.map((candidate) => candidate.id);
    const allSelected = visibleIds.length && visibleIds.every((id) => this.selectedBulkIds.has(id));
    if (allSelected) {
      visibleIds.forEach((id) => this.selectedBulkIds.delete(id));
      return;
    }
    visibleIds.forEach((id) => this.selectedBulkIds.add(id));
  }

  isBulkCandidateSelected(candidateId: number): boolean {
    return this.selectedBulkIds.has(candidateId);
  }

  saveSchedule(): void {
    if (!this.canSubmitSchedule) {
      this.errorMessage = this.interviewType === 'manual'
        ? 'Select candidate, interview type, evaluator, and a confirmed interview time.'
        : 'Select candidate, interview type, and a confirmed interview time.';
      return;
    }
    this.submitWorkflowUpdate({
      mode: 'schedule',
      interview_ids: [this.selectedInterviewId],
      interviewer_id: this.selectedEvaluatorId,
      interview_type: this.interviewType,
      scheduled_at: this.combineDateTime(),
    });
  }

  saveBulkAssign(): void {
    if (!this.canSubmitBulkAssign) {
      this.errorMessage = 'Select at least one candidate and an evaluator.';
      return;
    }
    this.submitWorkflowUpdate({
      mode: 'bulk-assign',
      interview_ids: Array.from(this.selectedBulkIds),
      interviewer_id: this.selectedEvaluatorId,
    });
  }

  openCandidateProfile(candidate: WorkflowCandidate): void {
    this.close({ action: 'openProfile', candidate });
  }

  openEvaluationSummary(candidate: WorkflowCandidate): void {
    this.close({ action: 'openEvaluationSummary', candidate });
  }

  scheduleFurtherInterview(candidate: WorkflowCandidate): void {
    this.close({ action: 'scheduleFurther', candidate });
  }

  private buildReviewDecisionActions(normalized: string): ReviewDecisionAction[] {
    if (normalized === 'shortlisted') {
      return [
        { key: 'offer_made', label: 'Send Offer', tone: 'primary' },
        { key: 'rejected', label: 'Reject', tone: 'secondary' },
      ];
    }
    if (normalized === 'offer made') {
      return [
        { key: 'offer_accepted', label: 'Mark Offer Accepted', tone: 'primary' },
        { key: 'offer_declined', label: 'Mark Offer Declined', tone: 'secondary' },
      ];
    }
    if (normalized === 'offer accepted') {
      return [
        { key: 'hired', label: 'Mark as Hired', tone: 'primary' },
      ];
    }
    return [];
  }

  updateReviewDecision(candidate: WorkflowCandidate, nextStatus: ReviewDecisionAction['key']): void {
    if (!candidate?.id || this.saving) {
      return;
    }

    this.saving = true;
    this.errorMessage = '';
    const body = new URLSearchParams();
    body.set('candidateId', String(candidate.id));
    body.set('newStatus', nextStatus);

    this.http.post<any>(`${this.getApiBaseUrl()}/update-candidate-status/`, body.toString(), {
      headers: new HttpHeaders({ 'Content-Type': 'application/x-www-form-urlencoded' })
    })
      .pipe(
        catchError((error) => {
          console.error('Error updating shortlisted decision', error);
          this.saving = false;
          this.errorMessage = error?.error?.Error || 'Unable to update candidate decision.';
          this.toast.showError('Decision update failed', this.errorMessage);
          return of(null);
        })
      )
      .subscribe((response) => {
        this.saving = false;
        if (!response?.Success) {
          this.errorMessage = response?.Error || 'Unable to update candidate decision.';
          this.toast.showError('Decision update failed', this.errorMessage);
          return;
        }

        const target = this.candidates.find((item) => item.id === candidate.id);
        if (target) {
          target.status = response?.Data?.status || nextStatus;
          if (response?.Data?.date) {
            target.date = response.Data.date;
          }
        }
        this.refreshReviewData();
        window.dispatchEvent(new CustomEvent('candidate-status-updated', {
          detail: {
            candidateId: candidate.id,
            status: target?.status || nextStatus,
            updatedAt: new Date().toISOString(),
          }
        }));
        const candidateName = candidate.name || 'Candidate';
        const statusLabel = this.formatStatus(target?.status || nextStatus);
        this.toast.showSuccess('Decision updated', `${candidateName} is now marked as ${statusLabel}.`);
      });
  }

  private refreshReviewData(): void {
    this.filteredReviewCandidatesList = this.buildReviewCandidates();
    this.reviewGroupsList = this.buildReviewGroups(this.filteredReviewCandidatesList);
    if (!this.reviewGroupsList.length) {
      this.activeReviewGroupKey = null;
      return;
    }
    const hasActiveGroup = this.reviewGroupsList.some((group) => group.key === this.activeReviewGroupKey);
    if (!hasActiveGroup) {
      this.activeReviewGroupKey = this.reviewGroupsList[0].key;
    }
  }

  formatStatus(value: string): string {
    return this.normalizeStatus(value).replace(/_/g, ' ').replace(/\b\w/g, (match) => match.toUpperCase());
  }

  formatDate(value?: string): string {
    if (!value) return 'Not scheduled';
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return 'Not scheduled';
    return parsed.toLocaleString();
  }

  trackCandidate(_: number, candidate: WorkflowCandidate): number {
    return candidate.id;
  }

  trackEvaluator(_: number, evaluator: EvaluatorOption): number {
    return evaluator.id;
  }

  private filterCandidates(source: WorkflowCandidate[]): WorkflowCandidate[] {
    const term = this.candidateSearch.trim().toLowerCase();
    if (term.length < 3) return [];
    return source.filter((candidate) =>
      [
        candidate.name,
        candidate.email,
        candidate.phone,
        candidate.role,
        candidate.role_id,
        candidate.recruiter,
        candidate.interviewer,
        candidate.status,
        candidate.candidate_id,
      ]
        .map((value) => (value || '').toString().toLowerCase())
        .some((value) => value.includes(term))
    );
  }

  private submitWorkflowUpdate(payload: Record<string, unknown>): void {
    this.saving = true;
    this.errorMessage = '';
    this.successMessage = '';

    this.http.post<any>(`${this.getApiBaseUrl()}/update-interview-workflow/`, payload)
      .pipe(
        catchError((error) => {
          console.error('Error updating workflow action', error);
          this.saving = false;
          this.errorMessage = error?.error?.Error || 'Unable to complete the workflow update.';
          this.toast.showError('Workflow update failed', this.errorMessage);
          return of(null);
        })
      )
      .subscribe((response) => {
        this.saving = false;
        if (!response?.Success) {
          this.errorMessage = response?.Error || 'Unable to complete the workflow update.';
          this.toast.showError('Workflow update failed', this.errorMessage);
          return;
        }
        const updatedCount = response?.Data?.updated_count || 0;
        const notificationResults = response?.Data?.notifications || [];
        const notificationQueued = notificationResults.some((item: any) => !!item?.result?.queued);
        const notificationSent = notificationResults.some((item: any) => !!item?.result?.sent);
        const successMessage = this.mode === 'schedule'
          ? `Interview scheduled${notificationQueued ? ' and follow-up notifications queued' : (notificationSent ? ' and candidate notification sent' : '')}.`
          : `${updatedCount} candidate record${updatedCount === 1 ? '' : 's'} updated successfully.`;
        this.successMessage = successMessage;
        this.toast.showSuccess(this.mode === 'schedule' ? 'Interview scheduled' : 'Workflow updated', successMessage);
        this.close({ action: 'refresh', message: successMessage });
      });
  }

  private getApiBaseUrl(): string {
    let port = '';
    if (window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost') {
      port = '8000';
    }
    return `${window.location.protocol}//${window.location.hostname}:${port}`;
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

  private combineDateTime(): string {
    return `${this.scheduledDate}T${this.scheduledTime}`;
  }

  private toLocalDateFields(value: string): { date: string; time: string } {
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
      return { date: '', time: '' };
    }
    const year = parsed.getFullYear();
    const month = `${parsed.getMonth() + 1}`.padStart(2, '0');
    const day = `${parsed.getDate()}`.padStart(2, '0');
    const hours = `${parsed.getHours()}`.padStart(2, '0');
    const minutes = `${parsed.getMinutes()}`.padStart(2, '0');
    return {
      date: `${year}-${month}-${day}`,
      time: `${hours}:${minutes}`,
    };
  }

  private toTime(value?: string): number {
    if (!value) return 0;
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? 0 : parsed.getTime();
  }
}
