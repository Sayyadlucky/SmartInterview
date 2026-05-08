import { Component, ElementRef, HostListener, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { FormsModule } from '@angular/forms';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { catchError, finalize, of, timeout } from 'rxjs';
import { RoleDetail } from '../app-modal/role-detail/role-detail';
import { AddUser } from '../app-modal/add-user/add-user';
import { getApiBaseUrl } from '../core/api-base';
import { readWorkspaceContext, writeWorkspaceContext } from '../core/workspace-context';

interface JobCard {
  id: number;
  name: string;
  description: string;
  description_preview?: string;
  vacancies: number;
  applications: number;
  hired: number;
  inprogress: number;
  open_positions: number;
  job_type: string;
  location: string;
  salary_range: string;
  experience_required: string;
  status: string;
  status_label: string;
  date_display: string;
  date_iso: string;
  recruiters: string[];
  recruiter_count: number;
  highlights: string[];
  company?: {
    display_name?: string;
    legal_name?: string;
    industry?: string;
    city?: string;
    state?: string;
    logo_url?: string;
  } | null;
  recruiter_summary?: string;
  visible_highlights?: string[];
  resolved_logo_url?: string;
}

interface CompanyProfileSummary {
  legal_name?: string;
  display_name?: string;
  description?: string;
  industry?: string;
  website?: string;
  careers_page?: string;
  logo_url?: string;
  city?: string;
  state?: string;
  country?: string;
  headquarters?: string;
}

type JobStatusFilter = 'all' | 'active' | 'closed' | 'hired' | 'canceled';

@Component({
  selector: 'app-jobs',
  standalone: true,
  imports: [CommonModule, FormsModule, MatDialogModule],
  templateUrl: './jobs.html',
  styleUrl: './jobs.scss',
})
export class Jobs {
  @ViewChild('mobileNavPanel') mobileNavPanelRef?: ElementRef<HTMLElement>;
  @ViewChild('mobileNavToggleButton') mobileNavToggleButtonRef?: ElementRef<HTMLButtonElement>;
  @ViewChild('quickViewDialog') quickViewDialogRef?: ElementRef<HTMLElement>;
  @ViewChild('quickViewCloseButton') quickViewCloseButtonRef?: ElementRef<HTMLButtonElement>;
  @ViewChild('jobsSearchField') jobsSearchFieldRef?: ElementRef<HTMLInputElement>;

  loading = true;
  mobileNavOpen = false;
  loginUser = '';
  loginUserRole = '';
  companyProfile: CompanyProfileSummary | null = null;
  dashboardCompanyLogoUrl = '';
  companyOverviewItems: Array<{ label: string; value: string; icon: string }> = [];
  jobs: JobCard[] = [];
  filteredJobsState: JobCard[] = [];
  searchQuery = '';
  activeStatus: JobStatusFilter = 'all';
  selectedJob: JobCard | null = null;
  loadError = '';
  private readonly imageErrorJobIds = new Set<number>();
  private readonly closingJobIds = new Set<number>();
  private previousFocusedElement: HTMLElement | null = null;
  private mobileNavPreviousFocusedElement: HTMLElement | null = null;
  private bodyScrollLocked = false;
  private readonly apiTimeoutMs = 12000;

  readonly statusFilters: Array<{ key: JobStatusFilter; label: string }> = [
    { key: 'all', label: 'All Roles' },
    { key: 'active', label: 'Active' },
    { key: 'closed', label: 'Closed' },
    { key: 'hired', label: 'Hired' },
    { key: 'canceled', label: 'Canceled' },
  ];

  constructor(private http: HttpClient, private dialog: MatDialog) {}

  ngOnInit(): void {
    this.loadJobsPage();
  }

  ngOnDestroy(): void {
    this.unlockBodyScroll();
  }

  @HostListener('document:keydown', ['$event'])
  handleDocumentKeydown(event: KeyboardEvent): void {
    if (event.key === 'Escape') {
      if (this.selectedJob) {
        event.preventDefault();
        this.closeQuickView();
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

    if (this.selectedJob) {
      this.trapFocus(event, this.quickViewDialogRef?.nativeElement);
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

  loadJobsPage(): void {
    this.loading = true;
    this.loadError = '';
    const apiBaseUrl = getApiBaseUrl();
    const cachedWorkspaceContext = readWorkspaceContext();

    if (cachedWorkspaceContext) {
      this.loginUser = cachedWorkspaceContext.loginUserName;
      this.loginUserRole = cachedWorkspaceContext.loginUserRole;
      this.companyProfile = cachedWorkspaceContext.companyProfile as CompanyProfileSummary | null;
      this.dashboardCompanyLogoUrl = this.companyProfile?.logo_url || '';
      this.companyOverviewItems = [
        {
          label: 'Industry',
          value: this.companyProfile?.industry || 'Not specified',
          icon: 'ph-buildings',
        },
        {
          label: 'HQ / Base',
          value: this.companyLocation,
          icon: 'ph-map-pin-line',
        },
        {
          label: 'Website',
          value: this.companyProfile?.website || 'Not available',
          icon: 'ph-globe-hemisphere-west',
        },
      ];
    }

    if (!cachedWorkspaceContext) {
      this.http.get<any>(`${apiBaseUrl}/dashboard-data/`)
        .pipe(
          timeout(this.apiTimeoutMs),
          catchError(() => of(null)),
        )
        .subscribe((dashboard) => {
          this.loginUser = dashboard?.Data?.login_user?.name || '';
          this.loginUserRole = dashboard?.Data?.login_user?.role || '';
          this.companyProfile = dashboard?.Data?.company_profile || null;
          this.dashboardCompanyLogoUrl = this.companyProfile?.logo_url || '';
          this.companyOverviewItems = [
            {
              label: 'Industry',
              value: this.companyProfile?.industry || 'Not specified',
              icon: 'ph-buildings',
            },
            {
              label: 'HQ / Base',
              value: this.companyLocation,
              icon: 'ph-map-pin-line',
            },
            {
              label: 'Website',
              value: this.companyProfile?.website || 'Not available',
              icon: 'ph-globe-hemisphere-west',
            },
          ];
          writeWorkspaceContext({
            loginUserName: this.loginUser,
            loginUserRole: this.loginUserRole,
            companyProfile: this.companyProfile,
          });
          this.jobs = this.jobs.map((job) => ({
            ...job,
            resolved_logo_url: job.company?.logo_url || this.dashboardCompanyLogoUrl || '',
          }));
          this.refreshFilteredJobs();
        });
    }

    this.http.get<any>(`${apiBaseUrl}/get-role-list/`)
      .pipe(
        timeout(this.apiTimeoutMs),
        catchError(() => {
          this.loadError = 'Unable to load job postings right now.';
          return of(null);
        }),
        finalize(() => {
          this.loading = false;
        }),
      )
      .subscribe((roles) => {
        this.jobs = Array.isArray(roles?.RoleData)
          ? roles.RoleData.map((job: JobCard) => this.decorateJob(job))
          : [];
        this.refreshFilteredJobs();
      });
  }

  get pageTitle(): string {
    return this.loginUserRole === 'recruiter' ? 'Your Job Portfolio' : 'Job Posting Oversight';
  }

  get pageSubtitle(): string {
    return this.loginUserRole === 'recruiter'
      ? 'Roles assigned to you, with live hiring momentum and quick access to each brief.'
      : 'A centralized view of active job postings across your hiring workspace, structured for quick review and informed action.';
  }

  get jobsPanelTitle(): string {
    return this.activeStatus === 'all'
      ? 'Job Postings'
      : `${this.getStatusFilterLabel(this.activeStatus)} Job Postings`;
  }

  get jobsPanelSubtitle(): string {
    const count = this.filteredJobsState.length;
    const noun = count === 1 ? 'posting' : 'postings';
    if (this.activeStatus === 'all') {
      return `${count} ${noun} in view`;
    }
    return `${count} ${this.getStatusFilterLabel(this.activeStatus).toLowerCase()} ${noun} in view`;
  }

  get loadingMessage(): string {
    return 'Loading your latest job postings and workspace signals...';
  }

  get emptyStateTitle(): string {
    return this.searchQuery.trim() || this.activeStatus !== 'all'
      ? 'No job postings matched this view'
      : 'No job postings yet';
  }

  get emptyStateCopy(): string {
    if (this.searchQuery.trim() || this.activeStatus !== 'all') {
      return 'Adjust the search or status filters, or create a new posting to continue hiring activity.';
    }
    return 'Start by publishing a role to bring hiring activity into this workspace.';
  }

  get totalVacancies(): number {
    return this.filteredJobsState.reduce((sum, job) => sum + Number(job.vacancies || 0), 0);
  }

  get totalOpenPositions(): number {
    return this.filteredJobsState.reduce((sum, job) => sum + Number(job.open_positions || 0), 0);
  }

  get totalApplications(): number {
    return this.filteredJobsState.reduce((sum, job) => sum + Number(job.applications || 0), 0);
  }

  get activeRoleCount(): number {
    return this.filteredJobsState.filter((job) => job.status === 'active').length;
  }

  get roleCoverageLabel(): string {
    if (!this.filteredJobsState.length) return 'No roles in the current view';
    const filled = this.filteredJobsState.reduce((sum, job) => sum + Math.min(job.hired || 0, job.vacancies || 0), 0);
    const total = this.filteredJobsState.reduce((sum, job) => sum + (job.vacancies || 0), 0);
    if (!total) return 'Headcount not defined';
    return `${Math.round((filled / total) * 100)}% delivery coverage`;
  }

  get companyDisplayName(): string {
    return this.companyProfile?.display_name || this.companyProfile?.legal_name || 'Company Profile';
  }

  get companyLocation(): string {
    const parts = [
      this.companyProfile?.city,
      this.companyProfile?.state,
      this.companyProfile?.country,
    ].filter(Boolean);
    return parts.join(', ') || this.companyProfile?.headquarters || 'Location not available';
  }

  get sidebarSummaryStats(): Array<{ label: string; value: string; icon: string }> {
    return [
      { label: 'Roles', value: String(this.filteredJobsState.length), icon: 'ph-briefcase' },
      { label: 'Open', value: String(this.totalOpenPositions), icon: 'ph-briefcase-metal' },
      { label: 'Pipeline', value: String(this.totalApplications), icon: 'ph-git-branch' },
    ];
  }

  get hasCompanyDescription(): boolean {
    return !!(this.companyProfile?.description || '').trim();
  }

  getStatusFilterLabel(filter: JobStatusFilter): string {
    return this.statusFilters.find((item) => item.key === filter)?.label || 'All Roles';
  }

  getStatusFilterId(filter: JobStatusFilter): string {
    return `jobs-status-filter-${filter}`;
  }

  setStatusFilter(filter: JobStatusFilter): void {
    this.activeStatus = filter;
    this.refreshFilteredJobs();
  }

  onSearchQueryChange(value: string): void {
    this.searchQuery = value;
    this.refreshFilteredJobs();
  }

  openQuickView(job: JobCard, trigger?: HTMLElement): void {
    this.previousFocusedElement = trigger || (document.activeElement instanceof HTMLElement ? document.activeElement : null);
    this.selectedJob = job;
    this.updateBodyScrollLock();
    setTimeout(() => this.quickViewCloseButtonRef?.nativeElement.focus(), 0);
  }

  openQuickViewFromEvent(job: JobCard, event: Event): void {
    const trigger = event.currentTarget instanceof HTMLElement ? event.currentTarget : undefined;
    this.openQuickView(job, trigger);
  }

  closeQuickView(): void {
    if (!this.selectedJob) {
      return;
    }
    this.selectedJob = null;
    this.updateBodyScrollLock();
    setTimeout(() => this.previousFocusedElement?.focus(), 0);
  }

  openRoleDetails(job: JobCard): void {
    this.closeQuickView();
    this.dialog.open(RoleDetail, {
      width: 'min(1120px, 96vw)',
      maxWidth: '96vw',
      maxHeight: '92vh',
      panelClass: 'role-detail-dialog',
      autoFocus: false,
      data: { role_id: job.id },
    });
  }

  getTalentPoolUrl(job?: JobCard | null): string {
    if (job?.id) {
      return `/dashboard?tab=ai-talent-pool&role=${encodeURIComponent(String(job.id))}`;
    }
    return '/dashboard?tab=ai-talent-pool';
  }

  postJob(): void {
    const dialogRef = this.dialog.open(AddUser, {
      width: 'min(1080px, 96vw)',
      maxWidth: '96vw',
      maxHeight: '94vh',
      autoFocus: false,
      data: { type: 'Role' },
    });

    dialogRef.afterClosed().subscribe((result) => {
      if (result) {
        this.loadJobsPage();
      }
    });
  }

  getStatusClass(status: string): string {
    return `status-${(status || 'active').toLowerCase()}`;
  }

  getRecruiterInitials(name: string): string {
    const parts = (name || '').trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return 'NA';
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
  }

  getJobLogoUrl(job: JobCard): string {
    if (!job || this.imageErrorJobIds.has(job.id)) {
      return '';
    }
    return job.resolved_logo_url || '';
  }

  handleJobLogoError(job: JobCard): void {
    if (!job?.id) {
      return;
    }
    this.imageErrorJobIds.add(job.id);
    const target = this.jobs.find((item) => item.id === job.id);
    if (target) {
      target.resolved_logo_url = '';
    }
    this.refreshFilteredJobs();
  }

  trackByJob(index: number, job: JobCard): number {
    return job.id || index;
  }

  isClosingJob(job: JobCard): boolean {
    return !!job?.id && this.closingJobIds.has(job.id);
  }

  closeJob(job: JobCard): void {
    if (!job?.id || this.closingJobIds.has(job.id) || job.status === 'closed') {
      return;
    }

    this.closingJobIds.add(job.id);
    const apiBaseUrl = getApiBaseUrl();
    const body = new URLSearchParams();
    body.set('vacancy_id', String(job.id));

    this.http.post<any>(`${apiBaseUrl}/close-vacancy/`, body.toString(), {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    })
      .pipe(
        catchError(() => {
          this.loadError = 'Unable to close this job posting right now.';
          return of(null);
        }),
        finalize(() => {
          this.closingJobIds.delete(job.id);
        }),
      )
      .subscribe((response) => {
        if (!response?.Success) {
          this.loadError = response?.Error || 'Unable to close this job posting right now.';
          return;
        }

        const nextStatus = response?.Data?.status || 'closed';
        const nextStatusLabel = response?.Data?.status_label || 'Closed';

        this.jobs = this.jobs.map((item) => item.id === job.id
          ? {
              ...item,
              status: nextStatus,
              status_label: nextStatusLabel,
            }
          : item);

        if (this.selectedJob?.id === job.id) {
          this.selectedJob = {
            ...this.selectedJob,
            status: nextStatus,
            status_label: nextStatusLabel,
          };
        }

        this.refreshFilteredJobs();
      });
  }

  private decorateJob(job: JobCard): JobCard {
    const resolvedLogoUrl = job.company?.logo_url || this.dashboardCompanyLogoUrl || '';
    const recruiterSummary = this.buildRecruiterSummary(job.recruiters || []);

    return {
      ...job,
      recruiter_summary: recruiterSummary,
      visible_highlights: this.computeVisibleHighlights(job),
      resolved_logo_url: resolvedLogoUrl,
    };
  }

  private refreshFilteredJobs(): void {
    const term = this.searchQuery.trim().toLowerCase();
    this.filteredJobsState = this.jobs.filter((job) => {
      const matchesStatus = this.matchesStatusFilter(job.status, this.activeStatus);
      if (!matchesStatus) {
        return false;
      }
      if (!term) {
        return true;
      }
      return [
        job.name,
        job.location,
        job.job_type,
        job.salary_range,
        job.experience_required,
        job.company?.display_name,
        job.company?.legal_name,
        job.recruiter_summary,
        ...(job.recruiters || []),
      ]
        .map((value) => (value || '').toString().toLowerCase())
        .some((value) => value.includes(term));
    });

    if (this.selectedJob?.id) {
      const refreshedSelectedJob = this.jobs.find((job) => job.id === this.selectedJob?.id) || null;
      this.selectedJob = refreshedSelectedJob ? { ...refreshedSelectedJob } : null;
    }
  }

  private buildRecruiterSummary(recruiters: string[]): string {
    if (!recruiters.length) {
      return 'Recruiter assignment pending';
    }
    if (recruiters.length <= 2) {
      return recruiters.join(', ');
    }
    return `${recruiters.slice(0, 2).join(', ')} +${recruiters.length - 2} more`;
  }

  private normalizeText(value: string): string {
    return (value || '')
      .trim()
      .toLowerCase()
      .replace(/\s+/g, ' ');
  }

  private toComparableJobLabel(value: string): string {
    return this.normalizeText(value)
      .replace(/\b(role|job|position|opening|vacancy|required|requirement)\b/g, ' ')
      .replace(/[^\w\s]/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();
  }

  private computeVisibleHighlights(job: JobCard | null | undefined): string[] {
    if (!job?.highlights?.length) {
      return [];
    }

    const normalizedTitle = this.normalizeText(job.name);
    const comparableTitle = this.toComparableJobLabel(job.name);
    const seen = new Set<string>();

    return job.highlights.filter((highlight) => {
      const normalizedHighlight = this.normalizeText(highlight);
      const comparableHighlight = this.toComparableJobLabel(highlight);
      if (!normalizedHighlight) {
        return false;
      }
      if (normalizedHighlight === normalizedTitle) {
        return false;
      }
      if (
        comparableHighlight &&
        comparableTitle &&
        (
          comparableHighlight === comparableTitle ||
          comparableHighlight.includes(comparableTitle) ||
          comparableTitle.includes(comparableHighlight)
        )
      ) {
        return false;
      }
      if (seen.has(normalizedHighlight)) {
        return false;
      }
      seen.add(normalizedHighlight);
      return true;
    });
  }

  private matchesStatusFilter(jobStatus: string | undefined, filter: JobStatusFilter): boolean {
    if (filter === 'all') {
      return true;
    }

    const normalizedStatus = (jobStatus || '').trim().toLowerCase();
    if (!normalizedStatus) {
      return false;
    }

    if (filter === 'canceled') {
      return normalizedStatus === 'canceled' || normalizedStatus === 'cancelled';
    }

    return normalizedStatus === filter;
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
    const shouldLock = this.mobileNavOpen || !!this.selectedJob;
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
}
