import { Component, AfterViewInit, OnDestroy, OnInit, ViewChild, ElementRef, SimpleChanges, DestroyRef, inject, HostListener } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';  // Import HttpClient
import { catchError } from 'rxjs/operators';
import { of, timeout } from 'rxjs';
import { CommonModule } from '@angular/common';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { FormsModule } from '@angular/forms';
import { Evaluators } from '../evaluators/evaluators';
import { Recruiters } from '../recruiters/recruiters';
import { Candidates } from '../candidates/candidates';
import { Activity } from '../activity/activity';
import { Analytics } from '../analytics/analytics';
import { TalentPool } from '../talent-pool/talent-pool';
import { LitioAssistant, LitioAssistantContext } from '../litio-assistant/litio-assistant';
import { Chart, registerables } from 'chart.js';
import * as XLSX from 'xlsx';
import { AddUser } from '../app-modal/add-user/add-user';
import { ConfirmationBox } from '../app-modal/confirmation-box/confirmation-box/confirmation-box';
import { RoleDetail } from '../app-modal/role-detail/role-detail';
import { CandidateProfile } from '../app-modal/candidate-profile/candidate-profile';
import { WorkflowAction } from '../app-modal/workflow-action/workflow-action';
import { getApiBaseUrl } from '../core/api-base';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { writeWorkspaceContext } from '../core/workspace-context';
import { AppToastService } from '../core/app-toast.service';
import { DigitsOnlyDirective } from '../core/digits-only.directive';

Chart.register(...registerables);

type TrendDirection = 'up' | 'down' | 'flat';

interface MonthlyTrendCard {
  key: string;
  label: string;
  helper: string;
  icon: string;
  value: number;
  previousValue: number;
  delta: number;
  deltaText: string;
  direction: TrendDirection;
}

interface OverviewKpiCard {
  key: string;
  label: string;
  value: number;
  icon: string;
  toneClass: string;
  trendText: string;
  trendDirection: TrendDirection;
  trendIcon: string;
}

interface AttentionItem {
  key: AttentionFilterKey;
  title: string;
  icon: string;
  count: number;
  helperText: string;
  candidates: any[];
}

type AttentionFilterKey = 'overdue-feedback' | 'unscheduled-shortlisted' | 'pending-offers';
type PendingActionKey = 'all' | 'new-applications' | 'assessment-pending' | 'overdue-feedback' | 'interviews-pending' | 'offer-decisions';
type PendingActionPriorityFilter = 'all' | 'high' | 'medium' | 'low';
type PendingActionSortKey = 'newest' | 'oldest' | 'priority';

interface RecruiterApplicationItem {
  id: number;
  candidate_id: number;
  candidate_name: string;
  candidate_email: string;
  candidate_phone?: string;
  vacancy_id: number;
  vacancy_role: string;
  status: string;
  status_label: string;
  applied_at: string;
  source?: string;
  public_profile_url?: string;
  public_resume_pdf_url?: string;
  public_profile_pdf_url?: string;
  resume_pdf_url?: string;
  actionLoading?: boolean;
  removing?: boolean;
}

interface PendingActionCard {
  key: PendingActionKey;
  label: string;
  helper: string;
  icon: string;
  count: number;
  tone: string;
}

interface PendingActionListItem {
  id: string;
  actionKey: PendingActionKey;
  actionLabel: string;
  actionIcon: string;
  actionTone: string;
  name: string;
  email: string;
  phone: string;
  role: string;
  status: string;
  date: string;
  source: string;
  kind: 'application' | 'candidate';
  raw: any;
}

interface CandidateExportRow {
  candidateName: string;
  email: string;
  role: string;
  roleId: string;
  recruiter: string;
  interviewer: string;
  status: string;
  score: string;
  date: string;
  notes: string;
}

interface CandidateFilterOption {
  value: string | null;
  label: string;
  helper: string;
  icon: string;
  tone: string;
}

interface CompanyProfileData {
  legal_name: string;
  display_name: string;
  description: string;
  industry: string;
  sub_industry: string;
  company_type: string;
  company_stage: string;
  company_size: string;
  employee_count: number | null;
  founded_year: number | null;
  website: string;
  careers_page: string;
  linkedin_url: string;
  twitter_url: string;
  logo_url: string;
  contact_email: string;
  contact_phone: string;
  alternate_phone: string;
  address_line_1: string;
  address_line_2: string;
  landmark: string;
  city: string;
  state: string;
  postal_code: string;
  country: string;
  headquarters: string;
  registration_number: string;
  tax_identifier: string;
  currency_code: string;
  timezone: string;
  updated_at: string;
}

interface CompanyProfileFormData {
  legal_name: string;
  display_name: string;
  description: string;
  industry: string;
  sub_industry: string;
  company_type: string;
  company_stage: string;
  company_size: string;
  employee_count: string;
  founded_year: string;
  website: string;
  careers_page: string;
  linkedin_url: string;
  twitter_url: string;
  contact_email: string;
  contact_phone: string;
  alternate_phone: string;
  address_line_1: string;
  address_line_2: string;
  landmark: string;
  city: string;
  state: string;
  postal_code: string;
  country: string;
  headquarters: string;
  registration_number: string;
  tax_identifier: string;
  currency_code: string;
  timezone: string;
}

type CompanyProfileTab = 'details' | 'branding' | 'contact' | 'billing';

interface CandidateEvaluationSummary {
  available: boolean;
  candidate_name: string;
  role_title: string;
  decision: string;
  recommendation: string;
  score: number | null;
  executive_summary: string;
  summary_verdict: string;
  professional_summary: string;
  professional_summary_sections: ProfessionalSummarySection[];
  professional_summary_fallback: string;
  question_answer_records: QuestionAnswerRecord[];
  candidate_behavior: CandidateBehaviorSummary;
  evidence_highlights: string[];
  technical_breakdown: Record<string, unknown>;
  behavior_breakdown: Record<string, unknown>;
  next_round_focus: string[];
  evaluation_payload: Record<string, unknown>;
  confidence: string;
  interview_signal_quality: string;
  strengths: string[];
  concerns: string[];
  gaps: string[];
  notes: string[];
  follow_up_areas: string[];
  hire_recommendation_action: string;
  hire_recommendation_reason: string;
  early_exit: boolean;
  early_exit_reason: string;
  profile_picture_data_url: string;
  updated_at: string;
  created_at: string;
  aptitude_assessment: AptitudeAssessmentSummary;
}

interface AptitudeAssessmentSummary {
  available: boolean;
  status: string;
  status_label: string;
  assignment_id: number | null;
  title: string;
  scheduled_at: string;
  submitted_at: string;
  started_at: string;
  expires_at: string;
  score: number | null;
  score_percent: number | null;
  max_score: number | null;
  passed: boolean | null;
  result_label: string;
  passing_score_percent: number | null;
  total_questions: number;
  answered_count: number;
  unanswered_count: number;
  early_exit: boolean;
  early_exit_reason: string;
  section_results: AptitudeSectionResult[];
  integrity_summary: AptitudeIntegritySummary;
}

interface AptitudeSectionResult {
  section_code: string;
  section_name: string;
  score: number | null;
  max_score: number | null;
  score_percent: number | null;
  correct_count: number;
  incorrect_count: number;
  unanswered_count: number;
  total_questions: number;
}

interface AptitudeIntegritySummary {
  review_required: boolean;
  event_count: number;
  flags: string[];
}

interface ProfessionalSummarySection {
  key: string;
  title: string;
  content: string;
}

interface QuestionAnswerRecord {
  turn_index: number | string;
  skill: string;
  section_role: string;
  question_text: string;
  candidate_answer: string;
  answer_quality_state: string;
  expected_signal: string;
}

interface CandidateBehaviorSummary {
  status: string;
  summary: string;
  gaze_tracking: Record<string, unknown>;
  voice_verification: Record<string, unknown>;
}

interface EvaluationReportMetaItem {
  label: string;
  value: string;
  icon: string;
}

interface EvaluationReportInsight {
  label: string;
  value: string;
  helper: string;
  icon: string;
  tone: string;
}

interface EvaluationReportSkillRow {
  label: string;
  score: number | null;
  proficiency: string;
  tone: string;
}

interface EvaluationReportProgressStep {
  label: string;
  state: string;
  score: string;
  active: boolean;
  tone: string;
}

interface EvaluationReportProfileItem {
  label: string;
  value: string;
  icon: string;
}

interface WorkspaceTourStep {
  key: string;
  title: string;
  description: string;
  selector?: string;
  padding?: number;
}

@Component({
  selector: 'app-dashboard',
  standalone: true,
  templateUrl: './dashboard.html',
  styleUrls: ['./dashboard.scss'],
  imports: [CommonModule, MatDialogModule, Evaluators, Recruiters, Candidates, Activity, Analytics, TalentPool, LitioAssistant, FormsModule, DigitsOnlyDirective],
})
export class Dashboard implements OnInit, AfterViewInit, OnDestroy {
  private readonly destroyRef = inject(DestroyRef);
  private readonly toast = inject(AppToastService);
  private readonly apiTimeoutMs = 12000;
  data: any;
  loading = false;
  shellLoading = true;
  activeTab: 'overview' | 'recruiters' | 'evaluators' | 'candidates' | 'ai-talent-pool' | 'activity' | 'analytics' = 'overview';
  mobileNavOpen = false;
  candidatesData: any;
  scheduledCandidates: any;
  completedCandidates: any;
  cancelledCandidates: any;
  shortlistedCandidates: any;
  hiredCandidates: any;
  assessmentPendingCandidates: any;
  autoScreeningScheduledCandidates: any;
  rejectedCandidates: any;
  assessmentCompletedCandidates: any;
  selectedStatus: string | null = null;
  pageSize: number = 10;          // candidates per page
  currentPage: number = 1;        // starting page
  showPagination: boolean = false;
  loginUser = '';
  loginUserEmail = '';
  loginUserRole = '';
  companyProfile: CompanyProfileData | null = null;
  companyDetailsModalOpen = false;
  companyDisplayNameText = 'Company Pending';
  companyInitialsText = 'CP';
  companyMetaLineText = 'Profile setup in progress';
  companyLocationLineText = '';
  companyOverviewItemsData: Array<{ label: string; value: string }> = [];
  companyLinksData: Array<{ label: string; value: string; icon: string }> = [];
  companyContactsData: Array<{ label: string; value: string; icon: string }> = [];
  companyEditMode = false;
  activeCompanyProfileTab: CompanyProfileTab = 'details';
  companySaving = false;
  selectedCompanyLogoFile: File | null = null;
  selectedCompanyLogoName = '';
  companyForm: CompanyProfileFormData = this.createEmptyCompanyForm();
  activeCandidates: any;
  searchQuery = '';
  candidateFilterMenuOpen = false;
  readonly candidateFilterOptions: CandidateFilterOption[] = [
    { value: null, label: 'All Candidates', helper: 'Complete candidate pipeline', icon: 'ph-users-three', tone: 'all' },
    { value: 'scheduled', label: 'In-Progress', helper: 'Candidates with active interviews', icon: 'ph-spinner-gap', tone: 'scheduled' },
    { value: 'rejected', label: 'Disqualified', helper: 'Candidates removed from consideration', icon: 'ph-x-circle', tone: 'rejected' },
    { value: 'shortlisted', label: 'Shortlisted', helper: 'Candidates ready for next steps', icon: 'ph-check-circle', tone: 'shortlisted' },
    { value: 'completed', label: 'Hired', helper: 'Completed or hired candidates', icon: 'ph-handshake', tone: 'completed' },
    { value: 'cancelled', label: 'Cancelled', helper: 'Stopped or cancelled processes', icon: 'ph-clock-counter-clockwise', tone: 'cancelled' },
    { value: 'assessment pending', label: 'Assessment Pending', helper: 'Waiting for assessment completion', icon: 'ph-clipboard-text', tone: 'assessment' },
    { value: 'auto screening scheduled', label: 'Auto Screening', helper: 'Automated screening scheduled', icon: 'ph-robot', tone: 'auto' },
  ];
  attentionFilter: AttentionFilterKey | null = null;
  lastUpdatedAt: Date = new Date();
  roleCatalog: any[] = [];
  recruiterApplications: RecruiterApplicationItem[] = [];
  recruiterApplicationsCount = 0;
  applicationFeedLoaded = false;
  applicationToastOpen = false;
  applicationToastMessage = '';
  pendingRequestsModalOpen = false;
  pendingRequestsSearch = '';
  pendingActionPriorityFilter: PendingActionPriorityFilter = 'all';
  pendingActionSortKey: PendingActionSortKey = 'newest';
  activePendingActionKey: PendingActionKey = 'all';
  activePendingActionItemId: string | null = null;
  talentPoolRoleId: string | null = null;
  activeInterviewLinkMenuId: number | null = null;
  resendingInterviewEmailId: number | null = null;
  evaluationSummaryModalOpen = false;
  evaluationSummaryLoading = false;
  evaluationSummaryLoadingCandidateId: number | null = null;
  evaluationSummaryError = '';
  evaluationSummaryCandidate: any | null = null;
  evaluationSummary: CandidateEvaluationSummary = this.createEmptyEvaluationSummary();
  evaluationReportOpen = false;
  evaluationReportGeneratedAt = new Date();
  evaluationReportMetaItems: EvaluationReportMetaItem[] = [];
  evaluationReportProfileItems: EvaluationReportProfileItem[] = [];
  evaluationReportInsightCards: EvaluationReportInsight[] = [];
  evaluationReportSkillRows: EvaluationReportSkillRow[] = [];
  evaluationReportProgressSteps: EvaluationReportProgressStep[] = [];
  evaluationFeedbackRows: Array<{ avatar: string; evaluator: string; stage: string; score: string; summary: string; tone: string }> = [];
  evaluationFeedbackHighlights: Array<{ title: string; description: string; icon: string }> = [];
  evaluationCoreSkillTags: string[] = [];
  evaluationNeedAttentionItems: string[] = [];
  evaluationActionItems: string[] = [];
  evaluationEducationItems: Array<{ title: string; detail: string }> = [];
  evaluationReportQaRecords: QuestionAnswerRecord[] = [];
  qaExpandedKeys = new Set<string>();
  workspaceTourOpen = false;
  workspaceTourSteps: WorkspaceTourStep[] = [];
  workspaceTourIndex = 0;
  workspaceTourSpotlightStyle: Record<string, string> = {};
  workspaceTourTooltipStyle: Record<string, string> = {};
  activeRoleContext: { id: string; title: string } | null = null;
  activeCandidateContext: any | null = null;
  activeWorkflowContext: { mode: string; candidate?: any | null } | null = null;
  addUserModalContext: 'candidate' | 'role' | null = null;
  @ViewChild('mobileNavPanel') mobileNavPanelRef?: ElementRef<HTMLElement>;
  @ViewChild('mobileNavToggleButton') mobileNavToggleButtonRef?: ElementRef<HTMLButtonElement>;
  @ViewChild('companyModalCard') companyModalCardRef?: ElementRef<HTMLElement>;
  @ViewChild('companyModalCloseButton') companyModalCloseButtonRef?: ElementRef<HTMLButtonElement>;
  @ViewChild('pendingRequestsDialog') pendingRequestsDialogRef?: ElementRef<HTMLElement>;
  @ViewChild('litioAssistant') litioAssistant?: LitioAssistant;
  private applicationIdsSeen = new Set<number>();
  private applicationPollTimer: ReturnType<typeof setInterval> | null = null;
  private applicationToastTimer: ReturnType<typeof setTimeout> | null = null;
  private workspaceTourTimer: ReturnType<typeof setTimeout> | null = null;
  private workspaceTourTargetElement: HTMLElement | null = null;
  private readonly workspaceTourAutoShowLimit = 5;
  private previousFocusedElement: HTMLElement | null = null;
  private mobileNavPreviousFocusedElement: HTMLElement | null = null;
  private bodyScrollLocked = false;

  private sourceCanvas?: ElementRef<HTMLCanvasElement>;
  private sourceChart?: Chart;
  @ViewChild('sourcePerformanceCanvas', { static: false })
  set sourceCanvasRef(value: ElementRef<HTMLCanvasElement> | undefined) {
    if (!value && this.sourceChart) {
      this.sourceChart.destroy();
      this.sourceChart = undefined;
    }
    this.sourceCanvas = value;
    if (value && this.activeTab === 'overview') {
      setTimeout(() => this.renderChart(), 0);
    }
  }
  rolesData: any;
  private readonly statusUpdateListener = () => {
    this.fetchData();
    this.fetchRoleCatalog();
  };

  constructor(private http: HttpClient, private dialog: MatDialog) {}  // Inject HttpClient and MatDialog

  private hasData(): boolean {
    return (
      this.scheduledCandidates.length > 0 ||
      this.shortlistedCandidates.length > 0 ||
      this.hiredCandidates.length > 0 ||
      this.rejectedCandidates.length > 0
    );
  }

  ngAfterViewInit(): void {
    // Render chart after view is initialized
    setTimeout(() => this.renderChart(), 0);
  }


  ngOnChanges(changes: SimpleChanges): void {
    if (changes['candidatesData']) {
      // Ensure view/canvas is ready before rendering
      setTimeout(() => this.renderChart(), 0);
    }
  }


  beforeViewInit(): void {
    this.scheduledCandidates = [];
    this.completedCandidates = [];
    this.cancelledCandidates = [];
    this.shortlistedCandidates = [];
    this.hiredCandidates = [];
    this.assessmentPendingCandidates = [];
    this.autoScreeningScheduledCandidates = [];
    this.rejectedCandidates = [];
    this.assessmentCompletedCandidates = [];
  }
  ngOnInit(): void {
    this.syncWorkspaceStateFromLocation();
    window.addEventListener('candidate-status-updated', this.statusUpdateListener as EventListener);
    window.addEventListener('global-data-refresh', this.statusUpdateListener as EventListener);
    this.fetchData();
    this.fetchRoleCatalog();
    this.fetchRecruiterApplicationFeed(true);
    this.applicationPollTimer = window.setInterval(() => this.fetchRecruiterApplicationFeed(false), 20000);
    this.showPagination = (this.candidatesData?.length || 0) > this.pageSize;
  }

  setActiveTab(tab: 'overview' | 'recruiters' | 'evaluators' | 'candidates' | 'ai-talent-pool' | 'activity' | 'analytics', options?: { roleId?: string | null; updateUrl?: boolean }): void {
    if (this.activeTab === 'overview' && tab !== 'overview' && this.sourceChart) {
      this.sourceChart.destroy();
      this.sourceChart = undefined;
    }
    this.activeTab = tab;
    if (tab === 'ai-talent-pool') {
      this.talentPoolRoleId = options?.roleId ?? this.talentPoolRoleId;
    } else if (!options?.roleId) {
      this.talentPoolRoleId = null;
    }
    window.dispatchEvent(new CustomEvent('dashboard-tab-change', { detail: { tab } }));
    if (options?.updateUrl !== false) {
      this.updateWorkspaceUrl();
    }
    if (tab === 'overview') {
      setTimeout(() => this.renderChart(), 0);
    }
  }

  openAiTalentPool(roleId?: string | number | null): void {
    const nextRoleId = roleId ? String(roleId) : null;
    this.setActiveTab('ai-talent-pool', { roleId: nextRoleId, updateUrl: true });
  }

  openLitioAssistant(): void {
    this.litioAssistant?.open();
  }

  get litioAssistantContext(): LitioAssistantContext {
    const candidate = this.evaluationSummaryCandidate || this.activeCandidateContext || this.activeWorkflowContext?.candidate || null;
    const roleContext = this.activeRoleContext || this.getRoleContext(this.talentPoolRoleId || candidate?.role_id || null);
    const context: LitioAssistantContext = {
      page: 'Recruiter dashboard',
      section: this.getDashboardSectionLabel(this.activeTab),
      activeTab: this.activeTab,
      openModal: this.getLitioOpenModalContext(),
      vacancyId: roleContext?.id || candidate?.role_id || null,
      vacancyTitle: roleContext?.title || candidate?.role || '',
      candidateId: candidate?.id || null,
      candidateName: candidate?.name || candidate?.candidate_name || '',
      candidateStage: this.normalizeStatus(candidate?.status || candidate?.current_stage),
      evaluationStatus: this.getLitioEvaluationStatus(),
    };

    Object.keys(context).forEach((key) => {
      const typedKey = key as keyof LitioAssistantContext;
      const value = context[typedKey];
      if (value === '' || value === null || value === undefined) {
        delete context[typedKey];
      }
    });
    return context;
  }

  ngOnDestroy(): void {
    window.removeEventListener('candidate-status-updated', this.statusUpdateListener as EventListener);
    window.removeEventListener('global-data-refresh', this.statusUpdateListener as EventListener);
    if (this.applicationPollTimer) {
      clearInterval(this.applicationPollTimer);
      this.applicationPollTimer = null;
    }
    if (this.applicationToastTimer) {
      clearTimeout(this.applicationToastTimer);
      this.applicationToastTimer = null;
    }
    if (this.workspaceTourTimer) {
      clearTimeout(this.workspaceTourTimer);
      this.workspaceTourTimer = null;
    }
    this.clearWorkspaceTourTarget();
    this.unlockBodyScroll();
  }

  @HostListener('document:keydown', ['$event'])
  handleDocumentKeydown(event: KeyboardEvent): void {
    if (this.workspaceTourOpen) {
      if (event.key === 'Escape') {
        event.preventDefault();
        this.closeWorkspaceTour();
        return;
      }
      if (event.key === 'ArrowRight' || event.key === 'Enter') {
        event.preventDefault();
        this.nextWorkspaceTourStep();
        return;
      }
      if (event.key === 'ArrowLeft') {
        event.preventDefault();
        this.previousWorkspaceTourStep();
        return;
      }
    }

    if (event.key === 'Escape') {
      if (this.evaluationReportOpen) {
        event.preventDefault();
        this.closeDetailedEvaluationReport();
        return;
      }
      if (this.evaluationSummaryModalOpen) {
        event.preventDefault();
        this.closeEvaluationSummaryModal();
        return;
      }
      if (this.activeInterviewLinkMenuId !== null) {
        event.preventDefault();
        this.closeInterviewLinkMenu();
        return;
      }
      if (this.candidateFilterMenuOpen) {
        event.preventDefault();
        this.closeCandidateFilterMenu();
        return;
      }
      if (this.companyDetailsModalOpen) {
        event.preventDefault();
        this.closeCompanyDetailsModal();
        return;
      }
      if (this.pendingRequestsModalOpen) {
        event.preventDefault();
        this.closePendingRequestsModal();
        return;
      }
      if (this.mobileNavOpen) {
        event.preventDefault();
        this.closeMobileNav(true);
      }
      return;
    }

    if (event.key !== 'Tab') {
      return;
    }

    if (this.companyDetailsModalOpen) {
      this.trapFocus(event, this.companyModalCardRef?.nativeElement);
      return;
    }

    if (this.pendingRequestsModalOpen) {
      this.trapFocus(event, this.pendingRequestsDialogRef?.nativeElement);
      return;
    }

    if (this.mobileNavOpen) {
      this.trapFocus(event, this.mobileNavPanelRef?.nativeElement);
    }
  }

  @HostListener('document:click', ['$event'])
  handleDocumentClick(event: MouseEvent): void {
    const target = event.target as HTMLElement | null;
    if (target?.closest('.candidate-filter-control')) {
      return;
    }
    this.closeCandidateFilterMenu();
    if (target?.closest('.interview-link-menu')) {
      return;
    }
    this.closeInterviewLinkMenu();
  }

  @HostListener('window:resize')
  handleWindowResize(): void {
    if (window.innerWidth >= 1180 && this.mobileNavOpen) {
      this.closeMobileNav(false);
    }

    if (this.workspaceTourOpen) {
      this.updateWorkspaceTourLayout();
    }
  }

  @HostListener('window:scroll')
  handleWindowScroll(): void {
    if (this.workspaceTourOpen) {
      this.updateWorkspaceTourLayout();
    }
  }

  toggleMobileNav(): void {
    if (this.mobileNavOpen) {
      this.closeMobileNav(true);
      return;
    }

    this.mobileNavPreviousFocusedElement = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : this.mobileNavToggleButtonRef?.nativeElement || null;
    this.mobileNavOpen = true;
    this.updateBodyScrollLock();
    setTimeout(() => this.focusFirstElement(this.mobileNavPanelRef?.nativeElement), 0);
  }

  closeMobileNav(restoreFocus = false): void {
    if (!this.mobileNavOpen) {
      return;
    }
    this.mobileNavOpen = false;
    this.updateBodyScrollLock();
    if (restoreFocus) {
      setTimeout(() => {
        (this.mobileNavPreviousFocusedElement || this.mobileNavToggleButtonRef?.nativeElement)?.focus();
      }, 0);
    }
  }

  // Example API call
  fetchData(): void {
    this.loading = true;
    const apiBaseUrl = getApiBaseUrl();
    this.http.get(apiBaseUrl + '/dashboard-data/') // Replace with your API URL
      .pipe(
        timeout(this.apiTimeoutMs),
        takeUntilDestroyed(this.destroyRef),
        catchError(error => {
          console.error('Error fetching data', error);
          this.loading = false;
          this.shellLoading = false;
          return of([]); // Return empty array on error
        })
      )
      .subscribe(response => {
        this.data = response;
        this.loading = false;
        this.shellLoading = false;
        if(this.data?.Data){
          this.candidatesData = (this.data.Data.candidate_data || []).map((c: any) => ({
            ...c,
            status: this.normalizeStatus(c?.status)
          }));
          const loginUserData = this.data.Data.login_user || {};
          this.loginUser = loginUserData.name || loginUserData.full_name || loginUserData.username || '';
          this.loginUserEmail = loginUserData.email || loginUserData.username || '';
          this.loginUserRole = loginUserData.role || '';
          this.companyProfile = this.data.Data.company_profile || null;
          writeWorkspaceContext({
            loginUserName: this.loginUser,
            loginUserRole: this.loginUserRole,
            companyProfile: this.companyProfile,
          });
        this.hydrateCompanyViewModel();
        this.lastUpdatedAt = new Date();
        this.assign_status();
        this.queueWorkspaceTour();
        // Render chart after data is loaded and view is initialized
        setTimeout(() => this.renderChart(), 5);
      }
    });
  }

  get currentWorkspaceTourStep(): WorkspaceTourStep | null {
    return this.workspaceTourSteps[this.workspaceTourIndex] || null;
  }

  get isWorkspaceTourFirstStep(): boolean {
    return this.workspaceTourIndex === 0;
  }

  get isWorkspaceTourLastStep(): boolean {
    return this.workspaceTourIndex >= this.workspaceTourSteps.length - 1;
  }

  replayWorkspaceTour(): void {
    this.startWorkspaceTour(true);
  }

  private queueWorkspaceTour(): void {
    if (typeof window === 'undefined' || this.workspaceTourOpen || !this.shouldAutoShowWorkspaceTour()) {
      return;
    }
    if (this.workspaceTourTimer) {
      clearTimeout(this.workspaceTourTimer);
    }
    this.workspaceTourTimer = window.setTimeout(() => {
      this.workspaceTourTimer = null;
      this.startWorkspaceTour(false);
    }, 450);
  }

  private buildWorkspaceTourSteps(): WorkspaceTourStep[] {
    return [
      {
        key: 'welcome',
        title: `Getting Started with Shortlistii`,
        description: `Welcome, ${this.loginUser || 'there'}. This guide walks through the core operating flow for your workspace so your team can move from role creation to candidate review with a clean, consistent process.`
      },
      {
        key: 'post-job',
        title: '1. Post a Job',
        description: 'Create the job posting first to establish the hiring requirement, align stakeholders on the role, and anchor every downstream candidate and interview action to the correct opening.',
        selector: '[data-tour="post-job"]',
        padding: 10
      },
      {
        key: 'assign-candidate',
        title: '2. Assign Candidate',
        description: 'Add candidates into the active workflow and attach them to the appropriate recruiter, evaluator, and role so ownership and pipeline tracking stay clean from the start.',
        selector: '[data-tour="assign-candidate"]',
        padding: 10
      },
      {
        key: 'schedule-interview',
        title: '3. Schedule Interview',
        description: 'Schedule interviews here to move shortlisted candidates into an execution-ready stage with clear timing, interviewer alignment, and workflow visibility.',
        selector: '[data-tour="schedule-interview"]',
        padding: 10
      },
      {
        key: 'candidate-details',
        title: '4. Review Candidate Summary',
        description: 'Use the candidate details view to review profile context, role mapping, evaluation signal, and the next recommended action before advancing the candidate.',
        selector: '[data-tour="candidate-details"]',
        padding: 12
      },
      {
        key: 'pending-requests',
        title: '5. Check Pending Requests',
        description: 'Monitor inbound candidate requests here and review them before they are admitted into the structured hiring workflow.',
        selector: '[data-tour="pending-requests"]',
        padding: 10
      },
      {
        key: 'bulk-assign',
        title: '6. Bulk Assign Evaluators',
        description: 'Use bulk assignment to distribute evaluators across multiple candidates efficiently when hiring volume increases or a role moves into active review.',
        selector: '[data-tour="bulk-assign"]',
        padding: 10
      },
      {
        key: 'export-data',
        title: '7. Download or Export Data',
        description: 'Export the current candidate view in a shareable format whenever you need to circulate pipeline status, archive activity, or prepare stakeholder reporting.',
        selector: '[data-tour="export-data"]',
        padding: 10
      }
    ].filter((step) => !step.selector || !!document.querySelector(step.selector));
  }

  private startWorkspaceTour(force: boolean): void {
    if (typeof window === 'undefined') {
      return;
    }
    if (!force && !this.shouldAutoShowWorkspaceTour()) {
      return;
    }
    if (this.activeTab !== 'overview') {
      this.setActiveTab('overview', { updateUrl: false });
    }
    this.closePendingRequestsModal();
    this.closeInterviewLinkMenu();
    this.workspaceTourSteps = this.buildWorkspaceTourSteps();
    if (!this.workspaceTourSteps.length) {
      return;
    }
    if (!force) {
      this.incrementWorkspaceTourAutoShowCount();
    }
    this.workspaceTourOpen = true;
    this.workspaceTourIndex = 0;
    this.syncWorkspaceTourStep();
  }

  closeWorkspaceTour(): void {
    this.workspaceTourOpen = false;
    this.workspaceTourSpotlightStyle = {};
    this.workspaceTourTooltipStyle = {};
    this.clearWorkspaceTourTarget();
  }

  previousWorkspaceTourStep(): void {
    if (!this.workspaceTourOpen || this.isWorkspaceTourFirstStep) {
      return;
    }
    this.workspaceTourIndex -= 1;
    this.syncWorkspaceTourStep();
  }

  nextWorkspaceTourStep(): void {
    if (!this.workspaceTourOpen) {
      return;
    }
    if (this.isWorkspaceTourLastStep) {
      this.closeWorkspaceTour();
      return;
    }
    this.workspaceTourIndex += 1;
    this.syncWorkspaceTourStep();
  }

  private syncWorkspaceTourStep(): void {
    const step = this.currentWorkspaceTourStep;
    if (!step) {
      this.closeWorkspaceTour();
      return;
    }
    this.clearWorkspaceTourTarget();
    if (!step.selector) {
      window.scrollTo({ top: 0, behavior: 'smooth' });
      window.setTimeout(() => this.updateWorkspaceTourLayout(), 80);
      return;
    }
    const target = document.querySelector(step.selector) as HTMLElement | null;
    if (!target) {
      this.nextWorkspaceTourStep();
      return;
    }
    target.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'center' });
    window.setTimeout(() => this.updateWorkspaceTourLayout(), 220);
  }

  private updateWorkspaceTourLayout(): void {
    const step = this.currentWorkspaceTourStep;
    if (!step) {
      return;
    }
    if (!step.selector) {
      this.workspaceTourSpotlightStyle = {};
      this.workspaceTourTooltipStyle = {
        width: 'min(360px, calc(100vw - 32px))',
        left: '50%',
        top: '50%',
        transform: 'translate(-50%, -50%)'
      };
      return;
    }

    const target = document.querySelector(step.selector) as HTMLElement | null;
    if (!target) {
      return;
    }
    this.setWorkspaceTourTarget(target);

    const rect = target.getBoundingClientRect();
    const padding = step.padding ?? 12;
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;
    const tooltipWidth = Math.min(360, viewportWidth - 32);
    const tooltipHeight = viewportWidth <= 720 ? 224 : 212;
    const spotlightTop = Math.max(8, rect.top - padding);
    const spotlightLeft = Math.max(8, rect.left - padding);
    const spotlightWidth = Math.min(viewportWidth - spotlightLeft - 8, rect.width + padding * 2);
    const spotlightHeight = Math.min(viewportHeight - spotlightTop - 8, rect.height + padding * 2);

    this.workspaceTourSpotlightStyle = {
      top: `${spotlightTop}px`,
      left: `${spotlightLeft}px`,
      width: `${spotlightWidth}px`,
      height: `${spotlightHeight}px`
    };

    if (viewportWidth <= 720) {
      this.workspaceTourTooltipStyle = {
        width: `${tooltipWidth}px`,
        left: '50%',
        bottom: '16px',
        transform: 'translateX(-50%)'
      };
      return;
    }

    const preferredTop = rect.bottom + 18;
    const fallbackTop = rect.top - tooltipHeight - 18;
    const top = preferredTop + tooltipHeight < viewportHeight - 16
      ? preferredTop
      : Math.max(16, fallbackTop);
    const centeredLeft = rect.left + (rect.width / 2) - (tooltipWidth / 2);
    const left = Math.max(16, Math.min(centeredLeft, viewportWidth - tooltipWidth - 16));

    this.workspaceTourTooltipStyle = {
      width: `${tooltipWidth}px`,
      left: `${left}px`,
      top: `${top}px`
    };
  }

  private get workspaceTourStorageKey(): string {
    const nameKey = (this.loginUser || 'workspace-user')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '') || 'workspace-user';
    const roleKey = (this.loginUserRole || 'workspace').toLowerCase();
    return `smartInterview.workspaceTour.v2.${roleKey}.${nameKey}`;
  }

  private getWorkspaceTourAutoShowCount(): number {
    if (typeof window === 'undefined' || !this.loginUser) {
      return this.workspaceTourAutoShowLimit;
    }
    const rawCount = window.localStorage.getItem(this.workspaceTourStorageKey);
    const parsedCount = Number.parseInt(rawCount || '0', 10);
    if (Number.isNaN(parsedCount) || parsedCount < 0) {
      return 0;
    }
    return parsedCount;
  }

  private shouldAutoShowWorkspaceTour(): boolean {
    return this.getWorkspaceTourAutoShowCount() < this.workspaceTourAutoShowLimit;
  }

  private incrementWorkspaceTourAutoShowCount(): void {
    if (typeof window === 'undefined' || !this.loginUser) {
      return;
    }
    const nextCount = Math.min(this.workspaceTourAutoShowLimit, this.getWorkspaceTourAutoShowCount() + 1);
    window.localStorage.setItem(this.workspaceTourStorageKey, String(nextCount));
  }

  private setWorkspaceTourTarget(target: HTMLElement): void {
    if (this.workspaceTourTargetElement === target) {
      return;
    }
    this.clearWorkspaceTourTarget();
    this.workspaceTourTargetElement = target;
    this.workspaceTourTargetElement.classList.add('workspace-tour-target');
  }

  private clearWorkspaceTourTarget(): void {
    if (!this.workspaceTourTargetElement) {
      return;
    }
    this.workspaceTourTargetElement.classList.remove('workspace-tour-target');
    this.workspaceTourTargetElement = null;
  }

  fetchRoleCatalog(): void {
    const apiBaseUrl = getApiBaseUrl();
    this.http.get(apiBaseUrl + '/get-role-list/')
      .pipe(
        timeout(this.apiTimeoutMs),
        takeUntilDestroyed(this.destroyRef),
        catchError(error => {
          console.error('Error fetching role catalog', error);
          return of([]);
        })
      )
      .subscribe((response: any) => {
        if (response?.RoleData) {
          this.roleCatalog = response.RoleData;
        }
      });
  }

  fetchRecruiterApplicationFeed(initialLoad = false): void {
    const apiBaseUrl = getApiBaseUrl();
    this.http.get<any>(`${apiBaseUrl}/recruiter-application-feed/`)
      .pipe(
        timeout(this.apiTimeoutMs),
        takeUntilDestroyed(this.destroyRef),
        catchError(error => {
          console.error('Error fetching recruiter application feed', error);
          return of(null);
        })
      )
      .subscribe(response => {
        if (!response?.Success || !response?.Data) {
          return;
        }

        const applications = (response.Data.applications || []) as RecruiterApplicationItem[];
        const nextIds = new Set<number>(applications.map((item: any) => Number(item.id)).filter((id: number) => Number.isFinite(id)));
        const newItems = initialLoad || !this.applicationFeedLoaded
          ? []
          : applications.filter((item: any) => !this.applicationIdsSeen.has(Number(item.id)));

        this.recruiterApplications = applications;
        this.recruiterApplicationsCount = Number(response.Data.count || applications.length || 0);
        this.applicationIdsSeen = nextIds;
        this.applicationFeedLoaded = true;

        if (newItems.length) {
          const first = newItems[0];
          const moreCount = newItems.length - 1;
          this.showApplicationToast(
            moreCount > 0
              ? `${first.candidate_name} applied for ${first.vacancy_role}. ${moreCount} more application(s) just arrived.`
              : `${first.candidate_name} applied for ${first.vacancy_role}.`
          );
        }
      });
  }

  showApplicationToast(message: string): void {
    this.applicationToastMessage = message;
    this.applicationToastOpen = true;
    if (this.applicationToastTimer) {
      clearTimeout(this.applicationToastTimer);
    }
    this.applicationToastTimer = window.setTimeout(() => {
      this.applicationToastOpen = false;
    }, 5000);
  }

  dismissApplicationToast(): void {
    this.applicationToastOpen = false;
    if (this.applicationToastTimer) {
      clearTimeout(this.applicationToastTimer);
      this.applicationToastTimer = null;
    }
  }

  openPendingRequestsModal(): void {
    this.pendingRequestsModalOpen = true;
    this.activePendingActionKey = 'all';
    this.activePendingActionItemId = null;
    this.updateBodyScrollLock();
    setTimeout(() => this.focusFirstElement(this.pendingRequestsDialogRef?.nativeElement), 0);
  }

  closePendingRequestsModal(): void {
    this.pendingRequestsModalOpen = false;
    this.activePendingActionItemId = null;
    this.updateBodyScrollLock();
  }

  get pendingActionCards(): PendingActionCard[] {
    const list = this.candidatesData || [];
    const now = new Date();
    return [
      {
        key: 'new-applications',
        label: 'New Applications',
        helper: 'Needs review',
        icon: 'ph ph-user-plus',
        count: this.recruiterApplicationsCount || this.recruiterApplications.length || 0,
        tone: 'purple'
      },
      {
        key: 'assessment-pending',
        label: 'Assessment Pending',
        helper: 'Awaiting results',
        icon: 'ph ph-clipboard-text',
        count: this.assessmentPendingCandidates?.length || 0,
        tone: 'orange'
      },
      {
        key: 'overdue-feedback',
        label: 'Overdue Feedback',
        helper: 'Requires action',
        icon: 'ph ph-clock-countdown',
        count: this.getOverdueFeedbackCandidates(list, now).length,
        tone: 'pink'
      },
      {
        key: 'interviews-pending',
        label: 'Interviews Pending',
        helper: 'To be scheduled',
        icon: 'ph ph-calendar-plus',
        count: this.getUnscheduledShortlistedCandidates(list).length,
        tone: 'blue'
      },
      {
        key: 'offer-decisions',
        label: 'Offer Decisions',
        helper: 'Awaiting decision',
        icon: 'ph ph-seal-check',
        count: this.getPendingOfferCandidates(list, now).length,
        tone: 'green'
      }
    ];
  }

  get activePendingAction(): PendingActionCard {
    if (this.activePendingActionKey === 'all') {
      return {
        key: 'all',
        label: 'All Actions',
        helper: 'Needs attention',
        icon: 'ph ph-list-checks',
        count: this.pendingActionTotalCount,
        tone: 'blue'
      };
    }
    return this.pendingActionCards.find((card) => card.key === this.activePendingActionKey) || this.pendingActionCards[0];
  }

  get pendingActionTotalCount(): number {
    return this.pendingActionCards.reduce((total, card) => total + (card.count || 0), 0);
  }

  trackByOverviewKpiCard(_index: number, card: OverviewKpiCard): string {
    return card.key;
  }

  get filteredPendingActionItems(): PendingActionListItem[] {
    const term = this.pendingRequestsSearch.trim().toLowerCase();
    let items = this.pendingActionItemsFor(this.activePendingActionKey);
    if (term) {
      items = items.filter((item) =>
        [item.name, item.email, item.phone, item.role, item.status, item.source, item.actionLabel]
          .map((value) => (value || '').toString().toLowerCase())
          .some((value) => value.includes(term))
      );
    }
    if (this.pendingActionPriorityFilter !== 'all') {
      items = items.filter((item) => this.pendingActionPriorityTone(item) === this.pendingActionPriorityFilter);
    }
    return this.sortPendingActionItems(items);
  }

  get selectedPendingActionItem(): PendingActionListItem | null {
    const items = this.filteredPendingActionItems;
    return items.find((item) => item.id === this.activePendingActionItemId) || items[0] || null;
  }

  selectPendingAction(key: PendingActionKey): void {
    this.activePendingActionKey = key;
    this.activePendingActionItemId = null;
  }

  focusPendingActionItem(item: PendingActionListItem): void {
    this.activePendingActionItemId = item.id;
  }

  openPendingActionItem(item: PendingActionListItem): void {
    if (item.kind === 'application') {
      this.openCandidatePublicProfile(item.raw);
      return;
    }
    this.profileUpdate(item.raw);
  }

  reviewPendingActionItem(item: PendingActionListItem): void {
    if (item.actionKey === 'overdue-feedback' && item.kind === 'candidate') {
      this.closePendingRequestsModal();
      this.openEvaluationSummary(item.raw);
      return;
    }
    this.openPendingActionItem(item);
  }

  schedulePendingActionItem(item: PendingActionListItem): void {
    if (item.kind === 'candidate') {
      this.openWorkflowAction('schedule', item.raw);
    }
  }

  pendingActionElapsedLabel(item: PendingActionListItem | null): string {
    if (!item?.date) {
      return 'Not scheduled';
    }
    const date = new Date(item.date);
    if (Number.isNaN(date.getTime())) {
      return 'Date pending';
    }
    const diffMs = Date.now() - date.getTime();
    const absMs = Math.abs(diffMs);
    const minute = 60 * 1000;
    const hour = 60 * minute;
    const day = 24 * hour;
    if (absMs < hour) {
      const minutes = Math.max(1, Math.round(absMs / minute));
      return `${minutes} min${minutes === 1 ? '' : 's'} ${diffMs >= 0 ? 'ago' : 'from now'}`;
    }
    if (absMs < day) {
      const hours = Math.round(absMs / hour);
      return `${hours} hour${hours === 1 ? '' : 's'} ${diffMs >= 0 ? 'ago' : 'from now'}`;
    }
    const days = Math.round(absMs / day);
    return `${days} day${days === 1 ? '' : 's'} ${diffMs >= 0 ? 'ago' : 'from now'}`;
  }

  pendingActionPriorityLabel(item: PendingActionListItem | null): string {
    if (!item) {
      return 'Normal';
    }
    if (item.actionKey === 'overdue-feedback' || item.actionKey === 'new-applications') {
      return 'High';
    }
    if (item.actionKey === 'interviews-pending' || item.actionKey === 'assessment-pending') {
      return 'Medium';
    }
    return 'Low';
  }

  pendingActionPriorityTone(item: PendingActionListItem | null): string {
    return this.pendingActionPriorityLabel(item).toLowerCase();
  }

  pendingActionSource(item: PendingActionListItem | null): string {
    return item?.source || 'Dashboard pipeline';
  }

  pendingActionExperience(item: PendingActionListItem | null): string {
    const raw = item?.raw || {};
    const value = raw.experience_years ?? raw.total_experience ?? raw.years_experience ?? raw.experience;
    if (value === null || value === undefined || value === '') {
      return 'Not captured';
    }
    const numericValue = Number(value);
    if (Number.isFinite(numericValue)) {
      return `${numericValue} Year${numericValue === 1 ? '' : 's'}`;
    }
    return String(value);
  }

  pendingActionLocation(item: PendingActionListItem | null): string {
    const raw = item?.raw || {};
    const parts = [raw.location || raw.current_location || raw.city, raw.state, raw.country]
      .map((value) => (value || '').toString().trim())
      .filter(Boolean);
    return parts.length ? Array.from(new Set(parts)).join(', ') : 'Not captured';
  }

  pendingActionResumeName(item: PendingActionListItem | null): string {
    const raw = item?.raw || {};
    const explicitName = raw.resume_name || raw.resume_filename || raw.file_name;
    if (explicitName) {
      return explicitName;
    }
    return `${(item?.name || 'Candidate').replace(/\s+/g, '_')}_Profile.pdf`;
  }

  pendingActionResumeMeta(item: PendingActionListItem | null): string {
    const raw = item?.raw || {};
    return raw.resume_size || raw.file_size || (this.pendingActionResumePdfUrl(item) ? 'PDF download available' : 'Profile record');
  }

  downloadPendingActionResumePdf(item: PendingActionListItem, event?: Event): void {
    event?.preventDefault();
    event?.stopPropagation();

    const pdfUrl = this.pendingActionResumePdfUrl(item);
    if (!pdfUrl) {
      this.toast.showError('Resume unavailable', 'Public resume PDF is not available for this candidate yet.');
      return;
    }

    const link = document.createElement('a');
    link.href = pdfUrl;
    link.target = '_blank';
    link.rel = 'noopener';
    link.download = '';
    document.body.appendChild(link);
    link.click();
    link.remove();
  }

  pendingActionResumePdfUrl(item: PendingActionListItem | null): string {
    const raw = item?.raw || {};
    const explicitUrl = raw.public_resume_pdf_url || raw.public_profile_pdf_url || raw.resume_pdf_url || raw.pdf_url;
    if (explicitUrl) {
      return String(explicitUrl);
    }

    const publicProfileUrl = raw.public_profile_url || raw.public_resume_url || raw.public_profile;
    if (!publicProfileUrl) {
      return '';
    }

    const normalizedUrl = String(publicProfileUrl);
    try {
      const url = new URL(normalizedUrl, window.location.origin);
      const normalizedPath = url.pathname.replace(/\/$/, '');
      if (normalizedPath.endsWith('/download-pdf')) {
        url.pathname = `${normalizedPath}/`;
      } else {
        url.pathname = `${normalizedPath}/download-pdf/`;
      }
      return url.toString();
    } catch {
      const trimmedUrl = normalizedUrl.replace(/\/$/, '');
      return trimmedUrl.endsWith('/download-pdf') ? `${trimmedUrl}/` : `${trimmedUrl}/download-pdf/`;
    }
  }

  private sortPendingActionItems(items: PendingActionListItem[]): PendingActionListItem[] {
    const priorityRank: Record<string, number> = { high: 0, medium: 1, low: 2, normal: 3 };
    return [...items].sort((left, right) => {
      if (this.pendingActionSortKey === 'priority') {
        const rankDiff = (priorityRank[this.pendingActionPriorityTone(left)] ?? 3) - (priorityRank[this.pendingActionPriorityTone(right)] ?? 3);
        if (rankDiff !== 0) {
          return rankDiff;
        }
      }
      const leftTime = this.pendingActionTimestamp(left);
      const rightTime = this.pendingActionTimestamp(right);
      if (this.pendingActionSortKey === 'oldest') {
        return leftTime - rightTime;
      }
      return rightTime - leftTime;
    });
  }

  private pendingActionTimestamp(item: PendingActionListItem): number {
    const timestamp = item.date ? new Date(item.date).getTime() : Number.NaN;
    return Number.isNaN(timestamp) ? 0 : timestamp;
  }

  private pendingActionItemsFor(key: PendingActionKey): PendingActionListItem[] {
    const list = this.candidatesData || [];
    const now = new Date();
    switch (key) {
      case 'all':
        return [
          ...this.pendingActionItemsFor('new-applications'),
          ...this.pendingActionItemsFor('assessment-pending'),
          ...this.pendingActionItemsFor('overdue-feedback'),
          ...this.pendingActionItemsFor('interviews-pending'),
          ...this.pendingActionItemsFor('offer-decisions')
        ];
      case 'new-applications':
        return (this.recruiterApplications || []).map((application) => this.mapApplicationToPendingActionItem(application));
      case 'assessment-pending':
        return (this.assessmentPendingCandidates || []).map((candidate: any) => this.mapCandidateToPendingActionItem(candidate, key));
      case 'overdue-feedback':
        return this.getOverdueFeedbackCandidates(list, now).map((candidate: any) => this.mapCandidateToPendingActionItem(candidate, key));
      case 'interviews-pending':
        return this.getUnscheduledShortlistedCandidates(list).map((candidate: any) => this.mapCandidateToPendingActionItem(candidate, key));
      case 'offer-decisions':
        return this.getPendingOfferCandidates(list, now).map((candidate: any) => this.mapCandidateToPendingActionItem(candidate, key));
    }
  }

  private mapApplicationToPendingActionItem(application: RecruiterApplicationItem): PendingActionListItem {
    const card = this.getPendingActionCard('new-applications');
    return {
      id: `application-${application.id}`,
      actionKey: 'new-applications',
      actionLabel: card.label,
      actionIcon: card.icon,
      actionTone: card.tone,
      name: application.candidate_name || 'Unnamed candidate',
      email: application.candidate_email || 'No email',
      phone: application.candidate_phone || 'Phone pending',
      role: application.vacancy_role || 'Role pending',
      status: application.status_label || 'New Application',
      date: application.applied_at,
      source: application.source || 'Career Portal',
      kind: 'application',
      raw: application
    };
  }

  private mapCandidateToPendingActionItem(candidate: any, key: PendingActionKey): PendingActionListItem {
    const card = this.getPendingActionCard(key);
    return {
      id: `candidate-${candidate?.id || key}-${candidate?.email || candidate?.name || ''}`,
      actionKey: key,
      actionLabel: card.label,
      actionIcon: card.icon,
      actionTone: card.tone,
      name: candidate?.name || candidate?.candidate_name || 'Unnamed candidate',
      email: candidate?.email || candidate?.candidate_email || 'No email',
      phone: candidate?.phone || candidate?.candidate_phone || 'Phone pending',
      role: candidate?.role || candidate?.role_title || candidate?.vacancy_role || 'Role pending',
      status: candidate?.status || card.label,
      date: candidate?.date || candidate?.updated_at || candidate?.created_at || '',
      source: candidate?.recruiter || candidate?.interviewer || 'Dashboard pipeline',
      kind: 'candidate',
      raw: candidate
    };
  }

  private getPendingActionCard(key: PendingActionKey): PendingActionCard {
    if (key === 'all') {
      return this.activePendingAction;
    }
    return this.pendingActionCards.find((card) => card.key === key) || this.pendingActionCards[0];
  }

  openCompanyDetailsModal(): void {
    if (this.companyProfile) {
      this.previousFocusedElement = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      this.companyEditMode = false;
      this.selectedCompanyLogoFile = null;
      this.selectedCompanyLogoName = '';
      this.activeCompanyProfileTab = 'details';
      this.populateCompanyForm();
      this.companyDetailsModalOpen = true;
      this.updateBodyScrollLock();
      setTimeout(() => this.companyModalCloseButtonRef?.nativeElement.focus(), 0);
    }
  }

  closeCompanyDetailsModal(): void {
    if (!this.companyDetailsModalOpen) {
      return;
    }
    this.companyDetailsModalOpen = false;
    this.companyEditMode = false;
    this.activeCompanyProfileTab = 'details';
    this.companySaving = false;
    this.selectedCompanyLogoFile = null;
    this.selectedCompanyLogoName = '';
    this.updateBodyScrollLock();
    setTimeout(() => this.previousFocusedElement?.focus(), 0);
  }

  get filteredRecruiterApplications(): RecruiterApplicationItem[] {
    const term = this.pendingRequestsSearch.trim().toLowerCase();
    if (!term) {
      return this.recruiterApplications;
    }
    return this.recruiterApplications.filter((application) =>
      [
        application.candidate_name,
        application.candidate_email,
        application.candidate_phone,
        application.vacancy_role,
        application.status_label,
      ]
        .map((value) => (value || '').toString().toLowerCase())
        .some((value) => value.includes(term))
    );
  }

  getCandidateInitials(name: string): string {
    const parts = (name || '').trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return 'NA';
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
  }

  openCandidatePublicProfile(application: RecruiterApplicationItem): void {
    if (!application.public_profile_url) {
      return;
    }
    window.open(application.public_profile_url, '_blank', 'noopener');
  }

  reviewPendingRequest(application: RecruiterApplicationItem, action: 'accept' | 'reject'): void {
    if (!application?.id || application.actionLoading) {
      return;
    }

    application.actionLoading = true;
    const apiBaseUrl = getApiBaseUrl();
    const body = new URLSearchParams();
    body.set('application_id', String(application.id));
    body.set('action', action);

    this.http.post<any>(`${apiBaseUrl}/review-recruiter-application/`, body.toString(), {
      headers: new HttpHeaders({ 'Content-Type': 'application/x-www-form-urlencoded' })
    })
      .pipe(
        catchError((error) => {
          console.error(`Error trying to ${action} request`, error);
          application.actionLoading = false;
          this.toast.showError('Request update failed', `Unable to ${action === 'accept' ? 'approve' : 'reject'} this request right now.`);
          return of(null);
        })
      )
      .subscribe((response) => {
        if (!response?.Success) {
          application.actionLoading = false;
          this.toast.showError('Request update failed', response?.Error || `Unable to ${action === 'accept' ? 'approve' : 'reject'} this request right now.`);
          return;
        }

        application.removing = true;
        this.toast.showSuccess(
          action === 'accept' ? 'Request approved' : 'Request rejected',
          `${application.candidate_name} has been ${action === 'accept' ? 'moved into the hiring workflow' : 'updated successfully'}.`
        );
        window.setTimeout(() => {
          this.recruiterApplications = this.recruiterApplications.filter((item) => item.id !== application.id);
          this.recruiterApplicationsCount = this.recruiterApplications.length;
          this.applicationIdsSeen.delete(application.id);
          if (action === 'accept') {
            this.fetchData();
          }
        }, 240);
      });
  }

  profileUpdate(candidate?: any): void {
    this.activeCandidateContext = candidate || null;
    const dialogRef = this.dialog.open(CandidateProfile, {
      width: 'min(1220px, 95vw)',
      maxWidth: '95vw',
      maxHeight: '92vh',
      panelClass: 'candidate-profile-dialog',
      autoFocus: false,
      data: { candidate }
    });

     dialogRef.afterClosed().subscribe((result: any) => {
      this.activeCandidateContext = null;
      if (!result) return;

      if (result.action === 'updated' && result.candidate) {
        this.updateCandidateData(result.candidate);
      }

      if (result.action === 'openRole' && result.candidate?.role_id) {
        this.openRoldeModal(result.candidate.role_id);
      }
    });
  }

  updateCandidateData(updatedCandidate: any) {
    // Full refresh keeps all dashboard sections in sync (cards, lists, charts, role snapshot).
    this.fetchData();
    this.fetchRoleCatalog();
  }

  assign_status(){
  const list = this.candidatesData || [];

  this.scheduledCandidates = list.filter((c: any) => this.normalizeStatus(c?.status) === 'scheduled' && !this.isAutoScreeningCandidate(c));
  this.completedCandidates = list.filter((c: any) => this.normalizeStatus(c?.status) === 'completed');
  this.cancelledCandidates = list.filter((c: any) => this.normalizeStatus(c?.status) === 'cancelled');
  this.shortlistedCandidates = list.filter((c: any) => {
    const s = this.normalizeStatus(c?.status);
    return s === 'shortlisted' || s === 'offer made' || s === 'offer accepted';
  });
  this.hiredCandidates = list.filter((c: any) => {
    const s = this.normalizeStatus(c?.status);
    return s === 'completed' || s === 'hired';
  });
  this.assessmentPendingCandidates = list.filter((c: any) =>
    this.normalizeStatus(c?.status) === 'assessment pending' && !this.isAutoScreeningCandidate(c)
  );
  this.autoScreeningScheduledCandidates = list.filter((c: any) =>
    this.normalizeStatus(c?.status) === 'auto screening scheduled'
    || (this.normalizeStatus(c?.status) === 'assessment pending' && this.isAutoScreeningCandidate(c))
    || (this.normalizeStatus(c?.status) === 'scheduled' && this.isAutoScreeningCandidate(c))
  );
  this.rejectedCandidates = list.filter((c: any) => this.normalizeStatus(c?.status) === 'rejected');
  this.assessmentCompletedCandidates = list.filter((c: any) => this.normalizeStatus(c?.status) === 'assessment completed');
  }

  trackCandidate(index: number, candidate: any): any {
  return candidate && candidate.id ? candidate.id : index;
  }

  private getSearchFilteredCandidates(): any[] {
    const search = this.searchQuery.trim().toLowerCase();
    const list = this.candidatesData || [];
    if (!search) {
      return list;
    }
    return list.filter((c: any) =>
      [c?.name, c?.status, c?.recruiter, c?.role, c?.interviewer]
        .map((v: any) => (v || '').toString().toLowerCase())
        .some((v: string) => v.includes(search))
    );
  }

  getPipelineCount(status: string): number {
    const normalizedStatus = this.normalizeStatus(status);
    return this.getSearchFilteredCandidates().filter((c: any) => {
      return this.matchesPipelineStatus(c, normalizedStatus);
    }).length;
  }

  get totalPages(): number {
  const statusFiltered = this.selectedStatus
    ? this.candidatesData.filter((c: any) => this.matchesPipelineStatus(c, this.normalizeStatus(this.selectedStatus)))
    : this.candidatesData;

  const searchFiltered = this.getSearchFilteredCandidates();
  const data = statusFiltered.filter((c: any) => searchFiltered.includes(c));

  return Math.ceil((data?.length || 0) / this.pageSize) || 1;
}

get paginatedCandidates() {
  const start = (this.currentPage - 1) * this.pageSize;
  return this.candidatesData.slice(start, start + this.pageSize);
}

nextPage() {
  if (this.currentPage < this.totalPages) {
    this.currentPage++;
  }
}

  prevPage() {
  if (this.currentPage > 1) {
    this.currentPage--;
  }
}

  private trapFocus(event: KeyboardEvent, container?: HTMLElement): void {
    if (!container) {
      return;
    }

    const focusableElements = this.getFocusableElements(container);
    if (!focusableElements.length) {
      event.preventDefault();
      container.focus();
      return;
    }

    const first = focusableElements[0];
    const last = focusableElements[focusableElements.length - 1];
    const activeElement = document.activeElement as HTMLElement | null;

    if (!activeElement || !container.contains(activeElement)) {
      event.preventDefault();
      (event.shiftKey ? last : first).focus();
      return;
    }

    if (event.shiftKey && activeElement === first) {
      event.preventDefault();
      last.focus();
      return;
    }

    if (!event.shiftKey && activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  private getFocusableElements(container: HTMLElement): HTMLElement[] {
    return Array.from(
      container.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'
      )
    ).filter((element) => {
      if (element.hasAttribute('hidden')) {
        return false;
      }
      if (element.getAttribute('aria-hidden') === 'true') {
        return false;
      }
      return element.offsetParent !== null || element === document.activeElement;
    });
  }

  private focusFirstElement(container?: HTMLElement): void {
    if (!container) {
      return;
    }
    const [firstElement] = this.getFocusableElements(container);
    (firstElement || container).focus();
  }

  private updateBodyScrollLock(): void {
    const shouldLock = this.mobileNavOpen || this.companyDetailsModalOpen || this.evaluationSummaryModalOpen || this.evaluationReportOpen || this.pendingRequestsModalOpen;
    if (shouldLock && !this.bodyScrollLocked) {
      document.body.style.overflow = 'hidden';
      this.bodyScrollLocked = true;
      return;
    }
    if (!shouldLock && this.bodyScrollLocked) {
      this.unlockBodyScroll();
    }
  }

  private unlockBodyScroll(): void {
    document.body.style.overflow = '';
    this.bodyScrollLocked = false;
  }

  private syncWorkspaceStateFromLocation(): void {
    const url = new URL(window.location.href);
    const requestedTab = this.normalizeDashboardTab(url.searchParams.get('tab') || url.hash.replace(/^#/, ''));
    const requestedRoleId = (url.searchParams.get('role') || '').trim() || null;

    if (requestedTab) {
      this.activeTab = requestedTab;
    }
    if (requestedTab === 'ai-talent-pool') {
      this.talentPoolRoleId = requestedRoleId;
    }
  }

  private normalizeDashboardTab(value: string): 'overview' | 'recruiters' | 'evaluators' | 'candidates' | 'ai-talent-pool' | 'activity' | 'analytics' | null {
    const normalized = (value || '').trim().toLowerCase();
    switch (normalized) {
      case 'overview':
      case 'dashboard':
        return 'overview';
      case 'recruiters':
        return 'recruiters';
      case 'evaluators':
        return 'evaluators';
      case 'candidates':
        return 'candidates';
      case 'talent':
      case 'talent-pool':
      case 'ai-talent-pool':
        return 'ai-talent-pool';
      case 'activity':
        return 'activity';
      case 'analytics':
        return 'analytics';
      default:
        return null;
    }
  }

  private getDashboardSectionLabel(tab: string): string {
    switch (tab) {
      case 'overview':
        return 'Overview';
      case 'recruiters':
        return 'Recruiters';
      case 'evaluators':
        return 'Evaluators';
      case 'candidates':
        return 'Candidates';
      case 'ai-talent-pool':
        return 'AI Talent Pool';
      case 'activity':
        return 'Activity';
      case 'analytics':
        return 'Analytics';
      default:
        return 'Dashboard';
    }
  }

  private getLitioOpenModalContext(): string {
    if (this.evaluationSummaryModalOpen || this.evaluationSummaryLoading) {
      return 'candidate_evaluation_summary';
    }
    if (this.evaluationReportOpen) {
      return 'candidate_evaluation_report';
    }
    if (this.activeCandidateContext) {
      return 'candidate_profile';
    }
    if (this.activeRoleContext) {
      return 'vacancy_detail';
    }
    if (this.activeWorkflowContext) {
      return `workflow_${this.activeWorkflowContext.mode}`;
    }
    if (this.addUserModalContext) {
      return this.addUserModalContext === 'role' ? 'create_vacancy' : 'create_candidate';
    }
    if (this.pendingRequestsModalOpen) {
      return 'pending_requests';
    }
    if (this.companyDetailsModalOpen) {
      return 'company_profile';
    }
    return '';
  }

  private getLitioEvaluationStatus(): string {
    if (this.evaluationSummaryLoading) {
      return 'loading';
    }
    if (this.evaluationSummaryModalOpen || this.evaluationReportOpen) {
      return this.evaluationSummary.available ? 'available' : 'unavailable';
    }
    return '';
  }

  private getRoleContext(roleId: any): { id: string; title: string } | null {
    const id = this.stringValue(roleId);
    if (!id) {
      return null;
    }
    const role = [
      ...(this.roleCatalog || []),
      ...(this.rolesData || []),
    ].find((item: any) => this.stringValue(item?.id) === id);
    return {
      id,
      title: this.stringValue(role?.name || role?.role || role?.title),
    };
  }

  private updateWorkspaceUrl(): void {
    const url = new URL(window.location.href);
    if (this.activeTab === 'overview') {
      url.searchParams.delete('tab');
      url.searchParams.delete('role');
    } else {
      url.searchParams.set('tab', this.activeTab);
      if (this.activeTab === 'ai-talent-pool' && this.talentPoolRoleId) {
        url.searchParams.set('role', this.talentPoolRoleId);
      } else {
        url.searchParams.delete('role');
      }
    }
    url.hash = '';
    window.history.replaceState({}, '', `${url.pathname}${url.search}`);
  }

  get filteredCandidates() {
  const statusFiltered = this.selectedStatus
  ? this.candidatesData.filter((c: any) => this.matchesPipelineStatus(c, this.normalizeStatus(this.selectedStatus)))
  : this.candidatesData;

  const searchFiltered = this.getSearchFilteredCandidates();
  const attentionFiltered = this.applyAttentionFilter(statusFiltered || []);
  const data = attentionFiltered.filter((c: any) => searchFiltered.includes(c));

  this.showPagination = (data?.length || 0) > this.pageSize;
  const totalPages = Math.ceil((data?.length || 0) / this.pageSize);
  if (this.currentPage > totalPages) {
    this.currentPage = totalPages || 1; // fallback to page 1 if empty
  }

  const start = (this.currentPage - 1) * this.pageSize;
  return data?.slice(start, start + this.pageSize);
  }

setStatusFilter(status: string | null, shouldScroll = false) {
  this.selectedStatus = status;
  this.attentionFilter = null;
  this.currentPage = 1; // reset to first page after filtering
  if (shouldScroll) {
    this.scrollToCandidatePipeline();
  }
}

toggleCandidateFilterMenu(event?: Event): void {
  event?.preventDefault();
  event?.stopPropagation();
  this.closeInterviewLinkMenu();
  this.candidateFilterMenuOpen = !this.candidateFilterMenuOpen;
}

closeCandidateFilterMenu(): void {
  this.candidateFilterMenuOpen = false;
}

applyCandidateFilter(status: string | null): void {
  this.setStatusFilter(status);
  this.closeCandidateFilterMenu();
}

isCandidateFilterSelected(status: string | null): boolean {
  return this.normalizeStatus(this.selectedStatus) === this.normalizeStatus(status);
}

get selectedCandidateFilterLabel(): string {
  return this.candidateFilterOptions.find((option) => this.isCandidateFilterSelected(option.value))?.label || 'Custom Filter';
}

getCandidateFilterOptionCount(status: string | null): number {
  if (!status) {
    return this.getSearchFilteredCandidates().length;
  }
  return this.getPipelineCount(status);
}

clearSearch(): void {
  this.searchQuery = '';
  this.currentPage = 1;
}

openEvaluationSummary(candidate: any, event?: Event): void {
  event?.preventDefault();
  event?.stopPropagation();

  const candidateId = Number(candidate?.id || 0);
  if (!candidateId) {
    this.toast.showError('Evaluation unavailable', 'Candidate interview details are missing.');
    return;
  }

  if (this.evaluationSummaryLoading && this.evaluationSummaryLoadingCandidateId === candidateId) {
    return;
  }

  this.closeInterviewLinkMenu();
  this.evaluationSummaryCandidate = candidate;
  this.evaluationSummaryModalOpen = false;
  this.evaluationReportOpen = false;
  this.evaluationSummaryLoading = true;
  this.evaluationSummaryLoadingCandidateId = candidateId;
  this.evaluationSummaryError = '';
  this.evaluationSummary = this.createEmptyEvaluationSummary();
  this.resetEvaluationReportViewData();
  this.qaExpandedKeys.clear();
  this.updateBodyScrollLock();

  const apiBaseUrl = getApiBaseUrl();
  this.http.get<any>(`${apiBaseUrl}/candidate-evaluation-summary/${candidateId}/`)
    .pipe(
      timeout(this.apiTimeoutMs),
      takeUntilDestroyed(this.destroyRef),
      catchError((error) => {
        console.error('Error loading candidate evaluation summary', error);
        if (this.evaluationSummaryLoadingCandidateId === candidateId) {
          this.evaluationSummaryLoading = false;
          this.evaluationSummaryLoadingCandidateId = null;
          this.evaluationSummaryCandidate = null;
          this.toast.showError('Evaluation summary unavailable', 'Unable to load the evaluation summary right now.');
        }
        return of(null);
      })
    )
    .subscribe((response) => {
      if (this.evaluationSummaryLoadingCandidateId !== candidateId) {
        return;
      }
      this.evaluationSummaryLoading = false;
      this.evaluationSummaryLoadingCandidateId = null;
      if (!response?.Success) {
        this.evaluationSummaryCandidate = null;
        this.toast.showError('Evaluation summary unavailable', response?.Error || 'Unable to load the evaluation summary right now.');
        return;
      }
      this.evaluationSummary = this.normalizeEvaluationPayload(response?.Data?.evaluation_summary || {});
      this.rebuildEvaluationReportViewData();
      this.evaluationSummaryModalOpen = true;
      this.updateBodyScrollLock();
    });
}

closeEvaluationSummaryModal(): void {
  if (!this.evaluationSummaryModalOpen) {
    return;
  }
  this.evaluationSummaryModalOpen = false;
  this.evaluationReportOpen = false;
  this.evaluationSummaryLoading = false;
  this.evaluationSummaryLoadingCandidateId = null;
  this.evaluationSummaryError = '';
  this.evaluationSummaryCandidate = null;
  this.evaluationSummary = this.createEmptyEvaluationSummary();
  this.resetEvaluationReportViewData();
  this.qaExpandedKeys.clear();
  this.updateBodyScrollLock();
}

openDetailedEvaluationReport(event?: Event): void {
  event?.preventDefault();
  event?.stopPropagation();
  if (!this.hasEvaluationReportContent()) {
    return;
  }
  this.evaluationReportGeneratedAt = new Date();
  const reportHtml = this.buildDetailedEvaluationReportHtml();
  const reportUrl = window.URL.createObjectURL(new Blob([reportHtml], { type: 'text/html;charset=utf-8' }));
  const reportWindow = window.open(reportUrl, '_blank', 'noopener,noreferrer');
  if (!reportWindow) {
    window.URL.revokeObjectURL(reportUrl);
    this.toast.showError('Popup blocked', 'Allow popups for this site to open the detailed report in a new tab.');
    return;
  }
  setTimeout(() => window.URL.revokeObjectURL(reportUrl), 60000);
  this.evaluationSummaryModalOpen = false;
  this.updateBodyScrollLock();
}

closeDetailedEvaluationReport(): void {
  if (!this.evaluationReportOpen) {
    return;
  }
  this.evaluationReportOpen = false;
  this.evaluationSummaryCandidate = null;
  this.evaluationSummary = this.createEmptyEvaluationSummary();
  this.resetEvaluationReportViewData();
  this.qaExpandedKeys.clear();
  this.updateBodyScrollLock();
}

downloadDetailedEvaluationReport(event?: Event): void {
  event?.preventDefault();
  event?.stopPropagation();
  setTimeout(() => window.print(), 0);
}

private buildDetailedEvaluationReportHtml(): string {
  const score = this.getEvaluationScorePercent();
  const scoreDegrees = score * 3.6;
  const decisionColor = this.getReportDecisionColor();
  const candidateName = this.evaluationSummary.candidate_name || this.evaluationSummaryCandidate?.name || 'Candidate';
  const roleTitle = this.evaluationSummary.role_title || this.evaluationSummaryCandidate?.role || 'Not captured';
  const profilePhotoUrl = this.getEvaluationProfilePhotoUrl();
  const candidateInitials = this.escapeHtml(this.getEvaluationCandidateInitials());
  const avatarClass = profilePhotoUrl ? 'report-avatar has-photo' : 'report-avatar';
  const avatarHtml = `
    ${profilePhotoUrl ? `<img src="${this.escapeHtmlAttr(profilePhotoUrl)}" alt="${this.escapeHtmlAttr(candidateName)}" onerror="this.parentElement.classList.add('is-fallback')">` : ''}
    <span class="report-avatar-fallback">${candidateInitials}</span>
  `;
  const metaHtml = this.evaluationReportMetaItems.map((item) => `
    <article>
      <span class="report-meta-icon">${this.reportIconForLabel(item.label)}</span>
      <div><small>${this.escapeHtml(item.label)}</small><strong>${this.escapeHtml(item.value)}</strong></div>
    </article>
  `).join('');
  const insightsHtml = this.evaluationReportInsightCards.map((item) => `
    <article class="report-insight-card is-${this.escapeHtmlAttr(item.tone)}">
      <span>${this.reportIconForLabel(item.label)}</span>
      <strong>${this.escapeHtml(item.value)}</strong>
      <small>${this.escapeHtml(item.helper)}</small>
    </article>
  `).join('');
  const skillsHtml = this.evaluationReportSkillRows.map((row) => {
    const normalizedScore = row.score === null ? null : (row.score <= 5 ? row.score * 20 : row.score);
    const width = normalizedScore === null ? 0 : Math.max(0, Math.min(100, normalizedScore));
    return `
      <article class="report-skill-row">
        <strong>${this.escapeHtml(row.label)}</strong>
        <span>${normalizedScore === null ? 'N/A' : `${this.escapeHtml(this.formatScore(normalizedScore))}/100`}</span>
        <div class="report-skill-meter"><i class="is-${this.escapeHtmlAttr(row.tone)}" style="width:${width}%"></i></div>
        <em class="is-${this.escapeHtmlAttr(row.tone)}">${this.escapeHtml(row.proficiency)}</em>
      </article>
    `;
  }).join('');
  const progressHtml = this.evaluationReportProgressSteps.map((step, index) => `
    <article class="${step.active ? 'is-active' : ''}">
      <span>${step.active ? '&#10003;' : index + 1}</span>
      <strong>${this.escapeHtml(step.label)}</strong>
      <small>${this.escapeHtml(step.state)}</small>
      <em>${this.escapeHtml(step.score)}</em>
    </article>
  `).join('');
  const qaHtml = this.evaluationReportQaRecords.length
    ? `
      <div class="report-qa-table">
        <div class="report-qa-head"><span>#</span><span>Question</span><span>Skill</span><span>Answer Quality</span></div>
        ${this.evaluationReportQaRecords.map((record, index) => {
          const quality = this.deriveAnswerQuality(record);
          const qualityClass = this.getQualityClass(quality);
          return `
          <article class="report-qa-row ${this.isWeakQuality(quality) ? 'is-warning' : ''}">
            <span>${this.escapeHtml(String(record.turn_index || index + 1))}</span>
            <div class="report-qa-copy">
              <p class="report-question">${this.escapeHtml(record.question_text || 'Question unavailable')}</p>
              <div class="report-qa-detail">
                <strong>Candidate Answer</strong>
                <p>${this.escapeHtml(record.candidate_answer || 'No answer captured')}</p>
              </div>
              <div class="report-qa-detail is-expected">
                <strong>Expected Signal</strong>
                <p>${this.escapeHtml(record.expected_signal || 'Expected signal not captured')}</p>
              </div>
            </div>
            <strong>${this.escapeHtml(record.skill || 'Not captured')}</strong>
            <em class="${this.escapeHtmlAttr(qualityClass)}">${this.escapeHtml(quality)}</em>
          </article>
        `;
        }).join('')}
      </div>
    `
    : '<p>No Q/A records captured for this evaluation.</p>';
  const profileHtml = this.evaluationReportProfileItems.map((item) => `
    <article class="report-profile-row">
      <span>${this.reportIconForLabel(item.label)}</span>
      <div><strong>${this.escapeHtml(item.label)}</strong><small>${this.escapeHtml(item.value)}</small></div>
    </article>
  `).join('');
  const coreSkillsHtml = (this.evaluationCoreSkillTags.length ? this.evaluationCoreSkillTags : ['No skills captured'])
    .map((skill) => `<span>${this.escapeHtml(skill)}</span>`)
    .join('');
  const educationHtml = this.evaluationEducationItems.map((item) => `
    <article class="report-education-item"><strong>${this.escapeHtml(item.title)}</strong><small>${this.escapeHtml(item.detail || 'Not captured')}</small></article>
  `).join('');
  const attentionHtml = this.evaluationNeedAttentionItems.map((item) => `<li>${this.escapeHtml(item)}</li>`).join('');
  const actionsHtml = this.evaluationActionItems.map((item) => `<label><span>&#10003;</span><small>${this.escapeHtml(item)}</small></label>`).join('');
  const aptitudeHtml = this.renderAptitudeReportSection();

  return `<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>${this.escapeHtml(candidateName)} - Candidate Evaluation Report</title>
  <style>${this.getDetailedReportStaticCss()}</style>
</head>
<body>
  <main class="report-page">
    <div class="report-accent-bar"></div>
    <header class="report-header">
      <div>
        ${this.getReportLogoHtml()}
        <p>Candidate Evaluation Report</p>
      </div>
      <div class="report-generated">
        <span>Generated on ${this.escapeHtml(this.evaluationReportGeneratedAt.toLocaleString())}</span>
        <span>Report ID: ${this.escapeHtml(this.getEvaluationReportId())}</span>
      </div>
    </header>

    <section class="report-hero-grid">
      <article class="report-candidate-hero report-card">
        <div class="${avatarClass}">${avatarHtml}</div>
        <div class="report-candidate-copy">
          <h1>${this.escapeHtml(candidateName)}</h1>
          <strong>${this.escapeHtml(roleTitle)}</strong>
          <p>${this.escapeHtml(this.getExecutiveSummary())}</p>
        </div>
      </article>
      <article class="report-score-decision report-card">
        <div class="report-score-ring" style="background:conic-gradient(${decisionColor} 0deg ${scoreDegrees}deg, #e6eaf0 ${scoreDegrees}deg 360deg)">
          <div class="report-score-copy">
            <span>${this.escapeHtml(this.formatReportScore())}</span>
            <small>/100</small>
          </div>
        </div>
        <div class="report-decision-copy">
          <span>Decision</span>
          <strong class="is-${this.escapeHtmlAttr(this.getDecisionTone())}">${this.escapeHtml(this.getEvaluationDecisionLabel())}</strong>
          <hr>
          <span>Recommendation</span>
          <p>${this.escapeHtml(this.getEvaluationRecommendationText())}</p>
        </div>
      </article>
    </section>

    <section class="report-meta-strip report-card">${metaHtml}</section>

    <div class="report-body-grid">
      <section class="report-main-column">
        <article class="report-card report-section">
          <h2><span>▦</span> Executive Summary</h2>
          <p>${this.escapeHtml(this.getExecutiveSummary())}</p>
          <div class="report-evidence-grid">
            <div class="report-evidence-card is-strong">
              <h3>☝ Strongest Evidence</h3>
              <span>${this.escapeHtml(this.getEvidenceSkillLabel())}</span>
              <p>${this.escapeHtml(this.getStrongestEvidence())}</p>
            </div>
            <div class="report-evidence-card is-weak">
              <h3>☟ Weakest Evidence</h3>
              <span>${this.escapeHtml(this.getEvidenceSkillLabel(true))}</span>
              <p>${this.escapeHtml(this.getWeakestEvidence())}</p>
            </div>
          </div>
          <div class="report-guidance"><span>◎</span><p>${this.escapeHtml(this.evaluationSummary.hire_recommendation_reason || this.evaluationSummary.next_round_focus[0] || 'Review the captured evidence before confirming the next hiring action.')}</p></div>
        </article>

        <article class="report-card report-section">
          <h2><span>✥</span> Summary Insights</h2>
          <div class="report-insight-grid">${insightsHtml}</div>
        </article>

        <article class="report-card report-section">
          <h2><span>⚙</span> Skills Assessment</h2>
          <div class="report-skills-layout">
            <div class="report-mini-score-ring" style="background:conic-gradient(${decisionColor} 0deg ${scoreDegrees}deg, #e6eaf0 ${scoreDegrees}deg 360deg)">
              <div class="report-score-copy">
                <span>${this.escapeHtml(this.formatReportScore())}</span><small>/100</small>
              </div>
              <em>Overall Score</em>
            </div>
            <div class="report-skill-table">
              <div class="report-skill-head"><span>Skill Area</span><span>Score</span><span>Proficiency</span></div>
              ${skillsHtml}
            </div>
          </div>
        </article>

        <article class="report-card report-section">
          <h2><span>⌁</span> Evaluation Progress</h2>
          <div class="report-progress-line">${progressHtml}</div>
        </article>

        ${aptitudeHtml}

        <article class="report-card report-section">
          <h2><span>▣</span> Detailed Question & Answer Summary</h2>
          ${qaHtml}
        </article>
      </section>

      <aside class="report-sidebar">
        <article class="report-card report-section">
          <h2><span>♙</span> Candidate Profile</h2>
          ${profileHtml}
        </article>
        <article class="report-card report-section">
          <h2><span>✺</span> Core Skills</h2>
          <div class="report-chip-cloud">${coreSkillsHtml}</div>
        </article>
        <article class="report-card report-section">
          <h2><span>▱</span> Education</h2>
          ${educationHtml}
        </article>
        <article class="report-card report-section report-attention">
          <h2><span>△</span> Need Attention</h2>
          <ul>${attentionHtml}</ul>
        </article>
        <article class="report-card report-section report-actions-list">
          <h2><span>▤</span> Action Items</h2>
          ${actionsHtml}
        </article>
        <article class="report-card report-section report-actions-card">
          <h2><span>▣</span> Reports</h2>
          <button type="button" class="report-download-btn" onclick="window.print()">Detailed Report <span>⇩</span></button>
          <button type="button" class="report-close-btn" onclick="window.close()">Close</button>
        </article>
      </aside>
    </div>
    <footer class="report-footer"><span>◎ Shared through Shortlistii.com</span></footer>
  </main>
</body>
</html>`;
}

private getEvaluationProfilePhotoUrl(): string {
  return this.stringValue(
    this.evaluationSummary.profile_picture_data_url
    || this.evaluationSummary.evaluation_payload['profile_picture_data_url']
    || this.evaluationSummaryCandidate?.profile_picture_url
    || this.evaluationSummaryCandidate?.candidate_profile_picture_url
    || this.evaluationSummary.evaluation_payload['profile_picture_url']
    || this.evaluationSummary.evaluation_payload['candidate_profile_picture_url']
  );
}

private getReportLogoHtml(): string {
  return `
    <div class="shortlistii-logo shortlistii-navbar shortlistii-report-logo" aria-label="shortlistii.com">
      <span class="logo-text">shortlist</span>
      <span class="logo-ii" aria-hidden="true">
        <span class="person"><span class="head"></span><span class="body"></span><span class="tie"></span></span>
        <span class="person"><span class="head"></span><span class="body"></span><span class="tie"></span></span>
      </span>
    </div>
  `;
}

private reportIconForLabel(label: string): string {
  const normalized = this.normalizeEvaluationLabel(label);
  if (normalized.includes('role') || normalized.includes('experience') || normalized.includes('company')) return '▣';
  if (normalized.includes('stage') || normalized.includes('evaluation')) return '☷';
  if (normalized.includes('interview')) return '▻';
  if (normalized.includes('source') || normalized.includes('location')) return '◎';
  if (normalized.includes('email')) return '✉';
  if (normalized.includes('phone')) return '☏';
  if (normalized.includes('question')) return '?';
  if (normalized.includes('score')) return '◷';
  if (normalized.includes('fit')) return '▤';
  if (normalized.includes('signal')) return '✦';
  return '•';
}

private escapeHtml(value: unknown): string {
  return this.stringValue(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

private escapeHtmlAttr(value: unknown): string {
  return this.escapeHtml(value).replace(/`/g, '&#96;');
}

private escapeJsString(value: unknown): string {
  return this.stringValue(value)
    .replace(/\\/g, '\\\\')
    .replace(/'/g, "\\'")
    .replace(/\n/g, '\\n')
    .replace(/\r/g, '');
}

private getDetailedReportStaticCss(): string {
  return `
    * { box-sizing: border-box; }
    html, body { margin: 0; min-height: 100%; background: #e9eff7; color: #111a33; font-family: Inter, Arial, Helvetica, sans-serif; }
    body { padding: 24px; }
    .report-page { position: relative; width: min(1080px, 100%); margin: 0 auto; background: #fff; padding: 28px 30px 28px 44px; box-shadow: 0 24px 70px rgba(15, 23, 42, 0.14); }
    .report-accent-bar { position: absolute; left: 0; top: 0; bottom: 0; width: 8px; background: linear-gradient(180deg, #1d4ed8, #06b6d4, #10b981, #f59e0b); }
    .report-card { border: 1px solid #dce4ef; border-radius: 8px; background: #fff; box-shadow: 0 10px 26px rgba(15, 23, 42, 0.035); }
    .report-header { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: start; gap: 24px; margin-bottom: 18px; }
    .shortlistii-report-logo, .shortlistii-report-logo.shortlistii-logo { display: inline-flex; align-items: flex-end; gap: 0.015em; line-height: 1; text-decoration: none; height: 31px; }
    .shortlistii-report-logo .logo-text { font-family: Georgia, 'Times New Roman', serif; font-size: 1.7rem; font-weight: 700; letter-spacing: -0.045em; color: #101a32; display: inline-flex; align-items: center; line-height: 1; }
    .shortlistii-report-logo .logo-ii { display: inline-flex; align-items: center; gap: 0.025em; margin-left: .3em; margin-bottom: 0.2em; line-height: 1; font-size: 1.4rem; transform: none; transform-origin: bottom center; }
    .shortlistii-report-logo .person { position: relative; width: 0.36em; height: 0.84em; display: inline-block; flex: 0 0 auto; }
    .shortlistii-report-logo .person .head { position: absolute; top: 0; left: 50%; width: 0.27em; height: 0.27em; transform: translateX(-50%); border-radius: 50%; background: linear-gradient(180deg, #8fd0ff 0%, #5aa9ff 100%); box-shadow: 0 0 12px rgba(90,169,255,.18); }
    .shortlistii-report-logo .person .body { position: absolute; left: 50%; bottom: 0; width: 0.24em; height: 0.53em; transform: translateX(-50%); border-radius: 0.12em 0.12em 0.10em 0.10em; background: #101a32; box-shadow: 0 2px 6px rgba(0,0,0,.14); }
    .shortlistii-report-logo .person .tie { position: absolute; top: 0.30em; left: 50%; width: 0.08em; height: 0.30em; transform: translateX(-50%); background: linear-gradient(180deg, #9dd5ff 0%, #5aa9ff 100%); clip-path: polygon(50% 0%, 100% 18%, 72% 100%, 28% 100%, 0% 18%); }
    .report-header p, .report-generated span { margin: 7px 0 0; color: #4b5874; font-size: 0.82rem; font-weight: 600; }
    .report-generated { display: grid; gap: 4px; text-align: right; padding-top: 4px; }
    .report-hero-grid { display: grid; grid-template-columns: minmax(0, 1.65fr) minmax(320px, 0.85fr); gap: 14px; align-items: stretch; }
    .report-candidate-hero { display: grid; grid-template-columns: 132px minmax(0, 1fr); gap: 22px; align-items: center; min-height: 170px; padding: 18px; }
    .report-avatar { width: 132px; height: 132px; border-radius: 8px; overflow: hidden; background: linear-gradient(145deg, #edf4ff, #d8e6ff); display: grid; place-items: center; }
    .report-avatar img, .report-avatar-fallback { grid-area: 1 / 1; }
    .report-avatar img { width: 100%; height: 100%; object-fit: cover; display: block; }
    .report-avatar-fallback { color: #0b74c8; font-size: 3.1rem; font-weight: 900; letter-spacing: -0.04em; }
    .report-avatar.has-photo:not(.is-fallback) .report-avatar-fallback { display: none; }
    .report-avatar.has-photo.is-fallback img { display: none; }
    .report-candidate-copy { min-width: 0; }
    .report-candidate-copy h1 { margin: 0 0 8px; color: #111827; font-size: 1.72rem; line-height: 1.05; letter-spacing: 0; }
    .report-candidate-copy strong { display: block; color: #0057ff; font-size: 0.86rem; font-weight: 900; text-transform: uppercase; margin-bottom: 10px; }
    .report-candidate-copy p, .report-section p, .report-evidence-card p, .report-guidance p, .report-profile-row small, .report-education-item small, .report-attention li, .report-actions-list small { margin: 0; color: #25314d; font-size: 0.82rem; line-height: 1.55; overflow-wrap: anywhere; }
    .report-score-decision { display: grid; grid-template-columns: 132px minmax(0, 1fr); align-items: center; gap: 22px; padding: 18px 22px; min-height: 170px; }
    .report-score-ring, .report-mini-score-ring { position: relative; display: grid; place-items: center; border-radius: 50%; }
    .report-score-ring { width: 132px; height: 132px; }
    .report-score-ring::before, .report-mini-score-ring::before { content: ''; position: absolute; inset: 10px; border-radius: 50%; background: #fff; }
    .report-score-copy { position: relative; z-index: 1; display: grid; place-items: center; gap: 5px; line-height: 1; }
    .report-score-copy span { color: #111827; font-size: 2.15rem; font-weight: 900; line-height: 1; }
    .report-score-copy small { color: #111827; font-size: 0.95rem; font-weight: 900; line-height: 1; }
    .report-decision-copy span, .report-meta-strip small, .report-section h2, .report-skill-head span, .report-qa-head span { color: #111a33; font-size: 0.74rem; font-weight: 900; text-transform: uppercase; letter-spacing: 0.05em; }
    .report-decision-copy strong { display: block; margin: 8px 0 14px; color: #f59e0b; font-size: 1.35rem; font-weight: 900; text-transform: uppercase; }
    .report-decision-copy strong.is-success { color: #059669; } .report-decision-copy strong.is-danger { color: #dc2626; }
    .report-decision-copy hr { margin: 0 0 14px; border: 0; border-top: 1px solid #dfe6ef; }
    .report-decision-copy p { margin: 8px 0 0; color: #059669; font-size: 0.86rem; font-weight: 900; }
    .report-meta-strip { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 0; margin: 18px 0 14px; padding: 14px 16px; }
    .report-meta-strip article { display: grid; grid-template-columns: 32px minmax(0, 1fr); align-items: center; gap: 10px; min-width: 0; border-right: 1px solid #e4e9f1; padding: 0 14px; }
    .report-meta-strip article:first-child { padding-left: 0; } .report-meta-strip article:last-child { border-right: 0; padding-right: 0; }
    .report-meta-icon { color: #0057ff; font-size: 1.45rem; font-weight: 900; }
    .report-meta-strip strong { display: block; margin-top: 5px; color: #111827; font-size: 0.84rem; line-height: 1.35; overflow-wrap: anywhere; }
    .report-body-grid { display: grid; grid-template-columns: minmax(0, 2fr) minmax(305px, 0.95fr); align-items: start; gap: 14px; }
    .report-main-column, .report-sidebar { display: grid; gap: 14px; min-width: 0; }
    .report-section { display: grid; gap: 14px; padding: 16px; min-width: 0; }
    .report-section h2 { display: flex; align-items: center; gap: 9px; margin: 0; letter-spacing: 0.06em; }
    .report-section h2 span { color: #0057ff; font-size: 1rem; }
    .report-evidence-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
    .report-evidence-card { border-radius: 8px; padding: 14px; min-width: 0; }
    .report-evidence-card.is-strong { border: 1px solid #bbf7d0; background: linear-gradient(145deg, #effdf5, #f8fffb); }
    .report-evidence-card.is-weak { border: 1px solid #fecaca; background: linear-gradient(145deg, #fff1f2, #fffafa); }
    .report-evidence-card h3 { margin: 0 0 12px; color: #16a34a; font-size: 0.9rem; text-transform: uppercase; } .report-evidence-card.is-weak h3 { color: #ef4444; }
    .report-evidence-card > span, .report-chip-cloud span { display: inline-flex; width: fit-content; border-radius: 5px; background: #dbeafe; color: #0f3d7a; font-size: 0.68rem; font-weight: 900; padding: 5px 8px; margin-bottom: 10px; }
    .report-evidence-card.is-strong > span { background: #dcfce7; color: #047857; } .report-evidence-card.is-weak > span { background: #fee2e2; color: #dc2626; }
    .report-guidance { display: grid; grid-template-columns: 26px minmax(0, 1fr); align-items: center; gap: 10px; border: 1px solid #dbeafe; border-radius: 8px; background: #eff6ff; padding: 12px; color: #0057ff; }
    .report-insight-grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; }
    .report-insight-card { display: grid; grid-template-columns: 36px minmax(0, 1fr); column-gap: 10px; align-items: center; min-height: 74px; border: 1px solid #dfe6ef; border-radius: 8px; padding: 12px; }
    .report-insight-card > span { grid-row: span 2; display: grid; place-items: center; width: 36px; height: 36px; border-radius: 50%; background: rgba(0, 87, 255, 0.1); color: #0057ff; font-weight: 900; }
    .report-insight-card strong { color: #111827; font-size: 1.18rem; line-height: 1; overflow-wrap: anywhere; }
    .report-insight-card small { color: #4b5874; font-size: 0.68rem; line-height: 1.25; }
    .report-skills-layout { display: grid; grid-template-columns: 130px minmax(0, 1fr); gap: 22px; align-items: center; }
    .report-mini-score-ring { width: 118px; height: 118px; }
    .report-mini-score-ring em { position: absolute; top: calc(100% + 7px); color: #4b5874; font-size: 0.68rem; font-style: normal; white-space: nowrap; }
    .report-mini-score-ring .report-score-copy span { font-size: 1.9rem; }
    .report-skill-table { display: grid; gap: 0; min-width: 0; }
    .report-skill-head, .report-skill-row { display: grid; grid-template-columns: minmax(120px, 1fr) 78px minmax(110px, 1.35fr) 82px; align-items: center; gap: 12px; }
    .report-skill-head { padding-bottom: 8px; } .report-skill-row { min-height: 34px; border-top: 1px solid #e7ebf2; }
    .report-skill-row strong, .report-skill-row span { color: #111827; font-size: 0.75rem; overflow-wrap: anywhere; }
    .report-skill-row em { font-size: 0.7rem; font-style: normal; font-weight: 900; }
    .is-good { color: #059669; } .is-average { color: #f59e0b; } .is-warning { color: #c2410c; } .is-neutral { color: #64748b; }
    .report-skill-meter { height: 5px; border-radius: 999px; background: #e7ebf2; overflow: hidden; } .report-skill-meter i { display: block; height: 100%; border-radius: inherit; background: #0284c7; } .report-skill-meter i.is-good { background: #10b981; } .report-skill-meter i.is-average { background: #f59e0b; } .report-skill-meter i.is-warning { background: #ef4444; } .report-skill-meter i.is-neutral { background: #94a3b8; }
    .report-progress-line { position: relative; display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 8px; }
    .report-progress-line::before { content: ''; position: absolute; top: 19px; left: 8%; right: 8%; height: 2px; background: linear-gradient(90deg, #10b981, #38bdf8, #8b5cf6); }
    .report-progress-line article { position: relative; z-index: 1; display: grid; justify-items: center; gap: 6px; text-align: center; min-width: 0; }
    .report-progress-line article > span { display: grid; place-items: center; width: 38px; height: 38px; border-radius: 50%; background: #8b5cf6; color: #fff; font-size: 0.86rem; font-weight: 900; } .report-progress-line article.is-active > span { background: #10b981; }
    .report-progress-line strong { color: #111827; font-size: 0.72rem; line-height: 1.25; } .report-progress-line small, .report-progress-line em { color: #4b5874; font-size: 0.66rem; font-style: normal; }
    .report-aptitude-grid { display: grid; grid-template-columns: 132px minmax(0, 1fr); gap: 16px; align-items: start; }
    .report-aptitude-score { display: grid; justify-items: center; gap: 8px; border: 1px solid #dbeafe; border-radius: 8px; background: #f8fbff; padding: 14px; }
    .report-aptitude-score strong { color: #111827; font-size: 1.65rem; line-height: 1; }
    .report-aptitude-score span, .report-aptitude-score em { color: #4b5874; font-size: 0.72rem; font-style: normal; font-weight: 900; text-transform: uppercase; }
    .report-aptitude-score em.is-success { color: #059669; } .report-aptitude-score em.is-danger { color: #dc2626; } .report-aptitude-score em.is-warning { color: #b45309; }
    .report-aptitude-metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
    .report-aptitude-metrics article { border: 1px solid #e5eaf2; border-radius: 8px; padding: 10px; background: #fff; }
    .report-aptitude-metrics small { display: block; color: #4b5874; font-size: 0.68rem; font-weight: 900; text-transform: uppercase; }
    .report-aptitude-metrics strong { display: block; margin-top: 5px; color: #111827; font-size: 0.78rem; overflow-wrap: anywhere; }
    .report-aptitude-chips, .report-aptitude-integrity-flags { display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0; }
    .report-aptitude-chips span, .report-aptitude-integrity-flags span { border: 1px solid #fde68a; border-radius: 999px; background: #fffbeb; color: #92400e; font-size: 0.68rem; font-weight: 900; padding: 5px 8px; }
    .report-aptitude-table { display: grid; border: 1px solid #e5eaf2; border-radius: 8px; overflow: hidden; margin-top: 10px; }
    .report-aptitude-head, .report-aptitude-row { display: grid; grid-template-columns: minmax(150px, 1fr) 110px 74px 78px 92px; gap: 10px; align-items: center; padding: 9px 10px; }
    .report-aptitude-head { background: #f8fafc; color: #111a33; font-size: 0.68rem; font-weight: 900; text-transform: uppercase; }
    .report-aptitude-row { border-top: 1px solid #e7ebf2; color: #111827; font-size: 0.72rem; }
    .report-aptitude-row span, .report-aptitude-row strong { min-width: 0; overflow-wrap: anywhere; }
    .report-aptitude-integrity { border: 1px solid #dbeafe; border-radius: 8px; padding: 10px; color: #25314d; font-size: 0.78rem; line-height: 1.5; margin-top: 10px; background: #f8fbff; }
    .report-aptitude-integrity.is-warning { border-color: #fde68a; background: #fffbeb; }
    .report-aptitude-integrity strong { display: block; color: #111827; font-size: 0.78rem; margin-bottom: 3px; }
    .report-aptitude-integrity p { margin: 0; }
    .report-qa-table { display: grid; overflow: hidden; border: 1px solid #e5eaf2; border-radius: 8px; }
    .report-qa-head, .report-qa-row { display: grid; grid-template-columns: 34px minmax(0, 1fr) 130px 132px; gap: 12px; align-items: start; padding: 10px 12px; }
    .report-qa-head { background: #f8fafc; } .report-qa-row { border-top: 1px solid #e7ebf2; } .report-qa-row.is-warning { background: #fff1f2; }
    .report-qa-copy { display: grid; gap: 8px; min-width: 0; }
    .report-qa-row > span, .report-qa-row > strong, .report-qa-row p { margin: 0; color: #111827; font-size: 0.72rem; overflow-wrap: anywhere; }
    .report-question { font-weight: 800; }
    .report-qa-detail { display: grid; gap: 4px; border-left: 2px solid #dbeafe; padding-left: 10px; }
    .report-qa-detail.is-expected { border-left-color: #bbf7d0; }
    .report-qa-detail strong { color: #0057ff; font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.04em; }
    .report-qa-detail p { color: #34405c; }
    .report-qa-row em { justify-self: start; border-radius: 6px; background: #e0f2fe; font-size: 0.68rem; font-style: normal; font-weight: 900; padding: 7px 10px; }
    .report-qa-row em.is-good { background: #dcfce7; color: #047857; } .report-qa-row em.is-warning { background: #ffedd5; color: #c2410c; } .report-qa-row em.is-neutral { background: #e0f2fe; color: #075985; }
    .report-profile-row { display: grid; grid-template-columns: 22px minmax(0, 1fr); align-items: start; gap: 10px; }
    .report-profile-row > span { color: #0057ff; font-weight: 900; } .report-profile-row strong, .report-education-item strong { display: block; color: #111827; font-size: 0.78rem; } .report-profile-row small, .report-education-item small { display: block; margin-top: 3px; }
    .report-chip-cloud { display: flex; flex-wrap: wrap; gap: 8px; } .report-chip-cloud span { background: #eaf2ff; color: #26324f; margin: 0; }
    .report-education-item { display: grid; gap: 4px; border-left: 2px solid #e5eaf2; padding-left: 12px; }
    .report-attention ul { margin: 0; padding-left: 18px; }
    .report-actions-list { border-top: 1px solid #edf1f6; } .report-actions-list label { display: grid; grid-template-columns: 20px minmax(0, 1fr); gap: 8px; align-items: start; } .report-actions-list label > span { color: #10b981; font-weight: 900; }
    .report-download-btn, .report-close-btn { display: flex; align-items: center; justify-content: center; gap: 10px; width: 100%; min-height: 38px; border-radius: 6px; font-weight: 900; cursor: pointer; }
    .report-download-btn { border: 1px solid #0b63ff; background: linear-gradient(95deg, #1649e9, #0057ff); color: #fff; } .report-close-btn { border: 1px solid #0b63ff; background: #fff; color: #0057ff; }
    .report-footer { margin-top: 14px; color: #64748b; font-size: 0.78rem; }
    @media (max-width: 900px) { body { padding: 12px; } .report-page { padding: 22px 16px 22px 28px; } .report-header, .report-hero-grid, .report-body-grid, .report-meta-strip, .report-evidence-grid, .report-insight-grid, .report-skills-layout, .report-aptitude-grid, .report-aptitude-metrics { grid-template-columns: 1fr; } .report-generated { text-align: left; } .report-meta-strip article { border-right: 0; border-bottom: 1px solid #e4e9f1; padding: 10px 0; } .report-candidate-hero, .report-score-decision { grid-template-columns: 112px minmax(0, 1fr); } .report-avatar, .report-score-ring { width: 112px; height: 112px; } .report-progress-line { grid-template-columns: 1fr; } .report-progress-line::before { display: none; } .report-skill-head, .report-qa-head, .report-aptitude-head { display: none; } .report-skill-row, .report-aptitude-row { grid-template-columns: 1fr; gap: 6px; padding: 10px; } .report-qa-row { grid-template-columns: 28px minmax(0, 1fr); } .report-qa-row strong, .report-qa-row em { grid-column: 2; } }
    @media print { body { background: #fff; padding: 0; } .report-page { width: 210mm; min-height: 297mm; margin: 0; box-shadow: none; padding: 12mm 10mm 12mm 14mm; } .report-card, .report-section, .report-meta-strip article, .report-qa-row, .report-progress-line article { break-inside: avoid; } .report-actions-card { display: none; } }
  `;
}

private resetEvaluationReportViewData(): void {
  this.evaluationReportMetaItems = [];
  this.evaluationReportProfileItems = [];
  this.evaluationReportInsightCards = [];
  this.evaluationReportSkillRows = [];
  this.evaluationReportProgressSteps = [];
  this.evaluationFeedbackRows = [];
  this.evaluationFeedbackHighlights = [];
  this.evaluationCoreSkillTags = [];
  this.evaluationNeedAttentionItems = [];
  this.evaluationActionItems = [];
  this.evaluationEducationItems = [];
  this.evaluationReportQaRecords = [];
}

private rebuildEvaluationReportViewData(): void {
  this.evaluationReportSkillRows = this.getReportSkillRows();
  this.evaluationCoreSkillTags = this.getCoreSkillTags();
  this.evaluationReportMetaItems = this.getEvaluationMetaItems();
  this.evaluationReportProfileItems = this.getReportProfileItems();
  this.evaluationReportInsightCards = this.getReportInsightCards();
  this.evaluationReportProgressSteps = this.getReportProgressSteps();
  this.evaluationFeedbackRows = this.getFeedbackRows();
  this.evaluationFeedbackHighlights = this.getFeedbackHighlights();
  this.evaluationNeedAttentionItems = this.getNeedAttentionItems();
  this.evaluationActionItems = this.getActionItems();
  this.evaluationEducationItems = this.getEducationItems();
  this.evaluationReportQaRecords = this.evaluationSummary.question_answer_records.slice(0, 25);
}

isInterviewLinkMenuOpen(candidate: any): boolean {
  return this.activeInterviewLinkMenuId === Number(candidate?.id || 0);
}

getCandidateActionLink(candidate: any): string {
  return (candidate?.candidate_action_link || candidate?.interview_link || '').toString().trim();
}

getCandidateActionLinkType(candidate: any): 'aptitude' | 'interview' {
  return candidate?.candidate_action_link_type === 'aptitude' ? 'aptitude' : 'interview';
}

getCandidateActionLinkLabel(candidate: any): string {
  const label = (candidate?.candidate_action_link_label || '').toString().trim();
  if (label) {
    return label;
  }
  return this.getCandidateActionLinkType(candidate) === 'aptitude' ? 'Aptitude Test Link' : 'Interview Link';
}

getCandidateActionLinkIcon(candidate: any): string {
  return this.getCandidateActionLinkType(candidate) === 'aptitude' ? 'ph-clipboard-text' : 'ph-video-camera';
}

getCandidateActionCopySuccessTitle(candidate: any): string {
  return this.getCandidateActionLinkType(candidate) === 'aptitude' ? 'Aptitude link copied' : 'Interview link copied';
}

getCandidateActionCopyLabel(candidate: any): string {
  return this.getCandidateActionLinkType(candidate) === 'aptitude' ? 'Copy Aptitude Link' : 'Copy Interview Link';
}

getCandidateActionVisitLabel(candidate: any): string {
  return this.getCandidateActionLinkType(candidate) === 'aptitude' ? 'Open Aptitude Test' : 'Visit Interview Link';
}

getCandidateActionEmailLabel(candidate: any): string {
  if (this.resendingInterviewEmailId === Number(candidate?.id || 0)) {
    return 'Sending...';
  }
  return this.getCandidateActionLinkType(candidate) === 'aptitude' ? 'Send Schedule Email' : 'Send Email';
}

toggleInterviewLinkMenu(candidate: any, event?: Event): void {
  event?.preventDefault();
  event?.stopPropagation();
  if (!this.getCandidateActionLink(candidate)) {
    return;
  }
  const candidateId = Number(candidate?.id || 0);
  if (!candidateId) {
    return;
  }
  this.activeInterviewLinkMenuId = this.activeInterviewLinkMenuId === candidateId ? null : candidateId;
}

closeInterviewLinkMenu(): void {
  this.activeInterviewLinkMenuId = null;
}

copyInterviewLink(candidate: any, event?: Event): void {
  event?.preventDefault();
  event?.stopPropagation();
  const link = this.getCandidateActionLink(candidate);
  if (!link) {
    return;
  }

  const handleSuccess = () => {
    this.toast.showSuccess(this.getCandidateActionCopySuccessTitle(candidate), `${candidate?.name || 'Candidate'} link copied to clipboard.`);
    this.closeInterviewLinkMenu();
  };
  const handleFailure = () => {
    this.toast.showError('Copy failed', `Unable to copy the ${this.getCandidateActionLinkType(candidate)} link right now.`);
  };

  if (navigator?.clipboard?.writeText) {
    navigator.clipboard.writeText(link).then(handleSuccess).catch(() => {
      if (this.fallbackCopyToClipboard(link)) {
        handleSuccess();
        return;
      }
      handleFailure();
    });
    return;
  }

  if (this.fallbackCopyToClipboard(link)) {
    handleSuccess();
    return;
  }
  handleFailure();
}

visitInterviewLink(candidate: any, event?: Event): void {
  event?.preventDefault();
  event?.stopPropagation();
  const link = this.getCandidateActionLink(candidate);
  if (!link) {
    return;
  }
  window.open(link, '_blank', 'noopener');
  this.closeInterviewLinkMenu();
}

resendCandidateInterviewEmail(candidate: any, event?: Event): void {
  event?.preventDefault();
  event?.stopPropagation();

  const candidateId = Number(candidate?.id || 0);
  if (!candidateId || this.resendingInterviewEmailId === candidateId) {
    return;
  }

  this.resendingInterviewEmailId = candidateId;
  const apiBaseUrl = getApiBaseUrl();
  const body = new URLSearchParams();
  body.set('interview_id', String(candidateId));

  this.http.post<any>(`${apiBaseUrl}/resend-candidate-interview-email/`, body.toString(), {
    headers: new HttpHeaders({ 'Content-Type': 'application/x-www-form-urlencoded' })
  })
    .pipe(
      timeout(this.apiTimeoutMs),
      takeUntilDestroyed(this.destroyRef),
      catchError((error) => {
        console.error('Error resending candidate interview email', error);
        this.resendingInterviewEmailId = null;
        this.toast.showError('Email resend failed', 'Unable to resend the interview email right now.');
        return of(null);
      })
    )
    .subscribe((response) => {
      this.resendingInterviewEmailId = null;
      if (!response?.Success) {
        this.toast.showError('Email resend failed', response?.Error || 'Unable to resend the interview email right now.');
        return;
      }

      this.toast.showSuccess(
        'Interview email sent',
        `Interview link email was resent to ${candidate?.email || candidate?.name || 'the candidate'}.`
      );
      this.closeInterviewLinkMenu();
    });
}

formatRoleWithId(role: any, roleId?: any): string {
  const roleName = (role || '').toString().trim();
  const id = (roleId ?? '').toString().trim();
  if (!roleName) return id;
  return id ? `${roleName} - ${id}` : roleName;
}

get totalFilteredCandidatesCount(): number {
  const statusFiltered = this.selectedStatus
    ? (this.candidatesData || []).filter((c: any) => this.matchesPipelineStatus(c, this.normalizeStatus(this.selectedStatus)))
    : (this.candidatesData || []);
  const searchFiltered = this.getSearchFilteredCandidates();
  return this.applyAttentionFilter(statusFiltered).filter((c: any) => searchFiltered.includes(c)).length;
}

get openRolesCount(): number {
  const roles = new Set(
    (this.candidatesData || [])
      .map((c: any) => (c?.role || '').toString().trim())
      .filter((r: string) => !!r)
  );
  return roles.size;
}

get formattedLastUpdated(): string {
  return this.lastUpdatedAt.toLocaleString();
}

get companyDisplayName(): string {
  return this.companyDisplayNameText;
}

get companyInitials(): string {
  return this.companyInitialsText;
}

get companyMetaLine(): string {
  return this.companyMetaLineText;
}

get companyLocationLine(): string {
  return this.companyLocationLineText;
}

get companyOverviewItems(): Array<{ label: string; value: string }> {
  return this.companyOverviewItemsData;
}

get companyLinks(): Array<{ label: string; value: string; icon: string }> {
  return this.companyLinksData;
}

get hasCompanyContacts(): boolean {
  return this.companyContactsData.length > 0;
}

get companyContacts(): Array<{ label: string; value: string; icon: string }> {
  return this.companyContactsData;
}

formatCompanyLinkValue(value: string): string {
  const normalized = (value || '').trim();
  if (!normalized) return '';
  return normalized.replace(/^https?:\/\//i, '').replace(/\/$/, '');
}

formatCompanyChoice(value: string): string {
  return (value || '')
    .replace(/_/g, ' ')
    .split(' ')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

isMeaningfulCompanyValue(value: string | number | null | undefined): boolean {
  const normalized = (value ?? '').toString().trim();
  return !!normalized && normalized.toLowerCase() !== 'tbd';
}

get canEditCompanyProfile(): boolean {
  return this.loginUserRole === 'admin' && !!this.companyProfile;
}

toggleCompanyEditMode(): void {
  this.companyEditMode = !this.companyEditMode;
  if (this.companyEditMode) {
    this.populateCompanyForm();
  } else {
    this.selectedCompanyLogoFile = null;
    this.selectedCompanyLogoName = '';
  }
}

setCompanyProfileTab(tab: CompanyProfileTab): void {
  this.activeCompanyProfileTab = tab;
}

onCompanyLogoSelected(event: Event): void {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0] || null;
  this.selectedCompanyLogoFile = file;
  this.selectedCompanyLogoName = file?.name || '';
}

saveCompanyProfile(): void {
  if (!this.companyProfile || this.companySaving) {
    return;
  }

  this.companySaving = true;
  const apiBaseUrl = getApiBaseUrl();
  const formData = new FormData();
  const entries = Object.entries(this.companyForm) as Array<[keyof CompanyProfileFormData, string]>;
  for (const [key, value] of entries) {
    formData.append(key, value || '');
  }
  if (this.selectedCompanyLogoFile) {
    formData.append('logo', this.selectedCompanyLogoFile);
  }

  this.http.post<any>(`${apiBaseUrl}/update-company-profile/`, formData)
    .pipe(
      catchError((error) => {
        console.error('Error updating company profile', error);
        this.companySaving = false;
        this.toast.showError('Company profile update failed', 'Unable to save company details right now.');
        return of(null);
      })
    )
    .subscribe((response) => {
      this.companySaving = false;
      if (!response?.Success || !response?.Data) {
        this.toast.showError('Company profile update failed', response?.Error || 'Unable to save company details right now.');
        return;
      }
      this.companyProfile = response.Data as CompanyProfileData;
      this.hydrateCompanyViewModel();
      this.companyEditMode = false;
      this.selectedCompanyLogoFile = null;
      this.selectedCompanyLogoName = '';
      this.lastUpdatedAt = new Date();
      this.toast.showSuccess('Company profile updated', 'Organization details were saved successfully.');
    });
}

private createEmptyCompanyForm(): CompanyProfileFormData {
  return {
    legal_name: '',
    display_name: '',
    description: '',
    industry: '',
    sub_industry: '',
    company_type: '',
    company_stage: '',
    company_size: '',
    employee_count: '',
    founded_year: '',
    website: '',
    careers_page: '',
    linkedin_url: '',
    twitter_url: '',
    contact_email: '',
    contact_phone: '',
    alternate_phone: '',
    address_line_1: '',
    address_line_2: '',
    landmark: '',
    city: '',
    state: '',
    postal_code: '',
    country: '',
    headquarters: '',
    registration_number: '',
    tax_identifier: '',
    currency_code: '',
    timezone: '',
  };
}

private populateCompanyForm(): void {
  const profile = this.companyProfile;
  if (!profile) {
    this.companyForm = this.createEmptyCompanyForm();
    return;
  }
  this.companyForm = {
    legal_name: profile.legal_name || '',
    display_name: profile.display_name || '',
    description: profile.description || '',
    industry: profile.industry || '',
    sub_industry: profile.sub_industry || '',
    company_type: profile.company_type || '',
    company_stage: profile.company_stage || '',
    company_size: profile.company_size || '',
    employee_count: profile.employee_count?.toString() || '',
    founded_year: profile.founded_year?.toString() || '',
    website: profile.website || '',
    careers_page: profile.careers_page || '',
    linkedin_url: profile.linkedin_url || '',
    twitter_url: profile.twitter_url || '',
    contact_email: profile.contact_email || '',
    contact_phone: profile.contact_phone || '',
    alternate_phone: profile.alternate_phone || '',
    address_line_1: profile.address_line_1 || '',
    address_line_2: profile.address_line_2 || '',
    landmark: profile.landmark || '',
    city: profile.city || '',
    state: profile.state || '',
    postal_code: profile.postal_code || '',
    country: profile.country || '',
    headquarters: profile.headquarters || '',
    registration_number: profile.registration_number || '',
    tax_identifier: profile.tax_identifier || '',
    currency_code: profile.currency_code || '',
    timezone: profile.timezone || '',
  };
}

private hydrateCompanyViewModel(): void {
  const profile = this.companyProfile;
  if (!profile) {
    this.companyDisplayNameText = 'Company Pending';
    this.companyInitialsText = 'CP';
    this.companyMetaLineText = 'Profile setup in progress';
    this.companyLocationLineText = '';
    this.companyOverviewItemsData = [];
    this.companyLinksData = [];
    this.companyContactsData = [];
    return;
  }

  this.companyDisplayNameText = profile.display_name || profile.legal_name || 'Company Pending';
  const parts = this.companyDisplayNameText.split(/\s+/).filter(Boolean);
  this.companyInitialsText = !parts.length
    ? 'CP'
    : parts.length === 1
      ? parts[0].slice(0, 2).toUpperCase()
      : `${parts[0][0]}${parts[1][0]}`.toUpperCase();
  this.companyMetaLineText = [
    this.formatCompanyChoice(profile.company_type),
    profile.industry,
    profile.headquarters,
  ].filter((value) => this.isMeaningfulCompanyValue(value)).join(' • ') || 'Profile setup in progress';
  this.companyLocationLineText = [
    profile.address_line_1,
    profile.address_line_2,
    profile.city,
    profile.state,
    profile.postal_code,
    profile.country,
  ].filter((value) => this.isMeaningfulCompanyValue(value)).join(', ');
  this.companyOverviewItemsData = [
    { label: 'Company Type', value: this.formatCompanyChoice(profile.company_type) },
    { label: 'Stage', value: this.formatCompanyChoice(profile.company_stage) },
    { label: 'Company Size', value: this.formatCompanyChoice(profile.company_size) },
    { label: 'Employees', value: profile.employee_count?.toString() || '' },
    { label: 'Founded', value: profile.founded_year?.toString() || '' },
    { label: 'Currency', value: profile.currency_code || '' },
    { label: 'Timezone', value: profile.timezone || '' },
    { label: 'Headquarters', value: profile.headquarters || '' },
  ].filter((item) => this.isMeaningfulCompanyValue(item.value));
  this.companyLinksData = [
    { label: 'Website', value: profile.website, icon: 'ph ph-globe-hemisphere-west' },
    { label: 'Careers', value: profile.careers_page, icon: 'ph ph-briefcase-metal' },
    { label: 'LinkedIn', value: profile.linkedin_url, icon: 'ph ph-linkedin-logo' },
    { label: 'Twitter', value: profile.twitter_url, icon: 'ph ph-x-logo' },
  ].filter((item) => this.isMeaningfulCompanyValue(item.value));
  this.companyContactsData = [
    { label: 'Email', value: profile.contact_email, icon: 'ph ph-envelope-simple' },
    { label: 'Primary Phone', value: profile.contact_phone, icon: 'ph ph-phone-call' },
    { label: 'Alternate Phone', value: profile.alternate_phone, icon: 'ph ph-device-mobile' },
    { label: 'Registration No.', value: profile.registration_number, icon: 'ph ph-identification-card' },
    { label: 'Tax Identifier', value: profile.tax_identifier, icon: 'ph ph-receipt' },
  ].filter((item) => this.isMeaningfulCompanyValue(item.value));
}

get chartLegendData() {
  const values = [
    { label: 'In Progress', value: this.scheduledCandidates?.length || 0, color: '#22d3ee' },
    { label: 'Shortlisted', value: this.shortlistedCandidates?.length || 0, color: '#3b82f6' },
    { label: 'Hired', value: this.hiredCandidates?.length || 0, color: '#10b981' },
    { label: 'Auto Screening Scheduled', value: this.autoScreeningScheduledCandidates?.length || 0, color: '#8b5cf6' },
    { label: 'Rejected', value: this.rejectedCandidates?.length || 0, color: '#ef4444' },
    { label: 'Assessment Pending', value: this.assessmentPendingCandidates?.length || 0, color: '#f59e0b' },
    { label: 'Cancelled', value: this.cancelledCandidates?.length || 0, color: '#9ca3af' }
  ];

  const total = values.reduce((sum, item) => sum + item.value, 0);
  return values.map((item) => ({
    ...item,
    percent: total ? Math.round((item.value / total) * 100) : 0
  }));
}

get hasSourceChartData(): boolean {
  return this.chartLegendData.some((item) => item.value > 0);
}

get overviewKpiCards(): OverviewKpiCard[] {
  const list = this.candidatesData || [];
  return [
    this.buildOverviewKpiCard(
      'total-candidates',
      'Total Candidates',
      'ph ph-users-three',
      'kpi-card--candidates',
      list,
      () => true
    ),
    this.buildOverviewKpiCard(
      'scheduled',
      'Scheduled',
      'ph ph-calendar-check',
      'kpi-card--scheduled',
      list,
      (candidate) => this.normalizeStatus(candidate?.status) === 'scheduled' && !this.isAutoScreeningCandidate(candidate)
    ),
    this.buildOverviewKpiCard(
      'hired',
      'Hired',
      'ph ph-check-circle',
      'kpi-card--hired',
      list,
      (candidate) => {
        const status = this.normalizeStatus(candidate?.status);
        return status === 'completed' || status === 'hired';
      }
    ),
    this.buildOverviewKpiCard(
      'disqualified',
      'Disqualified',
      'ph ph-x-circle',
      'kpi-card--rejected',
      list,
      (candidate) => this.normalizeStatus(candidate?.status) === 'rejected'
    ),
  ];
}

get roleSnapshotData() {
  const roleMap = new Map<string, { roleId: string; role: string; vacancies: number; applied: number; hired: number }>();

  for (const role of this.roleCatalog || []) {
    const roleId = (role?.id ?? '').toString();
    if (!roleId) continue;
    roleMap.set(roleId, {
      roleId,
      role: (role?.name || 'General').toString(),
      vacancies: Number(role?.vacancies) || 0,
      applied: 0,
      hired: 0
    });
  }

  for (const candidate of this.candidatesData || []) {
    const roleId = (candidate?.role_id ?? candidate?.role ?? '').toString();
    const fallbackRoleName = (candidate?.role || 'General').toString();
    const status = (candidate?.status || '').toString().toLowerCase();
    const entry = roleMap.get(roleId) || {
      roleId,
      role: fallbackRoleName,
      vacancies: 0,
      applied: 0,
      hired: 0
    };

    entry.applied += 1;
    if (status === 'completed' || status === 'hired') {
      entry.hired += 1;
    }
    roleMap.set(roleId, entry);
  }

  return Array.from(roleMap.values())
    .filter((item) => item.vacancies > 0 || item.applied > 0 || item.hired > 0)
    .sort((a, b) => b.applied - a.applied || b.vacancies - a.vacancies)
    .slice(0, 3)
    .map((item) => ({
      ...item,
      fulfilledPercent: item.vacancies > 0 ? Math.min(100, Math.round((item.hired / item.vacancies) * 100)) : 0
    }));
}

  get hiddenRolesCount(): number {
  const roleMap = new Map<string, boolean>();
  for (const role of this.roleCatalog || []) {
    roleMap.set((role?.id ?? '').toString(), true);
  }
  for (const candidate of this.candidatesData || []) {
    roleMap.set((candidate?.role_id ?? candidate?.role ?? '').toString(), true);
  }
  const totalRoles = Array.from(roleMap.keys()).filter((key) => !!key).length;
  return Math.max(totalRoles - 3, 0);
}

get monthlyTrendCards(): MonthlyTrendCard[] {
  const now = new Date();
  const currentMonth = now.getMonth();
  const currentYear = now.getFullYear();
  const previousDate = new Date(currentYear, currentMonth - 1, 1);
  const previousMonth = previousDate.getMonth();
  const previousYear = previousDate.getFullYear();

  const currentMonthCandidates = this.getCandidatesByMonth(currentYear, currentMonth);
  const previousMonthCandidates = this.getCandidatesByMonth(previousYear, previousMonth);

  const currentApplicants = currentMonthCandidates.length;
  const previousApplicants = previousMonthCandidates.length;

  const interviewStatuses = new Set(['scheduled', 'completed', 'hired', 'rejected', 'cancelled']);
  const currentInterviews = currentMonthCandidates.filter((c: any) => interviewStatuses.has(this.normalizeStatus(c?.status))).length;
  const previousInterviews = previousMonthCandidates.filter((c: any) => interviewStatuses.has(this.normalizeStatus(c?.status))).length;

  const currentShortlisted = currentMonthCandidates.filter((c: any) => this.normalizeStatus(c?.status) === 'shortlisted').length;
  const previousShortlisted = previousMonthCandidates.filter((c: any) => this.normalizeStatus(c?.status) === 'shortlisted').length;
  const currentShortlistRate = currentApplicants ? Math.round((currentShortlisted / currentApplicants) * 100) : 0;
  const previousShortlistRate = previousApplicants ? Math.round((previousShortlisted / previousApplicants) * 100) : 0;

  const currentHired = currentMonthCandidates.filter((c: any) => {
    const status = this.normalizeStatus(c?.status);
    return status === 'hired' || status === 'completed';
  }).length;
  const previousHired = previousMonthCandidates.filter((c: any) => {
    const status = this.normalizeStatus(c?.status);
    return status === 'hired' || status === 'completed';
  }).length;
  const currentHireRate = currentApplicants ? Math.round((currentHired / currentApplicants) * 100) : 0;
  const previousHireRate = previousApplicants ? Math.round((previousHired / previousApplicants) * 100) : 0;

  return [
    this.buildTrendCard('applicants', 'New Applicants', 'Profiles added this month', 'ph ph-users-three', currentApplicants, previousApplicants, false),
    this.buildTrendCard('interviews', 'Interviews Scheduled', 'Confirmed interviews this month', 'ph ph-calendar-check', currentInterviews, previousInterviews, false),
    this.buildTrendCard('shortlist-rate', 'Shortlist Conversion', 'Applicants moved to shortlist', 'ph ph-check-square-offset', currentShortlistRate, previousShortlistRate, true),
    this.buildTrendCard('hire-rate', 'Hiring Conversion', 'Applicants closed as hires', 'ph ph-handshake', currentHireRate, previousHireRate, true)
  ];
}

get needsAttentionItems(): AttentionItem[] {
  const now = new Date();
  const list = this.candidatesData || [];
  const overdueFeedbackCandidates = this.getOverdueFeedbackCandidates(list, now);
  const unscheduledShortlistedCandidates = this.getUnscheduledShortlistedCandidates(list);
  const pendingOfferCandidates = this.getPendingOfferCandidates(list, now);

  return [
    this.buildAttentionItem(
      'overdue-feedback',
      'Overdue Feedback',
      'ph ph-warning-circle',
      overdueFeedbackCandidates,
      'Completed interviews older than 2 days missing notes/score.'
    ),
    this.buildAttentionItem(
      'unscheduled-shortlisted',
      'Unscheduled Shortlisted',
      'ph ph-calendar-x',
      unscheduledShortlistedCandidates,
      'Shortlisted candidates without an interview date.'
    ),
    this.buildAttentionItem(
      'pending-offers',
      'Pending Offers',
      'ph ph-hourglass-medium',
      pendingOfferCandidates,
      'Shortlisted after interview date, awaiting final decision.'
    )
  ];
}

applyNeedsAttentionFilter(filterKey: AttentionFilterKey): void {
  this.attentionFilter = this.attentionFilter === filterKey ? null : filterKey;
  this.selectedStatus = null;
  this.searchQuery = '';
  this.currentPage = 1;
  this.scrollToCandidatePipeline();
}

isAttentionFilterActive(filterKey: AttentionFilterKey): boolean {
  return this.attentionFilter === filterKey;
}

clearNeedsAttentionFilter(): void {
  this.attentionFilter = null;
  this.currentPage = 1;
}

formatTrendValue(card: MonthlyTrendCard): string {
  return this.isRateCard(card.key) ? `${card.value}%` : `${card.value}`;
}

formatPreviousTrendValue(card: MonthlyTrendCard): string {
  return this.isRateCard(card.key) ? `${card.previousValue}%` : `${card.previousValue}`;
}

private getCandidatesByMonth(year: number, month: number): any[] {
  return (this.candidatesData || []).filter((candidate: any) => {
    const d = this.toDate(candidate?.date);
    return !!d && d.getFullYear() === year && d.getMonth() === month;
  });
}

private buildTrendCard(
  key: string,
  label: string,
  helper: string,
  icon: string,
  value: number,
  previousValue: number,
  isPercent: boolean
): MonthlyTrendCard {
  const delta = value - previousValue;
  const direction: TrendDirection = delta > 0 ? 'up' : (delta < 0 ? 'down' : 'flat');
  const absDelta = Math.abs(delta);
  const suffix = isPercent ? '%' : '';

  return {
    key,
    label,
    helper,
    icon,
    value,
    previousValue,
    delta,
    deltaText: `${delta > 0 ? '+' : delta < 0 ? '-' : ''}${absDelta}${suffix}`,
    direction
  };
}

private buildAttentionItem(
  key: AttentionFilterKey,
  title: string,
  icon: string,
  candidates: any[],
  helperText: string
): AttentionItem {
  return {
    key,
    title,
    icon,
    count: candidates.length,
    helperText,
    candidates: candidates.slice(0, 3)
  };
}

private toDate(value: any): Date | null {
  if (!value) return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

private isRateCard(key: string): boolean {
  return key === 'shortlist-rate' || key === 'hire-rate';
}

private buildOverviewKpiCard(
  key: string,
  label: string,
  icon: string,
  toneClass: string,
  list: any[],
  predicate: (candidate: any) => boolean
): OverviewKpiCard {
  const value = list.filter(predicate).length;
  const current = this.countCandidatesInRecentWindow(list, 0, 30, predicate);
  const previous = this.countCandidatesInRecentWindow(list, 30, 60, predicate);
  const delta = current - previous;
  const direction: TrendDirection = delta > 0 ? 'up' : delta < 0 ? 'down' : 'flat';
  const directionWord = direction === 'up' ? 'more' : direction === 'down' ? 'fewer' : 'same';
  const trendText = current || previous
    ? `${Math.abs(delta)} ${directionWord} vs previous 30 days`
    : 'No dated activity in last 60 days';

  return {
    key,
    label,
    value,
    icon,
    toneClass,
    trendText,
    trendDirection: direction,
    trendIcon: direction === 'up' ? 'ph ph-trend-up' : direction === 'down' ? 'ph ph-trend-down' : 'ph ph-minus',
  };
}

private countCandidatesInRecentWindow(
  list: any[],
  startDaysAgo: number,
  endDaysAgo: number,
  predicate: (candidate: any) => boolean
): number {
  const now = new Date();
  const start = new Date(now);
  start.setDate(now.getDate() - endDaysAgo);
  start.setHours(0, 0, 0, 0);
  const end = new Date(now);
  end.setDate(now.getDate() - startDaysAgo);
  end.setHours(23, 59, 59, 999);

  return list.filter((candidate) => {
    if (!predicate(candidate)) return false;
    const date = this.toDate(candidate?.date);
    return !!date && date >= start && date <= end;
  }).length;
}

private getOverdueFeedbackCandidates(list: any[], now: Date): any[] {
  return list.filter((candidate: any) => {
    const status = this.normalizeStatus(candidate?.status);
    const interviewDate = this.toDate(candidate?.date);
    const olderThanTwoDays = !!interviewDate && (now.getTime() - interviewDate.getTime()) > (2 * 24 * 60 * 60 * 1000);
    const missingFeedback = !candidate?.notes || candidate?.score === null || candidate?.score === undefined || candidate?.score === '';
    return (status === 'completed' || status === 'hired') && olderThanTwoDays && missingFeedback;
  });
}

private getUnscheduledShortlistedCandidates(list: any[]): any[] {
  return list.filter((candidate: any) => {
    const status = this.normalizeStatus(candidate?.status);
    return status === 'shortlisted' && !this.toDate(candidate?.date);
  });
}

private getPendingOfferCandidates(list: any[], now: Date): any[] {
  return list.filter((candidate: any) => {
    const status = this.normalizeStatus(candidate?.status);
    const interviewDate = this.toDate(candidate?.date);
    return status === 'shortlisted' && (!!interviewDate && interviewDate <= now);
  });
}

private applyAttentionFilter(list: any[]): any[] {
  if (!this.attentionFilter) return list;
  const now = new Date();

  if (this.attentionFilter === 'overdue-feedback') {
    return this.getOverdueFeedbackCandidates(list, now);
  }
  if (this.attentionFilter === 'unscheduled-shortlisted') {
    return this.getUnscheduledShortlistedCandidates(list);
  }
  return this.getPendingOfferCandidates(list, now);
}

private scrollToCandidatePipeline(): void {
  setTimeout(() => {
    const el = document.getElementById('candidatePipelineSection');
    if (el) {
      const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      const top = el.getBoundingClientRect().top + window.scrollY - 84;
      window.scrollTo({
        top: Math.max(0, top),
        behavior: prefersReducedMotion ? 'auto' : 'smooth',
      });
    }
  }, 50);
}

private normalizeStatus(value: any): string {
  const s = (value || '')
    .toString()
    .trim()
    .toLowerCase()
    .replace(/_/g, ' ')
    .replace(/\s+/g, ' ')
    .replace(/assesment/g, 'assessment');

  if (s === 'auto screened') return 'auto screening scheduled';
  if (s === 'auto screening') return 'auto screening scheduled';
  return s;
}

private isAutoScreeningCandidate(candidate: any): boolean {
  const interviewType = (candidate?.interview_type || '').toString().trim().toLowerCase();
  return interviewType === 'auto';
}

private matchesPipelineStatus(candidate: any, normalizedStatus: string): boolean {
  const candidateStatus = this.normalizeStatus(candidate?.status);
  if (normalizedStatus === 'completed') {
    return candidateStatus === 'completed' || candidateStatus === 'hired';
  }
  if (normalizedStatus === 'shortlisted') {
    return candidateStatus === 'shortlisted' || candidateStatus === 'offer made' || candidateStatus === 'offer accepted';
  }
  if (normalizedStatus === 'auto screening scheduled') {
    return candidateStatus === 'auto screening scheduled'
      || (candidateStatus === 'assessment pending' && this.isAutoScreeningCandidate(candidate))
      || (candidateStatus === 'scheduled' && this.isAutoScreeningCandidate(candidate));
  }
  if (normalizedStatus === 'assessment pending') {
    return candidateStatus === 'assessment pending' && !this.isAutoScreeningCandidate(candidate);
  }
  if (normalizedStatus === 'scheduled') {
    return candidateStatus === 'scheduled' && !this.isAutoScreeningCandidate(candidate);
  }
  return candidateStatus === normalizedStatus;
}

normalizeEvaluationPayload(report: Record<string, any>): CandidateEvaluationSummary {
  const base = this.createEmptyEvaluationSummary();
  const payload = this.isObjectRecord(report?.['evaluation_payload'])
    ? (report['evaluation_payload'] as Record<string, any>)
    : {};
  const field = (key: string): unknown => report?.[key] ?? payload[key];
  const hireRecommendation = this.isObjectRecord(field('hire_recommendation'))
    ? (field('hire_recommendation') as Record<string, unknown>)
    : {};
  const professionalSummary = this.stringValue(
    field('professional_summary') || field('executive_summary') || field('summary') || field('summary_verdict')
  );
  const professionalSections = this.parseProfessionalSummary(professionalSummary);
  const candidateBehavior = this.normalizeCandidateBehavior(field('candidate_behavior'));
  const questionAnswerRecords = this.normalizeQuestionAnswerRecords(field('question_answer_records'));

  return {
    ...base,
    available: Boolean(field('available')),
    candidate_name: this.stringValue(field('candidate_name') || this.evaluationSummaryCandidate?.name),
    role_title: this.stringValue(field('role_title') || field('interview_title') || this.evaluationSummaryCandidate?.role),
    decision: this.stringValue(field('decision')),
    recommendation: this.stringValue(field('recommendation') || hireRecommendation['action']),
    score: this.numberOrNull(field('score')),
    executive_summary: this.stringValue(field('executive_summary') || field('summary') || field('overall_summary')),
    summary_verdict: this.stringValue(field('summary_verdict')),
    professional_summary: professionalSummary,
    professional_summary_sections: professionalSections,
    professional_summary_fallback: professionalSections.length ? '' : professionalSummary,
    question_answer_records: questionAnswerRecords,
    candidate_behavior: candidateBehavior,
    evidence_highlights: this.normalizeTextArray(field('evidence_highlights')),
    technical_breakdown: this.isObjectRecord(field('technical_breakdown')) ? (field('technical_breakdown') as Record<string, unknown>) : {},
    behavior_breakdown: this.isObjectRecord(field('behavior_breakdown')) ? (field('behavior_breakdown') as Record<string, unknown>) : {},
    next_round_focus: this.normalizeTextArray(field('next_round_focus')),
    evaluation_payload: payload,
    confidence: this.stringValue(field('confidence')),
    interview_signal_quality: this.stringValue(field('interview_signal_quality')),
    strengths: this.normalizeTextArray(field('strengths') || field('top_strengths')),
    concerns: this.normalizeTextArray(field('concerns')),
    gaps: this.normalizeTextArray(field('gaps') || field('weaknesses')),
    notes: this.normalizeTextArray(field('notes')),
    follow_up_areas: this.normalizeTextArray(field('follow_up_areas')),
    hire_recommendation_action: this.stringValue(hireRecommendation['action']),
    hire_recommendation_reason: this.stringValue(hireRecommendation['reason']),
    early_exit: Boolean(field('early_exit')),
    early_exit_reason: this.stringValue(field('early_exit_reason')),
    profile_picture_data_url: this.stringValue(field('profile_picture_data_url')),
    updated_at: this.stringValue(field('updated_at')),
    created_at: this.stringValue(field('created_at')),
    aptitude_assessment: this.normalizeAptitudeSummary(field('aptitude_assessment')),
  };
}

parseProfessionalSummary(summary: string): ProfessionalSummarySection[] {
  const text = this.stringValue(summary);
  if (!text) {
    return [];
  }

  const labelMap: Record<string, { key: string; title: string }> = {
    'executive summary': { key: 'executive_summary', title: 'Executive Summary' },
    'evidence record': { key: 'evidence_record', title: 'Evidence Record' },
    'hiring signal': { key: 'hiring_signal', title: 'Hiring Signal' },
    'candidate behaviour': { key: 'candidate_behaviour', title: 'Candidate Behaviour' },
    'candidate behavior': { key: 'candidate_behaviour', title: 'Candidate Behaviour' },
  };
  const labelPattern = /(?:^|\n)\s*\*{0,2}(Executive Summary|Evidence Record|Hiring Signal|Candidate Behaviou?r)\*{0,2}\s*:?\s*/gi;
  const matches = Array.from(text.matchAll(labelPattern));
  if (!matches.length) {
    return [];
  }

  const sections: ProfessionalSummarySection[] = [];
  matches.forEach((match, index) => {
    const rawLabel = (match[1] || '').toLowerCase();
    const label = labelMap[rawLabel];
    const start = match.index !== undefined ? match.index + match[0].length : 0;
    const end = index + 1 < matches.length && matches[index + 1].index !== undefined
      ? matches[index + 1].index as number
      : text.length;
    const content = text.slice(start, end).trim();
    if (label && content) {
      sections.push({ ...label, content });
    }
  });
  return sections;
}

decisionBadgeClass(decision: string): string {
  const normalized = this.normalizeEvaluationLabel(decision);
  if (normalized.includes('strong hire')) return 'evaluation-report-badge--strong-hire';
  if (normalized === 'hire' || normalized.includes('advance')) return 'evaluation-report-badge--hire';
  if (normalized.includes('maybe') || normalized.includes('hold')) return 'evaluation-report-badge--maybe';
  if (normalized.includes('needs more data') || normalized.includes('more data')) return 'evaluation-report-badge--needs-data';
  if (normalized.includes('reject') || normalized.includes('no hire')) return 'evaluation-report-badge--reject';
  return 'evaluation-report-badge--neutral';
}

behaviorStatusBadgeClass(status: string): string {
  const normalized = this.normalizeEvaluationLabel(status);
  if (normalized.includes('attention required') || normalized.includes('flagged') || normalized.includes('review')) {
    return 'evaluation-report-badge--warning';
  }
  if (normalized.includes('clear') || normalized.includes('passed') || normalized.includes('verified')) {
    return 'evaluation-report-badge--success';
  }
  if (normalized.includes('not captured') || normalized.includes('unavailable') || normalized.includes('missing')) {
    return 'evaluation-report-badge--neutral';
  }
  return 'evaluation-report-badge--neutral';
}

formatScore(score: number | string | null | undefined): string {
  const value = this.numberOrNull(score);
  if (value === null) {
    return 'N/A';
  }
  return Number.isInteger(value) ? `${value}` : value.toFixed(1);
}

truncateText(text: string, limit: number): string {
  const value = this.stringValue(text);
  if (value.length <= limit) {
    return value;
  }
  return `${value.slice(0, limit).trim()}...`;
}

getEvaluationSummaryText(): string {
  return this.evaluationSummary.executive_summary
    || this.evaluationSummary.summary_verdict
    || this.evaluationSummary.professional_summary_fallback;
}

getEvaluationSignalLabel(): string {
  return [this.evaluationSummary.confidence, this.evaluationSummary.interview_signal_quality]
    .filter((value) => Boolean(value))
    .join(' / ');
}

hasEvidenceHighlights(): boolean {
  return Boolean(
    this.evaluationSummary.strengths.length
    || this.evaluationSummary.concerns.length
    || this.evaluationSummary.gaps.length
    || this.evaluationSummary.follow_up_areas.length
  );
}

hasCandidateBehaviorSignals(): boolean {
  const behavior = this.evaluationSummary.candidate_behavior;
  return Boolean(
    behavior.status
    || behavior.summary
    || Object.keys(behavior.gaze_tracking).length
    || Object.keys(behavior.voice_verification).length
  );
}

getEvaluationCandidateInitials(): string {
  return this.getCandidateInitials(this.evaluationSummary.candidate_name || this.evaluationSummaryCandidate?.name || 'Candidate');
}

getEvaluationCandidateEmail(): string {
  return this.stringValue(
    this.evaluationSummaryCandidate?.email
    || this.evaluationSummaryCandidate?.candidate_email
    || this.evaluationSummary.evaluation_payload['candidate_email']
  );
}

getEvaluationCandidatePhone(): string {
  return this.stringValue(
    this.evaluationSummaryCandidate?.phone
    || this.evaluationSummaryCandidate?.candidate_phone
    || this.evaluationSummary.evaluation_payload['candidate_phone']
  );
}

getEvaluationCurrentStage(): string {
  return this.humanizeLabel(
    this.stringValue(
      this.evaluationSummaryCandidate?.current_stage
      || this.evaluationSummaryCandidate?.status
      || this.evaluationSummary.evaluation_payload['current_stage']
      || this.evaluationSummary.evaluation_payload['stage']
    )
  ) || 'Not captured';
}

getEvaluationInterviewType(): string {
  const type = this.stringValue(this.evaluationSummaryCandidate?.interview_type || this.evaluationSummary.evaluation_payload['interview_type']);
  if (!type) {
    return 'Not captured';
  }
  return type.toLowerCase() === 'auto' ? 'Technical' : this.humanizeLabel(type);
}

getEvaluationSource(): string {
  return this.humanizeLabel(this.stringValue(this.evaluationSummaryCandidate?.source || this.evaluationSummary.evaluation_payload['source'])) || 'Not captured';
}

getEvaluationReportId(): string {
  const candidateId = this.stringValue(this.evaluationSummaryCandidate?.id || this.evaluationSummary.evaluation_payload['candidate_id']) || 'candidate';
  const date = this.evaluationReportGeneratedAt.toISOString().slice(0, 10).replace(/-/g, '');
  return `EV-${date}-${candidateId}`;
}

getEvaluationDecisionLabel(): string {
  return this.humanizeLabel(this.evaluationSummary.decision || this.evaluationSummary.recommendation) || 'Needs More Data';
}

getEvaluationRecommendationText(): string {
  return this.evaluationSummary.recommendation
    || this.evaluationSummary.hire_recommendation_action
    || this.evaluationSummary.hire_recommendation_reason
    || 'No recommendation captured';
}

getEvaluationScorePercent(): number {
  const value = this.numberOrNull(this.evaluationSummary.score);
  if (value === null) {
    return 0;
  }
  if (value <= 5) {
    return Math.max(0, Math.min(100, value * 20));
  }
  return Math.max(0, Math.min(100, value));
}

formatReportScore(): string {
  const score = this.getEvaluationScorePercent();
  if (!score) {
    return 'N/A';
  }
  return Number.isInteger(score) ? `${score}` : score.toFixed(1);
}

scoreRingStyle(score: number | null = null, color = '#f59e0b', track = '#e5e7eb'): Record<string, string> {
  const value = score === null ? this.getEvaluationScorePercent() : Math.max(0, Math.min(100, score));
  return {
    background: `conic-gradient(${color} 0deg ${value * 3.6}deg, ${track} ${value * 3.6}deg 360deg)`,
  };
}

getDecisionTone(): string {
  const normalized = this.normalizeEvaluationLabel(this.evaluationSummary.decision || this.evaluationSummary.recommendation);
  if (normalized.includes('reject') || normalized.includes('no hire') || normalized.includes('not recommended')) {
    return 'danger';
  }
  if (normalized.includes('maybe') || normalized.includes('hold') || normalized.includes('needs more data')) {
    return 'warning';
  }
  if (normalized.includes('hire') || normalized.includes('advance') || normalized.includes('recommended')) {
    return 'success';
  }
  return 'neutral';
}

getReportDecisionColor(): string {
  const tone = this.getDecisionTone();
  if (tone === 'success') return '#10b981';
  if (tone === 'danger') return '#ef4444';
  return '#f59e0b';
}

hasEvaluationReportContent(): boolean {
  return Boolean(this.evaluationSummary.available || this.hasAptitudeAssessment());
}

getAptitudeSummary(): AptitudeAssessmentSummary {
  return this.evaluationSummary.aptitude_assessment || this.createEmptyAptitudeSummary();
}

hasAptitudeAssessment(): boolean {
  return Boolean(this.getAptitudeSummary().available);
}

isAptitudeCompleted(): boolean {
  const summary = this.getAptitudeSummary();
  const status = this.normalizeEvaluationLabel(summary.status);
  return Boolean(
    summary.available
    && (status === 'submitted' || status === 'expired')
    && summary.score_percent !== null
  );
}

getAptitudeScoreLabel(): string {
  const score = this.getAptitudeSummary().score_percent;
  if (score === null) {
    return 'N/A';
  }
  return `${this.formatScore(score)}%`;
}

getAptitudeResultTone(): string {
  const summary = this.getAptitudeSummary();
  if (summary.passed === true) return 'success';
  if (summary.passed === false && this.isAptitudeCompleted()) return 'danger';
  const status = this.normalizeEvaluationLabel(summary.status);
  if (status === 'expired') return 'warning';
  return 'neutral';
}

getAptitudeResultLabel(): string {
  const summary = this.getAptitudeSummary();
  if (this.isAptitudeCompleted()) {
    return summary.result_label || (summary.passed ? 'Passed' : 'Not Passed');
  }
  return summary.status_label || this.humanizeLabel(summary.status) || 'Assigned';
}

getAptitudeStatusCopy(): string {
  const summary = this.getAptitudeSummary();
  const status = this.normalizeEvaluationLabel(summary.status);
  if (status === 'assigned') {
    return 'The aptitude assessment has been assigned and is awaiting candidate completion.';
  }
  if (status === 'in progress') {
    return 'The candidate has started the aptitude assessment.';
  }
  if (status === 'expired' && !this.isAptitudeCompleted()) {
    return 'The aptitude assessment window has expired. No scored result is currently available.';
  }
  if (this.isAptitudeCompleted()) {
    return 'The aptitude assessment has been completed and scored.';
  }
  return 'Aptitude assessment status is available for review.';
}

getAptitudeSectionRows(): AptitudeSectionResult[] {
  return this.getAptitudeSummary().section_results;
}

getAptitudeSectionScoreText(section: AptitudeSectionResult): string {
  const scoreLabel = section.score_percent === null ? 'N/A' : `${this.formatScore(section.score_percent)}%`;
  const rawScore = section.score === null || section.max_score === null
    ? 'Not scored'
    : `${this.formatScore(section.score)}/${this.formatScore(section.max_score)}`;
  return `${scoreLabel} · ${rawScore}`;
}

getAptitudeSectionProgressValue(section: AptitudeSectionResult): number {
  const score = section.score_percent ?? 0;
  return Math.max(0, Math.min(100, score));
}

getAptitudeAnsweredLabel(): string {
  const summary = this.getAptitudeSummary();
  return `${summary.answered_count}/${summary.total_questions || 0}`;
}

getAptitudePassingBenchmarkLabel(): string {
  const benchmark = this.getAptitudeSummary().passing_score_percent;
  return benchmark === null ? 'Not set' : `${this.formatScore(benchmark)}%`;
}

getAptitudeReviewLabel(integrity: AptitudeIntegritySummary = this.getAptitudeSummary().integrity_summary): string {
  return integrity.review_required ? 'Review recommended' : 'Clear';
}

getAptitudeIntegrityFlags(integrity: AptitudeIntegritySummary = this.getAptitudeSummary().integrity_summary): string[] {
  if (integrity.flags.length) {
    return integrity.flags;
  }
  if (integrity.review_required && integrity.event_count > 0) {
    return [`${integrity.event_count} integrity event${integrity.event_count === 1 ? '' : 's'}`];
  }
  return [];
}

getAptitudeIntegrityText(): string {
  const integrity = this.getAptitudeSummary().integrity_summary;
  if (integrity.review_required && integrity.flags.length) {
    return 'Review the integrity signals captured during the assessment.';
  }
  if (integrity.review_required) {
    return `Review recommended: ${integrity.event_count} integrity event${integrity.event_count === 1 ? '' : 's'} recorded`;
  }
  return 'No major integrity flags recorded';
}

getAptitudeTimelineLabel(): string {
  const summary = this.getAptitudeSummary();
  const dateValue = summary.submitted_at || summary.started_at || summary.scheduled_at || summary.expires_at;
  if (!dateValue) {
    return '';
  }
  const date = this.toDate(dateValue);
  return date ? date.toLocaleString() : '';
}

renderAptitudeReportSection(): string {
  if (!this.hasAptitudeAssessment()) {
    return '';
  }
  const summary = this.getAptitudeSummary();
  const tone = this.getAptitudeResultTone();
  const sectionHtml = this.renderAptitudeSectionBreakdown();
  const integrityHtml = this.renderAptitudeIntegritySummary();
  const timelineLabel = this.getAptitudeTimelineLabel();
  return `
        <article class="report-card report-section">
          <h2><span>◉</span> Aptitude Assessment</h2>
          <div class="report-aptitude-grid">
            <div class="report-aptitude-score">
              <span>Aptitude Score</span>
              <strong>${this.escapeHtml(this.getAptitudeScoreLabel())}</strong>
              <em class="is-${this.escapeHtmlAttr(tone)}">${this.escapeHtml(this.getAptitudeResultLabel())}</em>
            </div>
            <div class="report-aptitude-content">
              <div class="report-aptitude-metrics">
                <article><small>Status</small><strong>${this.escapeHtml(summary.status_label || this.humanizeLabel(summary.status) || 'Not captured')}</strong></article>
                <article><small>Score</small><strong>${this.escapeHtml(summary.score === null || summary.max_score === null ? 'Not scored' : `${this.formatScore(summary.score)} / ${this.formatScore(summary.max_score)}`)}</strong></article>
                <article><small>Passing Benchmark</small><strong>${this.escapeHtml(this.getAptitudePassingBenchmarkLabel())}</strong></article>
                <article><small>Questions Answered</small><strong>${this.escapeHtml(this.getAptitudeAnsweredLabel())}</strong></article>
              </div>
              <p>${this.escapeHtml(this.getAptitudeStatusCopy())}</p>
              ${timelineLabel ? `<p>Latest aptitude timestamp: ${this.escapeHtml(timelineLabel)}</p>` : ''}
              ${summary.unanswered_count ? `<div class="report-aptitude-chips"><span>Unanswered: ${this.escapeHtml(String(summary.unanswered_count))}</span></div>` : ''}
              ${(summary.early_exit || this.normalizeEvaluationLabel(summary.status) === 'expired') ? `<p>${this.escapeHtml(summary.early_exit ? `Early exit: ${summary.early_exit_reason || 'Reason not captured'}` : 'Time expired')}</p>` : ''}
              ${sectionHtml}
              ${integrityHtml}
            </div>
          </div>
        </article>
  `;
}

renderAptitudeSectionBreakdown(): string {
  const rows = this.getAptitudeSectionRows();
  if (!rows.length || !this.isAptitudeCompleted()) {
    return '';
  }
  return `
              <div class="report-aptitude-table">
                <div class="report-aptitude-head"><span>Section</span><span>Score</span><span>Correct</span><span>Incorrect</span><span>Unanswered</span></div>
                ${rows.map((row) => `
                  <div class="report-aptitude-row">
                    <strong>${this.escapeHtml(row.section_name || this.humanizeLabel(row.section_code) || 'Section')}</strong>
                    <span>${this.escapeHtml(this.getAptitudeSectionScoreText(row))}</span>
                    <span>${this.escapeHtml(String(row.correct_count))}</span>
                    <span>${this.escapeHtml(String(row.incorrect_count))}</span>
                    <span>${this.escapeHtml(`${row.unanswered_count}/${row.total_questions || 0}`)}</span>
                  </div>
                `).join('')}
              </div>
  `;
}

renderAptitudeIntegritySummary(): string {
  if (!this.isAptitudeCompleted()) {
    return '';
  }
  const integrity = this.getAptitudeSummary().integrity_summary;
  const flags = this.getAptitudeIntegrityFlags(integrity);
  const flagHtml = flags.length
    ? `<div class="report-aptitude-integrity-flags">${flags.map((flag) => `<span>${this.escapeHtml(flag)}</span>`).join('')}</div>`
    : '';
  return `
              <div class="report-aptitude-integrity${integrity.review_required ? ' is-warning' : ''}">
                <strong>${this.escapeHtml(this.getAptitudeReviewLabel(integrity) === 'Review recommended' ? 'Integrity review recommended' : 'Integrity clear')}</strong>
                <p>${this.escapeHtml(this.getAptitudeIntegrityText())}</p>
                ${flagHtml}
              </div>
  `;
}

getEvaluationMetaItems(): EvaluationReportMetaItem[] {
  return [
    { label: 'Role', value: this.evaluationSummary.role_title || this.evaluationSummaryCandidate?.role || 'Not captured', icon: 'ph ph-briefcase' },
    { label: 'Current Stage', value: this.getEvaluationCurrentStage(), icon: 'ph ph-users-three' },
    { label: 'Evaluations', value: this.getEvaluationEvaluationCountLabel(), icon: 'ph ph-clipboard-text' },
    { label: 'Interview Type', value: this.getEvaluationInterviewType(), icon: 'ph ph-video-camera' },
    { label: 'Source', value: this.getEvaluationSource(), icon: 'ph ph-globe-hemisphere-east' },
  ];
}

getEvaluationEvaluationCountLabel(): string {
  const count = this.evaluationSummary.question_answer_records.length;
  if (count) {
    return `${count} record${count === 1 ? '' : 's'} captured`;
  }
  if (this.evaluationSummary.available) {
    return 'Summary captured';
  }
  return 'Not captured';
}

getReportProfileItems(): EvaluationReportProfileItem[] {
  return [
    { label: 'Email', value: this.getEvaluationCandidateEmail() || 'Not captured', icon: 'ph ph-envelope-simple' },
    { label: 'Phone', value: this.getEvaluationCandidatePhone() || 'Not captured', icon: 'ph ph-phone' },
    { label: 'Experience', value: this.stringValue(this.evaluationSummaryCandidate?.experience || this.evaluationSummary.evaluation_payload['experience']) || 'Not specified', icon: 'ph ph-briefcase' },
    { label: 'Current Company', value: this.stringValue(this.evaluationSummaryCandidate?.current_company || this.evaluationSummary.evaluation_payload['current_company']) || 'Not captured', icon: 'ph ph-buildings' },
    { label: 'Location', value: this.stringValue(this.evaluationSummaryCandidate?.location || this.evaluationSummary.evaluation_payload['location']) || 'Not captured', icon: 'ph ph-map-pin' },
  ];
}

getExecutiveSummary(): string {
  return this.evaluationSummary.executive_summary
    || this.evaluationSummary.summary_verdict
    || this.evaluationSummary.professional_summary_fallback
    || 'No executive summary captured for this evaluation.';
}

getStrongestEvidence(): string {
  return this.evaluationSummary.strengths[0]
    || this.evaluationSummary.evidence_highlights[0]
    || this.evaluationSummary.question_answer_records.find((record) => this.isPositiveQuality(record.answer_quality_state))?.question_text
    || 'No strongest evidence captured';
}

getWeakestEvidence(): string {
  return this.evaluationSummary.concerns[0]
    || this.evaluationSummary.gaps[0]
    || this.evaluationSummary.question_answer_records.find((record) => this.isWeakQuality(record.answer_quality_state))?.question_text
    || 'No weakest evidence captured';
}

getEvidenceSkillLabel(preferWeak = false): string {
  const record = this.evaluationSummary.question_answer_records.find((item) => preferWeak ? this.isWeakQuality(item.answer_quality_state) : this.isPositiveQuality(item.answer_quality_state));
  return record?.skill || this.getCoreSkillTags()[0] || 'Interview Evidence';
}

getReportInsightCards(): EvaluationReportInsight[] {
  const codingSummary = this.isObjectRecord(this.evaluationSummary.evaluation_payload['coding_summary'])
    ? this.evaluationSummary.evaluation_payload['coding_summary'] as Record<string, unknown>
    : {};
  const codingResponses = this.numberOrNull(codingSummary['responses'] || codingSummary['response_count']) ?? 0;
  return [
    { label: 'Questions Answered', value: `${this.evaluationSummary.question_answer_records.length}`, helper: 'Questions Answered', icon: 'ph ph-question', tone: 'purple' },
    { label: 'Coding Responses', value: `${codingResponses}`, helper: 'Coding Responses', icon: 'ph ph-sparkle', tone: 'green' },
    { label: 'Overall Score', value: this.formatReportScore(), helper: 'Overall Score', icon: 'ph ph-gauge', tone: 'blue' },
    { label: 'Expected Fit', value: this.formatExpectedFit(), helper: 'Expected Fit for Role', icon: 'ph ph-calendar-check', tone: 'orange' },
    { label: 'Hiring Signal', value: this.getEvaluationDecisionLabel().toUpperCase(), helper: 'Hiring Signal', icon: 'ph ph-star', tone: 'cyan' },
  ];
}

formatExpectedFit(): string {
  const score = this.getEvaluationScorePercent();
  return score ? `${Math.round(score)}%` : 'N/A';
}

getReportSkillRows(): EvaluationReportSkillRow[] {
  const sources = [
    this.evaluationSummary.technical_breakdown,
    this.isObjectRecord(this.evaluationSummary.evaluation_payload['rubric']) ? this.evaluationSummary.evaluation_payload['rubric'] as Record<string, unknown> : {},
    this.isObjectRecord(this.evaluationSummary.evaluation_payload['skills_assessment']) ? this.evaluationSummary.evaluation_payload['skills_assessment'] as Record<string, unknown> : {},
  ];
  const rows: EvaluationReportSkillRow[] = [];
  sources.forEach((source) => {
    Object.entries(source || {}).forEach(([key, value]) => {
      if (rows.length >= 6 || key === 'overall') {
        return;
      }
      const score = this.extractScore(value);
      const label = this.extractLabel(value) || this.humanizeLabel(key);
      const proficiency = this.extractProficiency(value, score);
      rows.push({
        label,
        score,
        proficiency,
        tone: this.skillTone(score),
      });
    });
  });

  if (!rows.length) {
    const inferred = ['Technical Proficiency', 'Problem Solving', 'Communication', 'System Design', 'Overall Potential'];
    return inferred.map((label) => ({
      label,
      score: null,
      proficiency: 'Not captured',
      tone: 'neutral',
    }));
  }
  return rows.slice(0, 5);
}

getReportProgressSteps(): EvaluationReportProgressStep[] {
  const current = this.normalizeEvaluationLabel(this.getEvaluationCurrentStage());
  const score = this.formatReportScore() === 'N/A' ? 'Not captured' : `${this.formatReportScore()} / 100`;
  const assessmentLabel = this.shouldUseAptitudeAssessmentProgressLabel() ? 'Aptitude Assessment' : 'Technical Assessment';
  const labels = ['Application Review', assessmentLabel, 'Technical Interview', 'HR Interview', 'Final Evaluation'];
  const currentIndex = labels.findIndex((label) => {
    const normalizedLabel = label.toLowerCase();
    return current.includes(normalizedLabel)
      || (normalizedLabel === 'aptitude assessment' && current.includes('technical assessment'));
  });
  const activeIndex = currentIndex >= 0 ? currentIndex : (this.evaluationSummary.available ? 2 : 0);
  return labels.map((label, index) => ({
    label,
    state: index <= activeIndex ? 'Completed' : 'Pending',
    score: index <= activeIndex ? score : 'Not captured',
    active: index <= activeIndex,
    tone: index <= activeIndex ? (index === activeIndex ? 'current' : 'done') : 'pending',
  }));
}

shouldUseAptitudeAssessmentProgressLabel(): boolean {
  const aptitude = this.getAptitudeSummary();
  if (aptitude.available || aptitude.assignment_id !== null) {
    return true;
  }
  return this.getCandidateActionLinkType(this.evaluationSummaryCandidate) === 'aptitude';
}

getFeedbackRows(): Array<{ avatar: string; evaluator: string; stage: string; score: string; summary: string; tone: string }> {
  const evidence = [
    ...this.evaluationSummary.evidence_highlights,
    ...this.evaluationSummary.strengths,
    ...this.evaluationSummary.concerns,
    ...this.evaluationSummary.gaps,
  ].filter(Boolean);
  const rows = this.evaluationSummary.question_answer_records.slice(0, 3).map((record, index) => ({
    avatar: record.skill ? record.skill.slice(0, 2).toUpperCase() : `E${index + 1}`,
    evaluator: record.skill || 'Evidence-based feedback',
    stage: record.section_role ? this.humanizeLabel(record.section_role) : this.getEvaluationCurrentStage(),
    score: record.answer_quality_state ? this.humanizeLabel(record.answer_quality_state) : 'Captured',
    summary: record.expected_signal || record.question_text || record.candidate_answer || 'No feedback summary captured',
    tone: this.isWeakQuality(record.answer_quality_state) ? 'warning' : 'success',
  }));
  if (rows.length) {
    return rows;
  }
  return (evidence.length ? evidence.slice(0, 3) : ['No evaluator feedback captured']).map((item, index) => ({
    avatar: `E${index + 1}`,
    evaluator: 'Evidence-based feedback',
    stage: this.getEvaluationCurrentStage(),
    score: this.formatReportScore(),
    summary: item,
    tone: index === 0 ? 'success' : 'neutral',
  }));
}

getFeedbackHighlights(): Array<{ title: string; description: string; icon: string }> {
  const rows = this.getReportSkillRows();
  const summary = this.evaluationSummary.evidence_highlights;
  return [
    { title: 'Technical Skills', description: rows[0]?.proficiency || summary[0] || 'Not captured', icon: 'ph ph-stack' },
    { title: 'Problem Solving', description: rows.find((row) => row.label.toLowerCase().includes('problem'))?.proficiency || summary[1] || 'Not captured', icon: 'ph ph-flask' },
    { title: 'Communication', description: rows.find((row) => row.label.toLowerCase().includes('communication'))?.proficiency || this.textFromUnknown(this.evaluationSummary.behavior_breakdown['communication']) || 'Not captured', icon: 'ph ph-chat-circle-text' },
    { title: 'Learning Agility', description: this.evaluationSummary.follow_up_areas[0] || this.evaluationSummary.next_round_focus[0] || 'Not captured', icon: 'ph ph-rocket-launch' },
  ];
}

getCoreSkillTags(): string[] {
  const skills = new Set<string>();
  this.getReportSkillRows().forEach((row) => {
    if (row.label && row.proficiency !== 'Not captured') {
      skills.add(row.label);
    }
  });
  this.evaluationSummary.question_answer_records.forEach((record) => {
    if (record.skill) {
      skills.add(record.skill);
    }
  });
  this.evaluationSummary.strengths.slice(0, 4).forEach((item) => skills.add(item));
  return Array.from(skills).slice(0, 18);
}

getNeedAttentionItems(): string[] {
  const items = [
    ...this.evaluationSummary.concerns,
    ...this.evaluationSummary.gaps,
    ...this.evaluationSummary.follow_up_areas,
  ].filter(Boolean);
  return items.length ? items.slice(0, 4) : ['No attention items captured'];
}

getActionItems(): string[] {
  const items = [
    this.evaluationSummary.hire_recommendation_reason,
    ...this.evaluationSummary.next_round_focus,
    ...this.evaluationSummary.follow_up_areas,
  ].filter(Boolean);
  return items.length ? items.slice(0, 4) : ['Review detailed evidence before the next hiring decision'];
}

getEducationItems(): Array<{ title: string; detail: string }> {
  const education = this.evaluationSummary.evaluation_payload['education'];
  if (Array.isArray(education)) {
    return education
      .map((item) => {
        if (this.isObjectRecord(item)) {
          return {
            title: this.stringValue(item['degree'] || item['title'] || item['qualification']) || 'Education',
            detail: this.stringValue(item['institution'] || item['school'] || item['summary']) || 'Not captured',
          };
        }
        return { title: this.stringValue(item), detail: '' };
      })
      .filter((item) => item.title)
      .slice(0, 3);
  }
  const text = this.textFromUnknown(education);
  return text ? [{ title: text, detail: '' }] : [{ title: 'Education', detail: 'Not captured' }];
}

getQualityClass(value: string): string {
  if (this.isWeakQuality(value)) {
    return 'is-warning';
  }
  if (this.isPositiveQuality(value)) {
    return 'is-good';
  }
  return 'is-neutral';
}

deriveAnswerQuality(record: QuestionAnswerRecord): string {
  const answer = this.stringValue(record.candidate_answer);
  const expected = this.stringValue(record.expected_signal);
  if (!answer) {
    return 'Not Answered';
  }
  if (!expected) {
    return 'Evidence Captured';
  }

  const answerTokens = this.qualityTokens(answer);
  const expectedTokens = this.qualityTokens(expected);
  if (!answerTokens.length || !expectedTokens.length) {
    return 'Needs Review';
  }

  const answerSet = new Set(answerTokens);
  const expectedSet = new Set(expectedTokens);
  const overlap = Array.from(expectedSet).filter((token) => answerSet.has(token)).length;
  const expectedCoverage = overlap / expectedSet.size;
  const answerCoverage = overlap / Math.max(1, Math.min(answerSet.size, expectedSet.size * 2));
  const evidenceScore = (expectedCoverage * 0.75) + (answerCoverage * 0.25);

  if (evidenceScore >= 0.52) {
    return 'Strong Match';
  }
  if (evidenceScore >= 0.28) {
    return 'Partial Match';
  }
  if (overlap > 0) {
    return 'Needs Review';
  }
  return 'Off Target';
}

skillBarStyle(score: number | null): Record<string, string> {
  const width = score === null ? 0 : Math.max(0, Math.min(100, score <= 5 ? score * 20 : score));
  return { width: `${width}%` };
}

isPositiveQuality(value: string): boolean {
  const normalized = this.normalizeEvaluationLabel(value);
  return normalized.includes('good')
    || normalized.includes('strong')
    || normalized.includes('match')
    || normalized.includes('well')
    || normalized.includes('excellent')
    || normalized.includes('complete');
}

isWeakQuality(value: string): boolean {
  const normalized = this.normalizeEvaluationLabel(value);
  return normalized.includes('weak')
    || normalized.includes('partial')
    || normalized.includes('review')
    || normalized.includes('off target')
    || normalized.includes('not answered')
    || normalized.includes('improvement')
    || normalized.includes('gap')
    || normalized.includes('poor');
}

private qualityTokens(value: string): string[] {
  const stopWords = new Set([
    'a', 'an', 'and', 'are', 'as', 'at', 'be', 'by', 'can', 'for', 'from', 'how', 'in', 'is', 'it',
    'of', 'on', 'or', 'that', 'the', 'their', 'this', 'to', 'understand', 'understands', 'use',
    'uses', 'using', 'with', 'would', 'you', 'your',
  ]);
  return Array.from(new Set(
    this.stringValue(value)
      .toLowerCase()
      .replace(/[^a-z0-9+#.]+/g, ' ')
      .split(/\s+/)
      .map((token) => token.trim())
      .filter((token) => token.length > 2 && !stopWords.has(token))
  ));
}

private extractScore(value: unknown): number | null {
  if (typeof value === 'number' || typeof value === 'string') {
    return this.numberOrNull(value);
  }
  if (this.isObjectRecord(value)) {
    return this.numberOrNull(value['score'] ?? value['value'] ?? value['percentage'] ?? value['rating'] ?? value['points']);
  }
  return null;
}

private extractLabel(value: unknown): string {
  if (this.isObjectRecord(value)) {
    return this.stringValue(value['label'] || value['name'] || value['skill'] || value['title']);
  }
  return '';
}

private extractProficiency(value: unknown, score: number | null): string {
  if (this.isObjectRecord(value)) {
    const text = this.stringValue(value['proficiency'] || value['level'] || value['rating_label'] || value['summary']);
    if (text) {
      return this.humanizeLabel(text);
    }
  }
  if (score === null) {
    return 'Not captured';
  }
  const normalized = score <= 5 ? score * 20 : score;
  if (normalized >= 80) return 'High';
  if (normalized >= 60) return 'Good';
  if (normalized >= 45) return 'Average';
  return 'Needs Improvement';
}

private skillTone(score: number | null): string {
  if (score === null) return 'neutral';
  const normalized = score <= 5 ? score * 20 : score;
  if (normalized >= 70) return 'good';
  if (normalized >= 50) return 'average';
  return 'warning';
}

behaviorMetric(source: Record<string, unknown>, key: string): string {
  const value = source[key];
  if (value === null || value === undefined || value === '') {
    return 'N/A';
  }
  if (typeof value === 'boolean') {
    return value ? 'Yes' : 'No';
  }
  return String(value);
}

qaCardKey(record: QuestionAnswerRecord, index: number): string {
  return `${record.turn_index || index + 1}-${index}`;
}

isQaExpanded(record: QuestionAnswerRecord, index: number): boolean {
  return this.qaExpandedKeys.has(this.qaCardKey(record, index));
}

toggleQaAnswer(record: QuestionAnswerRecord, index: number): void {
  const key = this.qaCardKey(record, index);
  if (this.qaExpandedKeys.has(key)) {
    this.qaExpandedKeys.delete(key);
    return;
  }
  this.qaExpandedKeys.add(key);
}

shouldCollapseText(text: string, limit = 260): boolean {
  return this.stringValue(text).length > limit;
}

private createEmptyEvaluationSummary(): CandidateEvaluationSummary {
  return {
    available: false,
    candidate_name: '',
    role_title: '',
    decision: '',
    recommendation: '',
    score: null,
    executive_summary: '',
    summary_verdict: '',
    professional_summary: '',
    professional_summary_sections: [],
    professional_summary_fallback: '',
    question_answer_records: [],
    candidate_behavior: {
      status: '',
      summary: '',
      gaze_tracking: {},
      voice_verification: {},
    },
    evidence_highlights: [],
    technical_breakdown: {},
    behavior_breakdown: {},
    next_round_focus: [],
    evaluation_payload: {},
    confidence: '',
    interview_signal_quality: '',
    strengths: [],
    concerns: [],
    gaps: [],
    notes: [],
    follow_up_areas: [],
    hire_recommendation_action: '',
    hire_recommendation_reason: '',
    early_exit: false,
    early_exit_reason: '',
    profile_picture_data_url: '',
    updated_at: '',
    created_at: '',
    aptitude_assessment: this.createEmptyAptitudeSummary(),
  };
}

private createEmptyAptitudeSummary(): AptitudeAssessmentSummary {
  return {
    available: false,
    status: '',
    status_label: '',
    assignment_id: null,
    title: '',
    scheduled_at: '',
    submitted_at: '',
    started_at: '',
    expires_at: '',
    score: null,
    score_percent: null,
    max_score: null,
    passed: null,
    result_label: '',
    passing_score_percent: null,
    total_questions: 0,
    answered_count: 0,
    unanswered_count: 0,
    early_exit: false,
    early_exit_reason: '',
    section_results: [],
    integrity_summary: {
      review_required: false,
      event_count: 0,
      flags: [],
    },
  };
}

private normalizeQuestionAnswerRecords(value: unknown): QuestionAnswerRecord[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .filter((item) => this.isObjectRecord(item))
    .map((item, index) => {
      const record = item as Record<string, unknown>;
      return {
        turn_index: this.stringValue(record['turn_index']) || index + 1,
        skill: this.stringValue(record['skill']),
        section_role: this.stringValue(record['section_role']),
        question_text: this.stringValue(record['question_text']),
        candidate_answer: this.stringValue(record['candidate_answer']),
        answer_quality_state: this.stringValue(record['answer_quality_state']),
        expected_signal: this.stringValue(record['expected_signal']),
      };
    })
    .filter((record) => Boolean(record.question_text || record.candidate_answer));
}

private normalizeCandidateBehavior(value: unknown): CandidateBehaviorSummary {
  const source = this.isObjectRecord(value) ? (value as Record<string, unknown>) : {};
  return {
    status: this.stringValue(source['status']),
    summary: this.stringValue(source['summary']),
    gaze_tracking: this.isObjectRecord(source['gaze_tracking']) ? (source['gaze_tracking'] as Record<string, unknown>) : {},
    voice_verification: this.isObjectRecord(source['voice_verification']) ? (source['voice_verification'] as Record<string, unknown>) : {},
  };
}

private normalizeAptitudeSummary(value: unknown): AptitudeAssessmentSummary {
  const source = this.isObjectRecord(value) ? (value as Record<string, unknown>) : {};
  const integrity = this.isObjectRecord(source['integrity_summary'])
    ? source['integrity_summary'] as Record<string, unknown>
    : {};
  return {
    available: Boolean(source['available']),
    status: this.stringValue(source['status']),
    status_label: this.stringValue(source['status_label']),
    assignment_id: this.numberOrNull(source['assignment_id']),
    title: this.stringValue(source['title']),
    scheduled_at: this.stringValue(source['scheduled_at']),
    submitted_at: this.stringValue(source['submitted_at']),
    started_at: this.stringValue(source['started_at']),
    expires_at: this.stringValue(source['expires_at']),
    score: this.numberOrNull(source['score']),
    score_percent: this.numberOrNull(source['score_percent']),
    max_score: this.numberOrNull(source['max_score']),
    passed: typeof source['passed'] === 'boolean' ? source['passed'] as boolean : null,
    result_label: this.stringValue(source['result_label']),
    passing_score_percent: this.numberOrNull(source['passing_score_percent']),
    total_questions: this.numberOrNull(source['total_questions']) ?? 0,
    answered_count: this.numberOrNull(source['answered_count']) ?? 0,
    unanswered_count: this.numberOrNull(source['unanswered_count']) ?? 0,
    early_exit: Boolean(source['early_exit']),
    early_exit_reason: this.stringValue(source['early_exit_reason']),
    section_results: this.normalizeAptitudeSectionResults(source['section_results']),
    integrity_summary: {
      review_required: Boolean(integrity['review_required']),
      event_count: this.numberOrNull(integrity['event_count']) ?? 0,
      flags: Array.isArray(integrity['flags'])
        ? integrity['flags'].map((item) => this.stringValue(item)).filter(Boolean)
        : [],
    },
  };
}

private normalizeAptitudeSectionResults(value: unknown): AptitudeSectionResult[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .filter((item) => this.isObjectRecord(item))
    .map((item) => {
      const row = item as Record<string, unknown>;
      return {
        section_code: this.stringValue(row['section_code']),
        section_name: this.stringValue(row['section_name']),
        score: this.numberOrNull(row['score']),
        max_score: this.numberOrNull(row['max_score']),
        score_percent: this.numberOrNull(row['score_percent']),
        correct_count: this.numberOrNull(row['correct_count']) ?? 0,
        incorrect_count: this.numberOrNull(row['incorrect_count']) ?? 0,
        unanswered_count: this.numberOrNull(row['unanswered_count']) ?? 0,
        total_questions: this.numberOrNull(row['total_questions']) ?? 0,
      };
    });
}

private normalizeTextArray(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value
      .map((item) => this.textFromUnknown(item))
      .filter((item) => Boolean(item));
  }
  const text = this.textFromUnknown(value);
  return text ? [text] : [];
}

private textFromUnknown(value: unknown): string {
  if (value === null || value === undefined) {
    return '';
  }
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return String(value).trim();
  }
  if (this.isObjectRecord(value)) {
    return Object.entries(value)
      .slice(0, 4)
      .map(([key, item]) => {
        const text = Array.isArray(item)
          ? item.map((entry) => this.stringValue(entry)).filter(Boolean).join(', ')
          : this.stringValue(item);
        return text ? `${this.humanizeLabel(key)}: ${text}` : '';
      })
      .filter(Boolean)
      .join('; ');
  }
  return '';
}

private stringValue(value: unknown): string {
  if (value === null || value === undefined) {
    return '';
  }
  if (typeof value === 'string') {
    return value.trim();
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value).trim();
  }
  return '';
}

private numberOrNull(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

private isObjectRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value));
}

private normalizeEvaluationLabel(value: string): string {
  return this.stringValue(value).toLowerCase().replace(/_/g, ' ').replace(/\s+/g, ' ').trim();
}

humanizeLabel(value: string): string {
  return value
    .replace(/_/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

private fallbackCopyToClipboard(value: string): boolean {
  try {
    const textarea = document.createElement('textarea');
    textarea.value = value;
    textarea.setAttribute('readonly', 'true');
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    textarea.style.pointerEvents = 'none';
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();
    const copied = document.execCommand('copy');
    textarea.remove();
    return copied;
  } catch {
    return false;
  }
}
  
private renderChart(): void {
  if (!this.sourceCanvas || !this.sourceCanvas.nativeElement) {
    // Canvas not yet available
    return;
  }
  const ctx = this.sourceCanvas.nativeElement;

  // Destroy previous chart if exists
  if (this.sourceChart) {
    this.sourceChart.destroy();
    this.sourceChart = undefined;
  }

  const values = [
    this.scheduledCandidates?.length || 0,
    this.shortlistedCandidates?.length || 0,
    this.hiredCandidates?.length || 0,
    this.autoScreeningScheduledCandidates?.length || 0,
    this.rejectedCandidates?.length || 0,
    this.assessmentPendingCandidates?.length || 0,
    this.cancelledCandidates?.length || 0
  ];

  const labels = ['Scheduled ', 'Shortlisted ', 'Hired ', 'Auto Screening Scheduled ', 'Rejected ', 'Assessment Pending ', 'Cancelled '];
  const colors = ['#22d3ee', '#3b82f6', '#10b981', '#8b5cf6', '#ef4444', '#f59e0b', '#9ca3af'];

  if (!this.hasSourceChartData) {
    return;
  }

  this.sourceChart = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels,
      datasets: [{
        data: values,
        backgroundColor: colors,
        borderWidth: 2,
        borderColor: 'rgba(8, 31, 62, 0.9)',
        hoverOffset: 3
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      aspectRatio: 1,
      plugins: { legend: { display: false } },
      cutout: '62%'
    }
  });
}

openConfirmation(message: string = 'Choose an export format for your candidate report. The file will include the current filtered candidate view with professional presentation and branding.'): void {
   const exportCandidates = this.getExportCandidates();
   const statusLabel = this.selectedStatus ? this.selectedStatus.replace(/_/g, ' ').replace(/\b\w/g, (m) => m.toUpperCase()) : 'All Candidates';
   const searchLabel = this.searchQuery.trim() || 'No search applied';
   const dialogRef = this.dialog.open(ConfirmationBox, {
      disableClose: true,
      width: '840px',
      maxWidth: 'calc(100vw - 48px)',
      autoFocus: false,
      panelClass: ['confirm-dialog', 'workflow-export-dialog'],
      backdropClass: ['workflow-action-backdrop', 'workflow-export-backdrop'],
      data: {
        mode: 'export',
        title: 'Export Candidate Data',
        message,
        confirmText: 'Export',
        cancelText: 'Cancel'
        ,
        exportSummary: {
          count: exportCandidates.length,
          statusLabel,
          searchLabel
        }
      }
    });

     dialogRef.afterClosed().subscribe(result => {
      if (result) {
        this.exportCandidateData(result as 'excel' | 'pdf' | 'word');
      }
    });
}

private getExportCandidates(): any[] {
  const statusFiltered = this.selectedStatus
    ? (this.candidatesData || []).filter(
        (c: any) => this.normalizeStatus(c?.status) === this.normalizeStatus(this.selectedStatus)
      )
    : (this.candidatesData || []);
  const searchFiltered = this.getSearchFilteredCandidates();
  return this.applyAttentionFilter(statusFiltered).filter((c: any) => searchFiltered.includes(c));
}

private buildCandidateExportRows(): CandidateExportRow[] {
  return this.getExportCandidates().map((candidate: any) => ({
    candidateName: candidate?.name || '',
    email: candidate?.email || '',
    role: candidate?.role || '',
    roleId: candidate?.role_id ? String(candidate.role_id) : '',
    recruiter: candidate?.recruiter || '',
    interviewer: this.getEvaluatorDisplayName(candidate),
    status: this.normalizeStatus(candidate?.status).replace(/\b\w/g, (m) => m.toUpperCase()),
    score: candidate?.score === null || candidate?.score === undefined || candidate?.score === '' ? 'N/A' : String(candidate.score),
    date: candidate?.date ? new Date(candidate.date).toLocaleString() : '',
    notes: candidate?.notes || '',
  }));
}

getEvaluatorDisplayName(candidate: any): string {
  const interviewType = (candidate?.interview_type || '').toString().trim().toLowerCase();
  if (interviewType === 'auto') {
    return 'Bot Managed';
  }
  return candidate?.interviewer || '-';
}

private exportCandidateData(format: 'excel' | 'pdf' | 'word'): void {
  const rows = this.buildCandidateExportRows();
  if (!rows.length) {
    window.alert('No candidates available for export.');
    return;
  }

  try {
    if (format === 'excel') {
      this.exportCandidatesAsExcel(rows);
      return;
    }
    const documentHtml = this.buildCandidateExportDocument(rows, format);
    if (format === 'word') {
      this.exportCandidatesAsWord(documentHtml);
      return;
    }
    this.exportCandidatesAsPdf();
  } catch (err) {
    console.error('Export failed', err);
    window.alert('Failed to export candidate data.');
  }
}

private exportCandidatesAsExcel(rows: CandidateExportRow[]): void {
  const workbook = XLSX.utils.book_new();
  const generatedAt = new Date();
  const statusLabel = this.selectedStatus ? this.selectedStatus.replace(/_/g, ' ') : 'All Candidates';
  const aoa: any[][] = [
    ['Shortlistii.com'],
    ['Candidate Data Export Report'],
    ['Professional candidate summary generated from the Shortlistii.com dashboard.'],
    [`Generated At: ${generatedAt.toLocaleString()}`],
    [`Status Filter: ${statusLabel}`],
    [`Search: ${this.searchQuery.trim() || 'No search applied'}`],
    [`Total Candidates: ${rows.length}`],
    [],
    ['Candidate Name', 'Email', 'Role', 'Role ID', 'Recruiter', 'Evaluator', 'Status', 'Score', 'Interview Date', 'Notes'],
    ...rows.map((row) => [
      row.candidateName,
      row.email,
      row.role,
      row.roleId,
      row.recruiter,
      row.interviewer,
      row.status,
      row.score,
      row.date,
      row.notes,
    ]),
  ];
  const worksheet = XLSX.utils.aoa_to_sheet(aoa);
  worksheet['!cols'] = [
    { wch: 24 }, { wch: 28 }, { wch: 24 }, { wch: 10 }, { wch: 22 },
    { wch: 22 }, { wch: 18 }, { wch: 10 }, { wch: 22 }, { wch: 32 },
  ];
  worksheet['!autofilter'] = { ref: `A6:J${rows.length + 6}` };
  XLSX.utils.book_append_sheet(workbook, worksheet, 'Candidates');
  const wbout = XLSX.write(workbook, { bookType: 'xlsx', type: 'array' });
  const blob = new Blob([wbout], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  });
  this.downloadBlob(blob, `candidate_data_${this.buildExportTimestamp()}.xlsx`);
}

private exportCandidatesAsWord(documentHtml: string): void {
  const blob = new Blob(['\ufeff', documentHtml], {
    type: 'application/msword',
  });
  this.downloadBlob(blob, `candidate_data_${this.buildExportTimestamp()}.doc`);
}

private exportCandidatesAsPdf(): void {
  const apiBaseUrl = getApiBaseUrl();
  const body = {
    rows: this.buildCandidateExportRows(),
    statusLabel: this.selectedStatus ? this.selectedStatus.replace(/_/g, ' ') : 'All Candidates',
    searchLabel: this.searchQuery.trim() || 'No search applied',
  };
  this.http.post(`${apiBaseUrl}/export-candidate-data-pdf/`, body, {
    responseType: 'blob',
  }).subscribe({
    next: (blob) => {
      this.downloadBlob(blob, `candidate_data_${this.buildExportTimestamp()}.pdf`);
    },
    error: (error) => {
      console.error('PDF export failed', error);
      window.alert('Failed to export candidate data as PDF.');
    }
  });
}

private buildCandidateExportDocument(rows: CandidateExportRow[], format: 'pdf' | 'word'): string {
  const title = 'Candidate Data Export';
  const generatedAt = new Date().toLocaleString();
  const statusLabel = this.selectedStatus ? this.selectedStatus.replace(/_/g, ' ') : 'All Candidates';
  const searchLabel = this.searchQuery.trim() || 'No search applied';
  const executiveSummary = `This report presents ${rows.length} candidate record${rows.length === 1 ? '' : 's'} from the current dashboard view. It is intended for recruiter review, hiring coordination, and stakeholder sharing.`;
  const scopeSummary = `Applied filters: status = ${statusLabel}; search = ${searchLabel}.`;
  const escaped = (value: string) =>
    (value || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');

  const rowsHtml = rows.map((row, index) => `
      <tr class="${index % 2 === 0 ? 'row-even' : 'row-odd'}">
        <td>${escaped(row.candidateName)}</td>
        <td>${escaped(row.email)}</td>
        <td>${escaped(row.role)}</td>
        <td>${escaped(row.roleId)}</td>
        <td>${escaped(row.recruiter)}</td>
        <td>${escaped(row.interviewer)}</td>
        <td>${escaped(row.status)}</td>
        <td>${escaped(row.score)}</td>
        <td>${escaped(row.date)}</td>
        <td>${escaped(row.notes)}</td>
      </tr>
    `).join('');

  return `
    <!DOCTYPE html>
    <html>
      <head>
        <meta charset="utf-8" />
        <title>${title}</title>
        <style>
          body { font-family: Arial, Helvetica, sans-serif; margin: 32px; color: #1d2a36; background: #ffffff; }
          .header { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; margin-bottom: 22px; padding-bottom: 18px; border-bottom: 2px solid #dce7f2; }
          .brand-site { font-size: 13px; color: #4d6780; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 10px; }
          .brand h1 { margin: 0; font-size: 26px; color: #123b69; }
          .brand p { margin: 6px 0 0; color: #58718a; font-size: 13px; }
          .meta { display: grid; gap: 8px; min-width: 260px; }
          .meta-card { border: 1px solid #d7e3ef; border-radius: 10px; padding: 10px 12px; background: #f8fbff; }
          .meta-card span { display: block; font-size: 11px; text-transform: uppercase; color: #6d8297; letter-spacing: 0.06em; }
          .meta-card strong { display: block; margin-top: 4px; font-size: 14px; color: #12263a; }
          .summary-panel { margin-bottom: 18px; border: 1px solid #d7e3ef; border-radius: 14px; background: linear-gradient(180deg, #f9fbfe, #f4f8fc); padding: 16px 18px; }
          .summary-panel h2 { margin: 0 0 8px; font-size: 16px; color: #123b69; }
          .summary-panel p { margin: 0 0 6px; color: #4d6780; font-size: 13px; line-height: 1.6; }
          .summary-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin-bottom: 18px; }
          .summary-tile { border: 1px solid #d7e3ef; border-radius: 12px; padding: 12px 14px; background: #ffffff; }
          .summary-tile span { display: block; font-size: 11px; color: #6d8297; text-transform: uppercase; letter-spacing: 0.06em; }
          .summary-tile strong { display: block; margin-top: 5px; color: #12263a; font-size: 18px; }
          table { width: 100%; border-collapse: collapse; font-size: 12px; }
          thead th { background: #123b69; color: #ffffff; padding: 10px 8px; text-align: left; }
          tbody td { border-bottom: 1px solid #dfe7ef; padding: 9px 8px; vertical-align: top; }
          .row-even { background: #f8fbff; }
          .row-odd { background: #ffffff; }
          .footer { margin-top: 18px; font-size: 11px; color: #6d8297; border-top: 1px solid #dce7f2; padding-top: 12px; }
          @media print {
            body { margin: 18px; }
            .meta-card { break-inside: avoid; }
            table { page-break-inside: auto; }
            tr { page-break-inside: avoid; page-break-after: auto; }
          }
        </style>
      </head>
      <body class="format-${format}">
        <div class="header">
          <div class="brand">
            <div class="brand-site">shortlistii.com</div>
            <h1>${title}</h1>
            <p>Corporate candidate report prepared for hiring reviews, recruiter coordination, and leadership sharing.</p>
          </div>
          <div class="meta">
            <div class="meta-card"><span>Generated At</span><strong>${escaped(generatedAt)}</strong></div>
            <div class="meta-card"><span>Status Filter</span><strong>${escaped(statusLabel)}</strong></div>
            <div class="meta-card"><span>Search Filter</span><strong>${escaped(searchLabel)}</strong></div>
          </div>
        </div>
        <div class="summary-panel">
          <h2>Report Overview</h2>
          <p>${escaped(executiveSummary)}</p>
          <p>${escaped(scopeSummary)}</p>
        </div>
        <div class="summary-grid">
          <div class="summary-tile"><span>Total Candidates</span><strong>${rows.length}</strong></div>
          <div class="summary-tile"><span>Export Format</span><strong>${escaped(format.toUpperCase())}</strong></div>
          <div class="summary-tile"><span>Prepared For</span><strong>Recruitment Operations</strong></div>
        </div>
        <table>
          <thead>
            <tr>
              <th>Candidate Name</th>
              <th>Email</th>
              <th>Role</th>
              <th>Role ID</th>
              <th>Recruiter</th>
              <th>Evaluator</th>
              <th>Status</th>
              <th>Score</th>
              <th>Interview Date</th>
              <th>Notes</th>
            </tr>
          </thead>
          <tbody>${rowsHtml}</tbody>
        </table>
        <div class="footer">Generated by shortlistii.com • Candidate Data Export Report • ${escaped(generatedAt)}</div>
      </body>
    </html>
  `;
}

private buildExportTimestamp(): string {
  return new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-');
}

private downloadBlob(blob: Blob, filename: string): void {
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
}

addUser(): void {
    this.addUserModalContext = 'candidate';
    const dialogRef = this.dialog.open(AddUser, {
      disableClose: true,
      width: '550px',
      data: { type: 'Candidate' }
    });

     dialogRef.afterClosed().subscribe(result => {
      this.addUserModalContext = null;
      if (result) {
        this.candidatesData.push(result);
        this.candidatesData = this.candidatesData.map((c: any) => {
            if ((c?.status || '').toString().toLowerCase() === 'assessment_pending') {
              return { ...c, status: 'assessment pending' };
            }
            return c;
          });
          this.assign_status();
          // Render chart after data is loaded and view is initialized
          setTimeout(() => this.renderChart(), 5);
      }
    });
  }

addRRole(): void {
  this.addUserModalContext = 'role';
  const dialogRef = this.dialog.open(AddUser, {
    disableClose: true,
    width: '550px',
    data: { type: 'Role' }
  });
    dialogRef.afterClosed().subscribe(result => {
    this.addUserModalContext = null;
    if (result) {
      this.rolesData.push(result);
      this.fetchRoleCatalog();
    }
  });
}

  openRoldeModal(role_id: any): void {
    this.activeRoleContext = this.getRoleContext(role_id) || { id: this.stringValue(role_id), title: '' };
    const dialogRef = this.dialog.open(RoleDetail, {
      width: 'min(1280px, 96vw)',
      maxWidth: '96vw',
      maxHeight: '92vh',
      panelClass: 'role-detail-dialog',
      data: { type: 'Role', role_id }
    });

    dialogRef.afterClosed().subscribe(result => {
      this.activeRoleContext = null;
      // if (result) {
      //   // Update the role in the rolesData array
      //   const index = this.rolesData.findIndex((r: any) => r.id === role_id);
      //   if (index !== -1) {
      //     this.rolesData[index] = result;
      //   }
      // }
    });
  }

  openWorkflowAction(mode: 'schedule' | 'bulk-assign' | 'bulk-aptitude' | 'bulk-interview' | 'evaluation-reviews', candidate?: any): void {
    this.activeWorkflowContext = { mode, candidate: candidate || null };
    const isEvaluationReviews = mode === 'evaluation-reviews';
    const dialogRef = this.dialog.open(WorkflowAction, {
      disableClose: true,
      width: isEvaluationReviews ? '1060px' : '940px',
      maxWidth: 'calc(100vw - 48px)',
      panelClass: isEvaluationReviews ? ['workflow-action-dialog', 'evaluation-reviews-dialog'] : 'workflow-action-dialog',
      backdropClass: isEvaluationReviews ? ['workflow-action-backdrop', 'evaluation-reviews-overlay'] : 'workflow-action-backdrop',
      autoFocus: false,
      data: {
        mode,
        candidates: this.candidatesData || [],
        preselectedCandidateId: candidate?.id || null,
      }
    });

    dialogRef.afterClosed().subscribe((result: any) => {
      this.activeWorkflowContext = null;
      if (!result) {
        return;
      }
      if (result.action === 'refresh') {
        this.fetchData();
        window.dispatchEvent(new CustomEvent('global-data-refresh'));
        return;
      }
      if (result.action === 'openProfile' && result.candidate) {
        this.profileUpdate(result.candidate);
        return;
      }
      if (result.action === 'openEvaluationSummary' && result.candidate) {
        this.openEvaluationSummary(result.candidate);
        return;
      }
      if (result.action === 'scheduleFurther' && result.candidate) {
        this.openWorkflowAction('schedule', result.candidate);
      }
    });
  }
}
