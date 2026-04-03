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

interface AttentionItem {
  key: AttentionFilterKey;
  title: string;
  icon: string;
  count: number;
  helperText: string;
  candidates: any[];
}

type AttentionFilterKey = 'overdue-feedback' | 'unscheduled-shortlisted' | 'pending-offers';

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
  actionLoading?: boolean;
  removing?: boolean;
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

@Component({
  selector: 'app-dashboard',
  standalone: true,
  templateUrl: './dashboard.html',
  styleUrls: ['./dashboard.scss'],
  imports: [CommonModule, MatDialogModule, Evaluators, Recruiters, Candidates, Activity, Analytics, TalentPool, FormsModule],
})
export class Dashboard implements OnInit, AfterViewInit, OnDestroy {
  private readonly destroyRef = inject(DestroyRef);
  private readonly apiTimeoutMs = 12000;
  data: any;
  loading = false;
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
  companySaving = false;
  selectedCompanyLogoFile: File | null = null;
  selectedCompanyLogoName = '';
  companyForm: CompanyProfileFormData = this.createEmptyCompanyForm();
  activeCandidates: any;
  searchQuery = '';
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
  talentPoolRoleId: string | null = null;
  @ViewChild('mobileNavPanel') mobileNavPanelRef?: ElementRef<HTMLElement>;
  @ViewChild('mobileNavToggleButton') mobileNavToggleButtonRef?: ElementRef<HTMLButtonElement>;
  @ViewChild('companyModalCard') companyModalCardRef?: ElementRef<HTMLElement>;
  @ViewChild('companyModalCloseButton') companyModalCloseButtonRef?: ElementRef<HTMLButtonElement>;
  private applicationIdsSeen = new Set<number>();
  private applicationPollTimer: ReturnType<typeof setInterval> | null = null;
  private applicationToastTimer: ReturnType<typeof setTimeout> | null = null;
  private previousFocusedElement: HTMLElement | null = null;
  private mobileNavPreviousFocusedElement: HTMLElement | null = null;
  private bodyScrollLocked = false;

  private sourceCanvas?: ElementRef<HTMLCanvasElement>;
  private sourceChart?: Chart;
  @ViewChild('sourcePerformanceCanvas', { static: false })
  set sourceCanvasRef(value: ElementRef<HTMLCanvasElement> | undefined) {
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
    this.unlockBodyScroll();
  }

  @HostListener('document:keydown', ['$event'])
  handleDocumentKeydown(event: KeyboardEvent): void {
    if (event.key === 'Escape') {
      if (this.companyDetailsModalOpen) {
        event.preventDefault();
        this.closeCompanyDetailsModal();
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

    if (this.mobileNavOpen) {
      this.trapFocus(event, this.mobileNavPanelRef?.nativeElement);
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
          return of([]); // Return empty array on error
        })
      )
      .subscribe(response => {
        this.data = response;
        this.loading = false;
        if(this.data?.Data){
          this.candidatesData = (this.data.Data.candidate_data || []).map((c: any) => ({
            ...c,
            status: this.normalizeStatus(c?.status)
          }));
          this.loginUser = this.data.Data.login_user.name;
          this.loginUserRole = this.data.Data.login_user.role || '';
          this.companyProfile = this.data.Data.company_profile || null;
          writeWorkspaceContext({
            loginUserName: this.loginUser,
            loginUserRole: this.loginUserRole,
            companyProfile: this.companyProfile,
          });
          this.hydrateCompanyViewModel();
          this.lastUpdatedAt = new Date();
          this.assign_status();
          // Render chart after data is loaded and view is initialized
          setTimeout(() => this.renderChart(), 5);
        }
      });
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
  }

  closePendingRequestsModal(): void {
    this.pendingRequestsModalOpen = false;
  }

  openCompanyDetailsModal(): void {
    if (this.companyProfile) {
      this.previousFocusedElement = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      this.companyEditMode = false;
      this.selectedCompanyLogoFile = null;
      this.selectedCompanyLogoName = '';
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
          return of(null);
        })
      )
      .subscribe((response) => {
        if (!response?.Success) {
          application.actionLoading = false;
          return;
        }

        application.removing = true;
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
    const dialogRef = this.dialog.open(CandidateProfile, {
      width: '95vw',
      maxWidth: '980px',
      maxHeight: '92vh',
      panelClass: 'candidate-profile-dialog',
      autoFocus: false,
      data: { candidate }
    });

     dialogRef.afterClosed().subscribe((result: any) => {
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
  this.shortlistedCandidates = list.filter((c: any) => this.normalizeStatus(c?.status) === 'shortlisted');
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
    const shouldLock = this.mobileNavOpen || this.companyDetailsModalOpen;
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

setStatusFilter(status: string | null) {
  this.selectedStatus = status;
  this.attentionFilter = null;
  this.currentPage = 1; // reset to first page after filtering
}

clearSearch(): void {
  this.searchQuery = '';
  this.currentPage = 1;
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
        return of(null);
      })
    )
    .subscribe((response) => {
      this.companySaving = false;
      if (!response?.Success || !response?.Data) {
        return;
      }
      this.companyProfile = response.Data as CompanyProfileData;
      this.hydrateCompanyViewModel();
      this.companyEditMode = false;
      this.selectedCompanyLogoFile = null;
      this.selectedCompanyLogoName = '';
      this.lastUpdatedAt = new Date();
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
      el.scrollIntoView({ behavior: 'smooth', block: 'start' });
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
      width: '720px',
      maxWidth: '94vw',
      autoFocus: false,
      panelClass: 'confirm-dialog',
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
    const dialogRef = this.dialog.open(AddUser, {
      disableClose: true,
      width: '550px',
      data: { type: 'Candidate' }
    });

     dialogRef.afterClosed().subscribe(result => {
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
  const dialogRef = this.dialog.open(AddUser, {
    disableClose: true,
    width: '550px',
    data: { type: 'Role' }
  });
    dialogRef.afterClosed().subscribe(result => {
    if (result) {
      this.rolesData.push(result);
      this.fetchRoleCatalog();
    }
  });
}

  openRoldeModal(role_id: any): void {
    const dialogRef = this.dialog.open(RoleDetail, {
      width: '95vw',
      maxWidth: '920px',
      maxHeight: '92vh',
      panelClass: 'role-detail-dialog',
      data: { type: 'Role', role_id }
    });

    dialogRef.afterClosed().subscribe(result => {
      // if (result) {
      //   // Update the role in the rolesData array
      //   const index = this.rolesData.findIndex((r: any) => r.id === role_id);
      //   if (index !== -1) {
      //     this.rolesData[index] = result;
      //   }
      // }
    });
  }

  openWorkflowAction(mode: 'schedule' | 'bulk-assign' | 'evaluation-reviews', candidate?: any): void {
    const dialogRef = this.dialog.open(WorkflowAction, {
      disableClose: true,
      width: mode === 'evaluation-reviews' ? '980px' : '900px',
      maxWidth: '95vw',
      panelClass: 'workflow-action-dialog',
      autoFocus: false,
      data: {
        mode,
        candidates: this.candidatesData || [],
        preselectedCandidateId: candidate?.id || null,
      }
    });

    dialogRef.afterClosed().subscribe((result: any) => {
      if (!result) {
        return;
      }
      if (result.action === 'refresh') {
        this.fetchData();
        window.dispatchEvent(new CustomEvent('global-data-refresh'));
        if (result.message) {
          this.showApplicationToast(result.message);
        }
        return;
      }
      if (result.action === 'openProfile' && result.candidate) {
        this.profileUpdate(result.candidate);
        return;
      }
      if (result.action === 'scheduleFurther' && result.candidate) {
        this.openWorkflowAction('schedule', result.candidate);
      }
    });
  }
}
