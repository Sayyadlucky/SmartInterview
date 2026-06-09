import { Component, Inject, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { catchError, of } from 'rxjs';
import { AppToastService } from '../../core/app-toast.service';

type WorkflowActionMode = 'schedule' | 'bulk-assign' | 'bulk-aptitude' | 'bulk-interview' | 'evaluation-reviews';
type ReviewFilterKey = 'all' | 'pending' | 'completed' | 'needs-decision' | 'overdue';

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
  profile_picture_url?: string;
  candidate_profile_picture_url?: string;
  candidate_action_link_type?: string;
  aptitude_assignment_id?: number | null;
  aptitude_status?: string;
}

interface WorkflowRoleOption {
  id: number;
  label: string;
  helper: string;
  total: number;
  eligible: number;
  scheduled: number;
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

interface AptitudeTemplateOption {
  id: number;
  title: string;
  role_type: string;
  role_family: string;
  duration_minutes: number;
  total_questions: number;
  readiness?: {
    ready: boolean;
    message?: string;
  };
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
  updatedShortLabel: string;
  initials: string;
  profilePhotoUrl: string;
  scoreLabel: string;
  scorePercent: number;
  scoreColor: string;
  statusTone: 'success' | 'warning' | 'danger' | 'info';
  decisionLabel: string;
  decisionTone: 'success' | 'warning' | 'danger' | 'info';
  qaCountLabel: string;
  behaviorStatusLabel: string;
  decisionActions: ReviewDecisionAction[];
  canScheduleFurther: boolean;
}

interface ReviewSummaryCard {
  key: string;
  label: string;
  value: number | string;
  helper: string;
  icon: string;
  tone: 'pending' | 'completed' | 'decision' | 'overdue';
}

interface ReviewFilterTab {
  key: ReviewFilterKey;
  label: string;
  count: number;
}

interface AvailabilityInsight {
  date: string;
  time: string;
  dateLabel: string;
  timeLabel: string;
  windowLabel: string;
  helper: string;
  conflictCount: number;
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
  reviewCandidatesView: ReviewCandidateView[] = [];
  selectedReviewCandidateView: ReviewCandidateView | null = null;
  reviewFilterTabsList: ReviewFilterTab[] = [];
  reviewSummaryCardsList: ReviewSummaryCard[] = [];
  reviewAverageScoreText = '--';
  activeReviewGroupKey: ReviewGroup['key'] | null = null;
  saving = false;
  loadingEvaluators = false;
  loadingAptitudeTemplates = false;
  errorMessage = '';
  successMessage = '';

  candidateSearch = '';
  reviewSearch = '';
  activeReviewFilter: ReviewFilterKey = 'all';
  selectedReviewId: number | null = null;
  candidateSearchOpen = false;

  selectedInterviewId: number | null = null;
  selectedEvaluatorId: number | null = null;
  selectedRoleId: number | null = null;
  selectedBulkIds = new Set<number>();
  scheduledDate = '';
  scheduledTime = '';
  includeAptitudeAssessment = false;
  aptitudeDate = '';
  aptitudeTime = '';
  selectedAptitudeTemplateId: number | null = null;
  readonly todayDateString = this.toLocalDateString(new Date());
  interviewType: 'manual' | 'auto' = 'manual';
  evaluatorSearch = '';
  evaluatorSearchOpen = false;
  roleSearch = '';
  roleSearchOpen = false;

  evaluatorOptions: EvaluatorOption[] = [];
  aptitudeTemplates: AptitudeTemplateOption[] = [];

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
    if (this.mode === 'schedule' || this.mode === 'bulk-aptitude') {
      this.loadAptitudeTemplates();
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
    if (this.mode === 'bulk-aptitude') return 'Bulk Assign Aptitude Test';
    if (this.mode === 'bulk-interview') return 'Bulk Assign Interview';
    return 'Evaluation Reviews';
  }

  get subtitle(): string {
    if (this.mode === 'schedule') {
      return 'Configure the interview mode, optional aptitude assessment, and confirmed interview slot for the selected candidate.';
    }
    if (this.mode === 'bulk-assign') {
      return 'Assign an evaluator across multiple candidates in one controlled workflow update.';
    }
    if (this.mode === 'bulk-aptitude') {
      return 'Select a vacancy and schedule aptitude tests for candidates still in assignment progress. Candidates already scheduled are skipped.';
    }
    if (this.mode === 'bulk-interview') {
      return 'Select a vacancy and schedule interview links for candidates still in assignment progress. Existing scheduled candidates are not changed.';
    }
    return 'Review completed interviews, evaluator feedback, and final hiring decisions.';
  }

  get isBulkScheduleMode(): boolean {
    return this.mode === 'bulk-aptitude' || this.mode === 'bulk-interview';
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

  get workflowRoleOptions(): WorkflowRoleOption[] {
    const roleMap = new Map<number, WorkflowRoleOption>();
    for (const candidate of this.candidates) {
      const roleId = Number(candidate.role_id || 0);
      if (!roleId) {
        continue;
      }
      const current = roleMap.get(roleId) || {
        id: roleId,
        label: candidate.role || `Vacancy #${roleId}`,
        helper: `Vacancy #${roleId}`,
        total: 0,
        eligible: 0,
        scheduled: 0,
      };
      current.total += 1;
      if (this.isExistingScheduledCandidate(candidate)) {
        current.scheduled += 1;
      }
      if (this.isBulkWorkflowEligible(candidate)) {
        current.eligible += 1;
      }
      roleMap.set(roleId, current);
    }
    return Array.from(roleMap.values())
      .map((role) => ({
        ...role,
        helper: `${role.eligible} eligible · ${role.scheduled} already scheduled · ${role.total} total`,
      }))
      .sort((left, right) => left.label.localeCompare(right.label));
  }

  get filteredWorkflowRoleOptions(): WorkflowRoleOption[] {
    const term = this.roleSearch.trim().toLowerCase();
    if (term.length < 2) {
      return [];
    }
    return this.workflowRoleOptions.filter((role) =>
      [role.label, role.helper, role.id]
        .map((value) => (value || '').toString().toLowerCase())
        .some((value) => value.includes(term))
    );
  }

  get selectedWorkflowRole(): WorkflowRoleOption | null {
    return this.workflowRoleOptions.find((role) => role.id === this.selectedRoleId) || null;
  }

  get bulkWorkflowEligibleCount(): number {
    const roleId = this.selectedRoleId;
    if (!roleId) {
      return 0;
    }
    return this.candidates.filter((candidate) =>
      Number(candidate.role_id || 0) === roleId && this.isBulkWorkflowEligible(candidate)
    ).length;
  }

  get showWorkflowRoleResults(): boolean {
    return this.isBulkScheduleMode
      && this.roleSearchOpen
      && this.roleSearch.trim().length >= 2
      && !this.selectedWorkflowRole
      && this.filteredWorkflowRoleOptions.length > 0;
  }

  get showWorkflowRoleEmpty(): boolean {
    return this.isBulkScheduleMode
      && this.roleSearchOpen
      && this.roleSearch.trim().length >= 2
      && !this.selectedWorkflowRole
      && this.filteredWorkflowRoleOptions.length === 0;
  }

  get reviewCandidates(): ReviewCandidateView[] {
    return this.reviewCandidatesView;
  }

  get selectedReviewCandidate(): ReviewCandidateView | null {
    return this.selectedReviewCandidateView;
  }

  get reviewFilterTabs(): ReviewFilterTab[] {
    return this.reviewFilterTabsList;
  }

  get reviewSummaryCards(): ReviewSummaryCard[] {
    return this.reviewSummaryCardsList;
  }

  get reviewAverageScore(): string {
    return this.reviewAverageScoreText;
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
          updatedShortLabel: this.formatShortDate(candidate.date),
          decisionActions: this.buildReviewDecisionActions(normalized),
          canScheduleFurther: !['shortlisted', 'offer made', 'offer accepted', 'offer declined', 'hired', 'completed', 'rejected', 'cancelled'].includes(normalized),
          initials: this.getInitials(candidate.name),
          profilePhotoUrl: this.getProfilePhotoUrl(candidate),
          scoreLabel: this.getReviewScoreLabel(candidate.score),
          scorePercent: this.getReviewScorePercent(candidate.score),
          scoreColor: this.getReviewScoreColor(candidate.score),
          statusTone: this.getReviewStatusTone(normalized),
          decisionLabel: this.getReviewDecisionLabel(normalized),
          decisionTone: this.getReviewDecisionTone(normalized),
          qaCountLabel: candidate.notes ? 'Feedback captured' : 'Not captured',
          behaviorStatusLabel: candidate.notes ? 'Evaluator notes available' : 'Feedback incomplete',
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
    return !this.saving && !this.scheduleSubmitBlocker;
  }

  get scheduleSubmitBlocker(): string {
    if (!this.selectedInterviewId) {
      return 'Select a candidate before configuring the interview plan.';
    }
    if (!this.scheduledDate || !this.scheduledTime) {
      return 'Select interview date and time.';
    }
    if (this.isPastScheduleDate()) {
      return 'Please select today or a future date.';
    }
    if (this.interviewType === 'manual' && !this.selectedEvaluatorId) {
      return 'Select an evaluator for a manual interview.';
    }
    if (!this.includeAptitudeAssessment) {
      return '';
    }
    if (!this.aptitudeDate || !this.aptitudeTime) {
      return 'Aptitude assessment time is required.';
    }
    if (this.aptitudeScheduleError) {
      return this.aptitudeScheduleError;
    }
    if (!this.selectedAptitudeTemplateId) {
      return 'Select assessment template.';
    }
    return '';
  }

  get scheduleDateError(): string {
    return this.scheduledDate && this.isPastScheduleDate()
      ? 'Please select today or a future date.'
      : '';
  }

  get availabilityInsight(): AvailabilityInsight | null {
    if (!this.selectedCandidate) {
      return null;
    }
    return this.buildAvailabilityInsight(this.selectedCandidate);
  }

  get selectedAptitudeTemplate(): AptitudeTemplateOption | null {
    return this.aptitudeTemplates.find((template) => template.id === this.selectedAptitudeTemplateId) || null;
  }

  get aptitudeScheduledAt(): string {
    return this.combineAptitudeDateTime();
  }

  get minimumAptitudeDateString(): string {
    return this.todayDateString;
  }

  get interviewGapError(): string {
    if (!this.includeAptitudeAssessment || !this.aptitudeDate || !this.aptitudeTime || !this.scheduledDate || !this.scheduledTime) {
      return '';
    }
    const aptitudeTime = this.parseDate(this.aptitudeScheduledAt);
    const interviewTime = this.parseDate(this.combineDateTime());
    if (!aptitudeTime || !interviewTime) {
      return '';
    }
    const minimumInterviewTime = new Date(aptitudeTime.getTime() + 2 * 60 * 60_000);
    return interviewTime < minimumInterviewTime
      ? 'Interview time must be at least 2 hours after aptitude assessment time.'
      : '';
  }

  get aptitudeScheduleError(): string {
    if (!this.includeAptitudeAssessment || !this.aptitudeDate || !this.aptitudeTime) {
      return '';
    }
    const aptitudeTime = this.parseDate(this.aptitudeScheduledAt);
    if (!aptitudeTime) {
      return 'Please provide a valid aptitude assessment time.';
    }
    if (aptitudeTime.getTime() < Date.now()) {
      return 'Aptitude assessment time must not be in the past.';
    }
    if (this.interviewGapError) {
      return this.interviewGapError;
    }
    return '';
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

  get bulkWorkflowSubmitBlocker(): string {
    if (!this.selectedRoleId) {
      return 'Select a job vacancy before assigning.';
    }
    if (!this.bulkWorkflowEligibleCount) {
      return 'No assignment-in-progress candidates are eligible for this vacancy.';
    }
    if (!this.scheduledDate || !this.scheduledTime) {
      return 'Select date and time for the bulk assignment.';
    }
    if (this.scheduleDateError) {
      return this.scheduleDateError;
    }
    if (this.mode === 'bulk-aptitude' && !this.selectedAptitudeTemplateId) {
      return 'Select assessment template.';
    }
    return '';
  }

  get canSubmitBulkWorkflow(): boolean {
    return !this.saving && !this.bulkWorkflowSubmitBlocker;
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

  loadAptitudeTemplates(): void {
    this.loadingAptitudeTemplates = true;
    this.http.get<any>(`${this.getApiBaseUrl()}/api/aptitude/templates/`)
      .pipe(
        catchError((error) => {
          console.error('Error loading aptitude templates', error);
          this.loadingAptitudeTemplates = false;
          return of(null);
        })
      )
      .subscribe((response) => {
        this.loadingAptitudeTemplates = false;
        if (!response?.success) {
          return;
        }
        this.aptitudeTemplates = response?.data?.templates || [];
        this.ensureDefaultAptitudeTemplate();
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
    this.aptitudeDate = '';
    this.aptitudeTime = '';
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
    this.includeAptitudeAssessment = false;
    this.aptitudeDate = '';
    this.aptitudeTime = '';
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

  openRoleSearch(): void {
    if (!this.isBulkScheduleMode || this.selectedWorkflowRole) {
      return;
    }
    this.roleSearchOpen = true;
  }

  closeRoleSearch(): void {
    window.setTimeout(() => {
      this.roleSearchOpen = false;
      if (this.selectedWorkflowRole) {
        this.roleSearch = this.selectedWorkflowRole.label;
      }
    }, 120);
  }

  onRoleSearchChange(value: string): void {
    this.roleSearch = value;
    this.roleSearchOpen = true;
    this.selectedRoleId = null;
    this.errorMessage = '';
  }

  selectWorkflowRole(role: WorkflowRoleOption): void {
    this.selectedRoleId = role.id;
    this.roleSearch = role.label;
    this.roleSearchOpen = false;
    this.errorMessage = '';
  }

  resetSelectedWorkflowRole(): void {
    this.selectedRoleId = null;
    this.roleSearch = '';
    this.roleSearchOpen = false;
    this.errorMessage = '';
  }

  onReviewSearchChange(value: string): void {
    this.reviewSearch = value;
    this.refreshReviewData();
  }

  setActiveReviewFilter(key: ReviewFilterKey): void {
    this.activeReviewFilter = key;
    this.updateReviewViewState();
  }

  selectReviewCandidate(candidate: ReviewCandidateView): void {
    this.selectedReviewId = candidate.id;
    this.updateSelectedReviewCandidate();
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

  onScheduleDateChange(value: string): void {
    this.scheduledDate = value;
    if (this.scheduleDateError) {
      this.errorMessage = this.scheduleDateError;
      return;
    }
    if (this.interviewGapError) {
      this.errorMessage = this.interviewGapError;
      return;
    }
    if (
      this.errorMessage === 'Please select today or a future date.'
      || this.errorMessage === 'Interview time must be at least 2 hours after aptitude assessment time.'
    ) {
      this.errorMessage = '';
    }
  }

  onScheduleTimeChange(value: string): void {
    this.scheduledTime = value;
    if (this.interviewGapError) {
      this.errorMessage = this.interviewGapError;
      return;
    }
    if (this.errorMessage === 'Interview time must be at least 2 hours after aptitude assessment time.') {
      this.errorMessage = '';
    }
  }

  onBulkScheduleDateChange(value: string): void {
    this.scheduledDate = value;
    if (this.scheduleDateError) {
      this.errorMessage = this.scheduleDateError;
      return;
    }
    if (this.errorMessage === 'Please select today or a future date.') {
      this.errorMessage = '';
    }
  }

  onBulkScheduleTimeChange(value: string): void {
    this.scheduledTime = value;
    if (this.errorMessage === 'Select date and time for the bulk assignment.') {
      this.errorMessage = '';
    }
  }

  toggleAptitudeAssessment(value: boolean): void {
    this.includeAptitudeAssessment = value;
    this.errorMessage = '';
    if (value) {
      this.ensureDefaultAptitudeTemplate();
      if (!this.aptitudeDate || !this.aptitudeTime) {
        const suggested = this.buildSuggestedAptitudeDateTime();
        this.aptitudeDate = suggested.date;
        this.aptitudeTime = suggested.time;
      }
      return;
    }
    this.aptitudeDate = '';
    this.aptitudeTime = '';
  }

  onAptitudeDateChange(value: string): void {
    this.aptitudeDate = value;
    if (this.aptitudeScheduleError) {
      this.errorMessage = this.aptitudeScheduleError;
      return;
    }
    if (
      this.errorMessage.startsWith('Aptitude assessment time')
      || this.errorMessage === 'Interview time must be at least 2 hours after aptitude assessment time.'
    ) {
      this.errorMessage = '';
    }
  }

  onAptitudeTimeChange(value: string): void {
    this.aptitudeTime = value;
    if (this.aptitudeScheduleError) {
      this.errorMessage = this.aptitudeScheduleError;
      return;
    }
    if (this.errorMessage.startsWith('Aptitude assessment time') || this.errorMessage === 'Interview time must be at least 2 hours after aptitude assessment time.') {
      this.errorMessage = '';
    }
  }

  applySuggestedAvailability(): void {
    const insight = this.availabilityInsight;
    if (!insight) {
      return;
    }
    this.scheduledDate = insight.date;
    this.scheduledTime = insight.time;
    if (this.errorMessage === 'Please select today or a future date.') {
      this.errorMessage = '';
    }
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
      this.errorMessage = this.scheduleSubmitBlocker || 'Complete the required schedule fields.';
      return;
    }
    const payload: Record<string, unknown> = {
      mode: 'schedule',
      interview_ids: [this.selectedInterviewId],
      interviewer_id: this.selectedEvaluatorId,
      interview_type: this.interviewType,
      scheduled_at: this.combineDateTime(),
    };
    if (this.includeAptitudeAssessment) {
      payload['include_aptitude_assessment'] = true;
      payload['aptitude_scheduled_at'] = this.aptitudeScheduledAt;
      payload['aptitude_template_id'] = this.selectedAptitudeTemplateId;
    }
    this.submitWorkflowUpdate(payload);
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

  saveBulkWorkflowSchedule(): void {
    if (!this.canSubmitBulkWorkflow) {
      this.errorMessage = this.bulkWorkflowSubmitBlocker || 'Complete the required bulk assignment fields.';
      return;
    }
    this.submitBulkWorkflowSchedule({
      mode: this.mode,
      role_id: this.selectedRoleId,
      scheduled_at: this.combineDateTime(),
      aptitude_template_id: this.mode === 'bulk-aptitude' ? this.selectedAptitudeTemplateId : null,
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
      this.selectedReviewId = null;
      this.updateReviewViewState();
      return;
    }
    const hasActiveGroup = this.reviewGroupsList.some((group) => group.key === this.activeReviewGroupKey);
    if (!hasActiveGroup) {
      this.activeReviewGroupKey = this.reviewGroupsList[0].key;
    }
    this.updateReviewViewState();
  }

  private updateReviewViewState(): void {
    this.reviewCandidatesView = this.filteredReviewCandidatesList.filter((candidate) => this.matchesReviewFilter(candidate, this.activeReviewFilter));
    this.reviewAverageScoreText = this.calculateReviewAverageScore();
    this.reviewFilterTabsList = this.buildReviewFilterTabs();
    this.reviewSummaryCardsList = this.buildReviewSummaryCards();
    this.ensureSelectedReviewCandidate();
  }

  private updateSelectedReviewCandidate(): void {
    this.selectedReviewCandidateView = this.filteredReviewCandidatesList.find((candidate) => candidate.id === this.selectedReviewId) || null;
  }

  private ensureSelectedReviewCandidate(): void {
    const visible = this.reviewCandidatesView;
    if (!visible.length) {
      this.selectedReviewId = null;
      this.selectedReviewCandidateView = null;
      return;
    }
    const selectedVisible = visible.some((candidate) => candidate.id === this.selectedReviewId);
    if (!selectedVisible) {
      this.selectedReviewId = visible[0].id;
    }
    this.updateSelectedReviewCandidate();
  }

  private getReviewFilterCount(key: ReviewFilterKey): number {
    return this.filteredReviewCandidatesList.filter((candidate) => this.matchesReviewFilter(candidate, key)).length;
  }

  private buildReviewFilterTabs(): ReviewFilterTab[] {
    return [
      { key: 'all', label: 'All', count: this.getReviewFilterCount('all') },
      { key: 'pending', label: 'Pending Review', count: this.getReviewFilterCount('pending') },
      { key: 'completed', label: 'Completed', count: this.getReviewFilterCount('completed') },
      { key: 'needs-decision', label: 'Needs Decision', count: this.getReviewFilterCount('needs-decision') },
      { key: 'overdue', label: 'Overdue', count: this.getReviewFilterCount('overdue') },
    ];
  }

  private buildReviewSummaryCards(): ReviewSummaryCard[] {
    return [
      {
        key: 'pending',
        label: 'Pending Review',
        value: this.getReviewFilterCount('pending'),
        helper: 'Completed interviews awaiting recruiter review',
        icon: 'ph-hourglass-medium',
        tone: 'pending',
      },
      {
        key: 'completed',
        label: 'Completed Evaluations',
        value: this.getReviewFilterCount('completed'),
        helper: 'Evaluations with captured score or feedback',
        icon: 'ph-check-circle',
        tone: 'completed',
      },
      {
        key: 'decision',
        label: 'Needs Decision',
        value: this.getReviewFilterCount('needs-decision'),
        helper: 'Records requiring a hiring decision',
        icon: 'ph-git-pull-request',
        tone: 'decision',
      },
      {
        key: 'overdue',
        label: 'Overdue Feedback',
        value: this.getReviewFilterCount('overdue'),
        helper: 'Older feedback items still incomplete',
        icon: 'ph-warning',
        tone: 'overdue',
      },
    ];
  }

  private calculateReviewAverageScore(): string {
    const scores = this.filteredReviewCandidatesList
      .map((candidate) => candidate.score)
      .filter((score): score is number => score !== null && score !== undefined)
      .map((score) => Number(score))
      .filter((score) => Number.isFinite(score));
    if (!scores.length) return '--';
    return (scores.reduce((sum, score) => sum + score, 0) / scores.length).toFixed(1);
  }

  private matchesReviewFilter(candidate: ReviewCandidateView, key: ReviewFilterKey): boolean {
    if (key === 'all') {
      return true;
    }
    const normalized = this.normalizeStatus(candidate.status);
    if (key === 'pending') {
      return normalized === 'completed' || !candidate.notes || candidate.score === null || candidate.score === undefined;
    }
    if (key === 'completed') {
      return !!candidate.notes || candidate.score !== null && candidate.score !== undefined || ['completed', 'shortlisted', 'offer made', 'offer accepted', 'offer declined', 'hired', 'rejected'].includes(normalized);
    }
    if (key === 'needs-decision') {
      return ['completed', 'shortlisted', 'offer made', 'offer accepted'].includes(normalized) || candidate.decisionActions.length > 0;
    }
    return this.isReviewOverdue(candidate);
  }

  private isReviewOverdue(candidate: ReviewCandidateView): boolean {
    const submittedAt = this.toTime(candidate.date);
    if (!submittedAt) {
      return false;
    }
    const ageMs = Date.now() - submittedAt;
    const olderThanTwoDays = ageMs > 2 * 24 * 60 * 60 * 1000;
    return olderThanTwoDays && (!candidate.notes || candidate.score === null || candidate.score === undefined || this.matchesReviewFilter(candidate, 'needs-decision'));
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

  formatShortDate(value?: string): string {
    if (!value) return 'Not captured';
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return 'Not captured';
    return parsed.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
  }

  getProfilePhotoUrl(candidate: WorkflowCandidate): string {
    return candidate.profile_picture_url || candidate.candidate_profile_picture_url || '';
  }

  private getInitials(name: string): string {
    const parts = (name || 'Candidate')
      .trim()
      .split(/\s+/)
      .filter(Boolean);
    return parts.slice(0, 2).map((part) => part.charAt(0).toUpperCase()).join('') || 'C';
  }

  private getReviewScorePercent(score?: number | null): number {
    if (score === null || score === undefined) {
      return 0;
    }
    const numeric = Number(score);
    if (!Number.isFinite(numeric)) {
      return 0;
    }
    const percent = numeric <= 10 ? numeric * 10 : numeric;
    return Math.max(0, Math.min(100, Math.round(percent)));
  }

  private getReviewScoreLabel(score?: number | null): string {
    if (score === null || score === undefined || !Number.isFinite(Number(score))) {
      return 'Not scored';
    }
    return `${this.getReviewScorePercent(score)}/100`;
  }

  private getReviewScoreColor(score?: number | null): string {
    const percent = this.getReviewScorePercent(score);
    if (!percent) return '#65b9ff';
    if (percent >= 75) return '#20d892';
    if (percent >= 50) return '#f6a11a';
    return '#ff5f7a';
  }

  private getReviewStatusTone(normalized: string): 'success' | 'warning' | 'danger' | 'info' {
    if (['hired', 'shortlisted', 'offer accepted'].includes(normalized)) return 'success';
    if (['completed', 'offer made', 'scheduled'].includes(normalized)) return 'warning';
    if (['rejected', 'offer declined', 'cancelled'].includes(normalized)) return 'danger';
    return 'info';
  }

  private getReviewDecisionLabel(normalized: string): string {
    if (['hired', 'offer accepted', 'shortlisted'].includes(normalized)) return 'Recommended';
    if (['completed', 'offer made'].includes(normalized)) return 'Needs Decision';
    if (['rejected', 'offer declined', 'cancelled'].includes(normalized)) return 'Not Recommended';
    return 'Review Pending';
  }

  private getReviewDecisionTone(normalized: string): 'success' | 'warning' | 'danger' | 'info' {
    if (['hired', 'offer accepted', 'shortlisted'].includes(normalized)) return 'success';
    if (['completed', 'offer made'].includes(normalized)) return 'warning';
    if (['rejected', 'offer declined', 'cancelled'].includes(normalized)) return 'danger';
    return 'info';
  }

  trackCandidate(_: number, candidate: WorkflowCandidate): number {
    return candidate.id;
  }

  trackEvaluator(_: number, evaluator: EvaluatorOption): number {
    return evaluator.id;
  }

  trackRole(_: number, role: WorkflowRoleOption): number {
    return role.id;
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
        const aptitudeScheduled = (response?.Data?.items || []).some((item: any) => !!item?.aptitude_assignment_id);
        const notificationQueued = notificationResults.some((item: any) => !!item?.result?.queued);
        const notificationSent = notificationResults.some((item: any) => !!item?.result?.sent);
        const successMessage = this.mode === 'schedule'
          ? `Interview scheduled${aptitudeScheduled ? ' with aptitude assessment' : ''}${notificationQueued ? ' and follow-up notifications queued' : (notificationSent ? ' and candidate notification sent' : '')}.`
          : `${updatedCount} candidate record${updatedCount === 1 ? '' : 's'} updated successfully.`;
        this.successMessage = successMessage;
        this.toast.showSuccess(this.mode === 'schedule' ? 'Interview scheduled' : 'Workflow updated', successMessage);
        this.close({ action: 'refresh', message: successMessage });
      });
  }

  private submitBulkWorkflowSchedule(payload: Record<string, unknown>): void {
    this.saving = true;
    this.errorMessage = '';
    this.successMessage = '';

    this.http.post<any>(`${this.getApiBaseUrl()}/bulk-workflow-schedule/`, payload)
      .pipe(
        catchError((error) => {
          console.error('Error completing bulk workflow schedule', error);
          this.saving = false;
          this.errorMessage = error?.error?.Error || 'Unable to complete bulk assignment.';
          this.toast.showError('Bulk assignment failed', this.errorMessage);
          return of(null);
        })
      )
      .subscribe((response) => {
        this.saving = false;
        if (!response?.Success) {
          this.errorMessage = response?.Error || 'Unable to complete bulk assignment.';
          this.toast.showError('Bulk assignment failed', this.errorMessage);
          return;
        }
        const updatedCount = response?.Data?.updated_count || 0;
        const skippedCount = response?.Data?.skipped_count || 0;
        const noun = this.mode === 'bulk-aptitude' ? 'aptitude test' : 'interview';
        const successMessage = `${updatedCount} ${noun}${updatedCount === 1 ? '' : 's'} assigned. ${skippedCount} candidate${skippedCount === 1 ? '' : 's'} skipped because they were already scheduled or not eligible.`;
        this.successMessage = successMessage;
        this.toast.showSuccess('Bulk assignment complete', successMessage);
        this.close({ action: 'refresh', message: successMessage });
      });
  }

  private isBulkWorkflowEligible(candidate: WorkflowCandidate): boolean {
    const status = this.normalizeStatus(candidate.status);
    return ['assignment in progress', 'assessment pending', 'assignment pending'].includes(status)
      && !this.isExistingScheduledCandidate(candidate);
  }

  private isExistingScheduledCandidate(candidate: WorkflowCandidate): boolean {
    const status = this.normalizeStatus(candidate.status);
    return ['scheduled', 'auto screening scheduled'].includes(status)
      || this.normalizeStatus(candidate.aptitude_status || '') === 'assigned'
      || this.normalizeStatus(candidate.aptitude_status || '') === 'in progress'
      || candidate.candidate_action_link_type === 'aptitude'
      || !!candidate.aptitude_assignment_id;
  }

  private getApiBaseUrl(): string {
    let port = '';
    if (window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost') {
      port = '8080';
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

  private combineAptitudeDateTime(): string {
    return this.aptitudeDate && this.aptitudeTime ? `${this.aptitudeDate}T${this.aptitudeTime}` : '';
  }

  private ensureDefaultAptitudeTemplate(): void {
    if (this.selectedAptitudeTemplateId || !this.aptitudeTemplates.length) {
      return;
    }
    const preferred = this.aptitudeTemplates.find((template) => template.title === 'General Aptitude Test')
      || this.aptitudeTemplates[0];
    this.selectedAptitudeTemplateId = preferred.id;
  }

  private buildSuggestedAptitudeDateTime(): { date: string; time: string } {
    const interviewTime = this.parseDate(this.combineDateTime());
    const now = new Date();
    const base = interviewTime
      ? new Date(interviewTime.getTime() - 2 * 60 * 60_000)
      : new Date(now.getTime() + 60 * 60_000);
    const adjusted = base.getTime() < now.getTime()
      ? this.roundUpToStep(new Date(now.getTime() + 5 * 60_000), 5)
      : base;
    return { date: this.toLocalDateString(adjusted), time: this.toLocalTimeString(adjusted) };
  }

  private buildAvailabilityInsight(candidate: WorkflowCandidate): AvailabilityInsight {
    const slot = this.findNextAvailableInterviewSlot(candidate);
    const conflictCount = this.getCandidateBusyWindows(candidate).length;
    return {
      date: this.toLocalDateString(slot),
      time: this.toLocalTimeString(slot),
      dateLabel: slot.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' }),
      timeLabel: slot.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' }),
      windowLabel: '9:00 AM - 6:00 PM',
      helper: conflictCount
        ? `${conflictCount} existing scheduled interview${conflictCount === 1 ? '' : 's'} checked for this candidate.`
        : 'No existing scheduled interviews found for this candidate.',
      conflictCount,
    };
  }

  private findNextAvailableInterviewSlot(candidate: WorkflowCandidate): Date {
    const busyWindows = this.getCandidateBusyWindows(candidate);
    const slotMinutes = 60;
    const stepMinutes = 30;
    let cursor = this.roundUpToStep(new Date(), stepMinutes);

    for (let dayOffset = 0; dayOffset < 90; dayOffset += 1) {
      const day = new Date(cursor);
      day.setDate(cursor.getDate() + dayOffset);
      const dayStart = new Date(day);
      dayStart.setHours(9, 0, 0, 0);
      const dayEnd = new Date(day);
      dayEnd.setHours(18, 0, 0, 0);

      let slotStart = dayOffset === 0 && cursor > dayStart ? new Date(cursor) : dayStart;
      if (slotStart.getHours() < 9) {
        slotStart = dayStart;
      }
      while (slotStart.getTime() + slotMinutes * 60_000 <= dayEnd.getTime()) {
        const slotEnd = new Date(slotStart.getTime() + slotMinutes * 60_000);
        const overlaps = busyWindows.some((busy) => slotStart < busy.end && slotEnd > busy.start);
        if (!overlaps) {
          return slotStart;
        }
        slotStart = new Date(slotStart.getTime() + stepMinutes * 60_000);
      }
    }

    const fallback = new Date();
    fallback.setDate(fallback.getDate() + 1);
    fallback.setHours(9, 0, 0, 0);
    return fallback;
  }

  private getCandidateBusyWindows(candidate: WorkflowCandidate): Array<{ start: Date; end: Date }> {
    const candidateKey = this.getCandidateScheduleKey(candidate);
    if (!candidateKey) {
      return [];
    }
    return this.candidates
      .filter((item) => item.id !== candidate.id && this.getCandidateScheduleKey(item) === candidateKey)
      .filter((item) => ['scheduled', 'auto screening scheduled'].includes(this.normalizeStatus(item.status)))
      .map((item) => {
        const start = this.parseDate(item.date);
        if (!start) {
          return null;
        }
        return {
          start,
          end: new Date(start.getTime() + 60 * 60_000),
        };
      })
      .filter((item): item is { start: Date; end: Date } => !!item && item.end.getTime() > Date.now());
  }

  private getCandidateScheduleKey(candidate: WorkflowCandidate): string {
    if (candidate.candidate_id) {
      return `candidate:${candidate.candidate_id}`;
    }
    if (candidate.email) {
      return `email:${candidate.email.trim().toLowerCase()}`;
    }
    const name = (candidate.name || '').trim().toLowerCase();
    return name ? `name:${name}` : `interview:${candidate.id}`;
  }

  private roundUpToStep(value: Date, stepMinutes: number): Date {
    const rounded = new Date(value);
    rounded.setSeconds(0, 0);
    const minutes = rounded.getMinutes();
    const remainder = minutes % stepMinutes;
    if (remainder) {
      rounded.setMinutes(minutes + stepMinutes - remainder);
    }
    return rounded;
  }

  private isPastScheduleDate(): boolean {
    return !!this.scheduledDate && this.scheduledDate < this.todayDateString;
  }

  private toLocalDateString(value: Date): string {
    const year = value.getFullYear();
    const month = `${value.getMonth() + 1}`.padStart(2, '0');
    const day = `${value.getDate()}`.padStart(2, '0');
    return `${year}-${month}-${day}`;
  }

  private toLocalTimeString(value: Date): string {
    const hours = `${value.getHours()}`.padStart(2, '0');
    const minutes = `${value.getMinutes()}`.padStart(2, '0');
    return `${hours}:${minutes}`;
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
    const parsed = this.parseDate(value);
    return parsed ? parsed.getTime() : 0;
  }

  private parseDate(value?: string): Date | null {
    if (!value) return null;
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  }
}
