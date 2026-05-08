import { Component, OnDestroy, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { catchError } from 'rxjs/operators';
import { of } from 'rxjs';
import { FormsModule } from '@angular/forms';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { AddUser } from '../app-modal/add-user/add-user';
import { DigitsOnlyDirective } from '../core/digits-only.directive';

interface Recruiter {
  id: number;
  user_id?: number;
  profile_id?: number;
  name: string;
  email: string;
  role: string;
  phone?: string;
  gender?: string;
  interviewers_count?: number;
  candidates_count?: number;
}

interface RecruiterResponse {
  Success: boolean;
  Error?: string | null;
  RecruiterData?: Recruiter[];
  Data?: { RecruiterData?: Recruiter[] };
}

interface RecruiterInterviewItem {
  id: number;
  candidate: string;
  status: string;
  score?: number | null;
  role?: string;
  date: string;
  recruiter?: string;
  interviewer?: string;
}

interface RecruiterInterviewResponse {
  Success: boolean;
  Error?: string | null;
  Interviews?: RecruiterInterviewItem[];
}

interface RecruiterAlert {
  type: 'warning' | 'info' | 'success';
  title: string;
  message: string;
}

@Component({
  selector: 'app-recruiters',
  imports: [CommonModule, FormsModule, MatDialogModule, DigitsOnlyDirective],
  templateUrl: './recruiters.html',
  styleUrl: './recruiters.scss'
})
export class Recruiters implements OnInit, OnDestroy {
  loading = false;
  errorMessage = '';
  searchTerm = '';
  recruiters: Recruiter[] = [];
  filteredRecruiters: Recruiter[] = [];
  selectedRecruiter: Recruiter | null = null;
  recruiterSummaryCards: Array<{ label: string; value: number; helper: string; icon: string }> = [];
  selectedRecruiterHighlights: Array<{ title: string; value: string; tone: 'neutral' | 'accent'; helper: string }> = [];
  recruiterNarrative = '';
  candidateLoadPercent = 0;
  evaluatorCoveragePercent = 0;
  detailLoading = false;
  detailErrorMessage = '';
  recruiterInterviews: RecruiterInterviewItem[] = [];
  performanceYear = new Date().getFullYear();
  minPerformanceYear = new Date().getFullYear();
  maxPerformanceYear = new Date().getFullYear();
  yearlyPerformanceBars: Array<{ label: string; count: number }> = [];
  insightsMonth = new Date().getMonth();
  insightsYear = new Date().getFullYear();
  minInsightsMonthIndex = new Date().getFullYear() * 12 + new Date().getMonth();
  maxInsightsMonthIndex = new Date().getFullYear() * 12 + new Date().getMonth();
  selectedMonthTopRoles: Array<{ role: string; count: number }> = [];
  selectedMonthInterviews = 0;
  selectedMonthActiveDays = 0;
  selectedMonthScheduledCount = 0;
  selectedMonthBusiestDayLabel = '-';
  selectedMonthBusiestCount = 0;
  selectedMonthAvgPerActiveDay = 0;
  isEditingProfile = false;
  savingProfile = false;
  saveErrorMessage = '';
  saveSuccessMessage = '';
  editableRecruiter = {
    name: '',
    email: '',
    phone: '',
    gender: 'other'
  };
  private readonly refreshListener = () => this.loadRecruiters();

  constructor(private http: HttpClient, private dialog: MatDialog) {}

  ngOnInit(): void {
    window.addEventListener('candidate-status-updated', this.refreshListener as EventListener);
    window.addEventListener('global-data-refresh', this.refreshListener as EventListener);
    this.loadRecruiters();
  }

  ngOnDestroy(): void {
    window.removeEventListener('candidate-status-updated', this.refreshListener as EventListener);
    window.removeEventListener('global-data-refresh', this.refreshListener as EventListener);
  }

  get totalRecruiters(): number {
    return this.recruiters.length;
  }

  get displayedRecruiters(): number {
    return this.filteredRecruiters.length;
  }

  get totalManagedCandidates(): number {
    return this.recruiters.reduce((sum, recruiter) => sum + (recruiter.candidates_count || 0), 0);
  }

  get totalLinkedEvaluators(): number {
    return this.recruiters.reduce((sum, recruiter) => sum + (recruiter.interviewers_count || 0), 0);
  }

  get averageCandidateLoad(): number {
    if (!this.totalRecruiters) return 0;
    return Math.round(this.totalManagedCandidates / this.totalRecruiters);
  }

  get recruiterAlerts(): RecruiterAlert[] {
    if (!this.selectedRecruiter || this.detailLoading) {
      return [];
    }

    const alerts: RecruiterAlert[] = [];
    const now = new Date();
    const upcomingThreshold = now.getTime() + (3 * 24 * 60 * 60 * 1000);
    const scheduledItems = this.recruiterInterviews.filter((item) => this.normalizeStatus(item.status) === 'scheduled');
    const upcomingScheduled = scheduledItems.filter((item) => {
      const date = this.parseDate(item.date);
      if (!date) return false;
      const time = date.getTime();
      return time >= now.getTime() && time <= upcomingThreshold;
    }).length;
    const overdueScheduled = scheduledItems.filter((item) => {
      const date = this.parseDate(item.date);
      return !!date && date.getTime() < now.getTime();
    }).length;

    const candidateLoad = this.selectedRecruiter.candidates_count || 0;
    const evaluatorCoverage = this.selectedRecruiter.interviewers_count || 0;

    if (overdueScheduled > 0) {
      alerts.push({
        type: 'warning',
        title: 'Overdue scheduled interviews',
        message: `${overdueScheduled} scheduled interview${overdueScheduled === 1 ? '' : 's'} appear to be in the past and may need follow-up.`,
      });
    }

    if (upcomingScheduled > 0) {
      alerts.push({
        type: 'info',
        title: 'Interviews scheduled soon',
        message: `${upcomingScheduled} interview${upcomingScheduled === 1 ? '' : 's'} are scheduled within the next 3 days.`,
      });
    }

    if (candidateLoad > Math.max(8, this.averageCandidateLoad + 2)) {
      alerts.push({
        type: 'warning',
        title: 'High candidate load',
        message: `${this.selectedRecruiter.name} is handling ${candidateLoad} candidates, above the current team average of ${this.averageCandidateLoad}.`,
      });
    }

    if (evaluatorCoverage === 0) {
      alerts.push({
        type: 'warning',
        title: 'No evaluator coverage',
        message: 'No evaluators are currently linked to this recruiter. Review assignment coverage.',
      });
    } else if (evaluatorCoverage === 1 && candidateLoad >= 4) {
      alerts.push({
        type: 'info',
        title: 'Low evaluator coverage',
        message: 'Only 1 evaluator is linked while candidate volume is building. Consider expanding evaluator support.',
      });
    }

    if (this.selectedMonthInterviews === 0) {
      alerts.push({
        type: 'info',
        title: 'No recent activity this month',
        message: 'This recruiter has no recorded interview activity in the current insights month.',
      });
    }

    if (!alerts.length) {
      alerts.push({
        type: 'success',
        title: 'All clear',
        message: 'No immediate recruiter workflow issues are surfacing from the current interview and ownership data.',
      });
    }

    return alerts.slice(0, 4);
  }

  private getApiBaseUrl(): string {
    let portNumber = '';
    if (window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost') {
      portNumber = '8000';
    }
    return `${window.location.protocol}//${window.location.hostname}:${portNumber}`;
  }

  private parseRecruiterData(response: RecruiterResponse | any): Recruiter[] {
    return response?.RecruiterData || response?.Data?.RecruiterData || [];
  }

  loadRecruiters(): void {
    this.loading = true;
    this.errorMessage = '';
    this.http.get<RecruiterResponse>(`${this.getApiBaseUrl()}/get-hr-list/`)
      .pipe(
        catchError((error) => {
          console.error('Error fetching recruiters', error);
          this.loading = false;
          this.errorMessage = 'Failed to load HR records.';
          return of({ Success: false, RecruiterData: [] } as RecruiterResponse);
        })
      )
      .subscribe((response) => {
        this.recruiters = this.parseRecruiterData(response);
        this.applyFilter();
        this.updateSummaryCards();
        if (this.selectedRecruiter) {
          this.selectedRecruiter = this.filteredRecruiters.find((item) => item.id === this.selectedRecruiter?.id) || null;
        }
        this.updateSelectedRecruiterState();
        this.loadRecruiterAnalytics();
        this.loading = false;
      });
  }

  addRecruiter(): void {
    const dialogRef = this.dialog.open(AddUser, {
      width: '550px',
      data: { type: 'Recruiter' }
    });

    dialogRef.afterClosed().subscribe((result) => {
      if (!result) return;
      this.loadRecruiters();
    });
  }

  clearSearch(): void {
    this.searchTerm = '';
    this.applyFilter();
  }

  applyFilter(): void {
    const term = this.searchTerm.trim().toLowerCase();
    if (!term) {
      this.filteredRecruiters = this.recruiters;
    } else {
      this.filteredRecruiters = this.recruiters.filter((recruiter) =>
        [
          recruiter.name,
          recruiter.email,
          recruiter.phone,
          recruiter.role,
          recruiter.gender,
        ]
          .map((value) => (value || '').toString().toLowerCase())
          .some((value) => value.includes(term))
      );
    }

    if (this.selectedRecruiter && !this.filteredRecruiters.some((recruiter) => recruiter.id === this.selectedRecruiter?.id)) {
      this.selectedRecruiter = null;
      this.detailLoading = false;
      this.detailErrorMessage = '';
      this.recruiterInterviews = [];
      this.updateSelectedRecruiterState();
      this.loadRecruiterAnalytics();
    }
  }

  openRecruiter(recruiter: Recruiter): void {
    this.selectedRecruiter = recruiter;
    this.isEditingProfile = false;
    this.saveErrorMessage = '';
    this.saveSuccessMessage = '';
    this.updateSelectedRecruiterState();
    this.loadRecruiterAnalytics();
  }

  openEditProfile(): void {
    if (!this.selectedRecruiter || this.savingProfile) return;
    this.hydrateEditableRecruiter();
    this.saveErrorMessage = '';
    this.saveSuccessMessage = '';
    this.isEditingProfile = true;
  }

  cancelEditProfile(): void {
    if (this.savingProfile) return;
    this.isEditingProfile = false;
    this.saveErrorMessage = '';
    this.saveSuccessMessage = '';
    this.hydrateEditableRecruiter();
  }

  saveRecruiterProfile(): void {
    const recruiterId = this.selectedRecruiter?.user_id || this.selectedRecruiter?.id;
    const name = (this.editableRecruiter.name || '').trim();
    const email = (this.editableRecruiter.email || '').trim();
    if (!recruiterId || !name || !email || this.savingProfile) {
      this.saveErrorMessage = 'Name and email are required.';
      this.saveSuccessMessage = '';
      return;
    }

    const body = new URLSearchParams();
    body.set('recruiter_id', String(recruiterId));
    body.set('profile_type', 'recruiter');
    body.set('name', name);
    body.set('email', email);
    body.set('phone', (this.editableRecruiter.phone || '').trim());
    body.set('gender', (this.editableRecruiter.gender || 'other').trim().toLowerCase());

    this.savingProfile = true;
    this.saveErrorMessage = '';
    this.saveSuccessMessage = '';

    this.http.post<any>(`${this.getApiBaseUrl()}/update-recruiter-details/`, body.toString(), {
      headers: new HttpHeaders({ 'Content-Type': 'application/x-www-form-urlencoded' })
    })
      .pipe(
        catchError((error) => {
          console.error('Error updating recruiter details', error);
          this.savingProfile = false;
          this.saveSuccessMessage = '';
          this.saveErrorMessage = error?.error?.Error || 'Failed to update recruiter details.';
          return of({ Success: false, Error: this.saveErrorMessage });
        })
      )
      .subscribe((response) => {
        if (!response?.Success) {
          this.savingProfile = false;
          this.saveSuccessMessage = '';
          this.saveErrorMessage = response?.Error || 'Failed to update recruiter details.';
          return;
        }

        const updated = response?.RecruiterData || {};
        if (this.selectedRecruiter) {
          this.selectedRecruiter = {
            ...this.selectedRecruiter,
            id: updated.id || this.selectedRecruiter.id,
            user_id: updated.user_id || this.selectedRecruiter.user_id || this.selectedRecruiter.id,
            profile_id: updated.profile_id || this.selectedRecruiter.profile_id,
            name: updated.name || name,
            email: updated.email || email,
            phone: updated.phone ?? this.editableRecruiter.phone,
            gender: updated.gender || this.editableRecruiter.gender,
          };
        }

        this.recruiters = this.recruiters.map((recruiter) =>
          recruiter.id === (updated.id || recruiterId)
            ? {
                ...recruiter,
                name: updated.name || name,
                email: updated.email || email,
                phone: updated.phone ?? this.editableRecruiter.phone,
                gender: updated.gender || this.editableRecruiter.gender,
                user_id: updated.user_id || recruiter.user_id,
                profile_id: updated.profile_id || recruiter.profile_id,
              }
            : recruiter
        );
        this.applyFilter();
        this.updateSummaryCards();
        this.updateSelectedRecruiterState();
        this.hydrateEditableRecruiter();
        this.isEditingProfile = false;
        this.savingProfile = false;
        this.saveErrorMessage = '';
        this.saveSuccessMessage = 'Recruiter details updated.';
        window.dispatchEvent(new CustomEvent('global-data-refresh'));
      });
  }

  getInitials(name: string): string {
    const parts = (name || '').trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return 'NA';
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
  }

  formatTitle(value: string): string {
    return (value || '')
      .split(/[\s_]+/)
      .filter(Boolean)
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
      .join(' ');
  }

  get canGoPrevPerformanceYear(): boolean {
    return this.performanceYear > this.minPerformanceYear;
  }

  get canGoNextPerformanceYear(): boolean {
    return this.performanceYear < this.maxPerformanceYear;
  }

  get canGoPrevInsightsMonth(): boolean {
    const monthIndex = this.insightsYear * 12 + this.insightsMonth;
    return monthIndex > this.minInsightsMonthIndex;
  }

  get canGoNextInsightsMonth(): boolean {
    const monthIndex = this.insightsYear * 12 + this.insightsMonth;
    return monthIndex < this.maxInsightsMonthIndex;
  }

  get insightsMonthName(): string {
    return new Date(this.insightsYear, this.insightsMonth, 1).toLocaleString('default', { month: 'long' });
  }

  yearBarWidth(count: number): number {
    const max = this.yearlyPerformanceBars.reduce((acc, item) => Math.max(acc, item.count), 0) || 1;
    return Math.max(count ? 12 : 0, Math.round((count / max) * 100));
  }

  roleBarWidth(count: number): number {
    const max = this.selectedMonthTopRoles[0]?.count || 1;
    return Math.max(count ? 12 : 0, Math.round((count / max) * 100));
  }

  changePerformanceYear(step: number): void {
    const next = this.performanceYear + step;
    if (next < this.minPerformanceYear || next > this.maxPerformanceYear) return;
    this.performanceYear = next;
    this.rebuildYearlyPerformance();
  }

  changeInsightsMonth(step: number): void {
    const nextIndex = this.insightsYear * 12 + this.insightsMonth + step;
    if (nextIndex < this.minInsightsMonthIndex || nextIndex > this.maxInsightsMonthIndex) return;
    this.insightsYear = Math.floor(nextIndex / 12);
    this.insightsMonth = ((nextIndex % 12) + 12) % 12;
    this.rebuildMonthlyInsights();
  }

  private updateSummaryCards(): void {
    this.recruiterSummaryCards = [
      { label: 'Recruiters', value: this.totalRecruiters, helper: 'Total active recruiter records', icon: 'ph-identification-badge' },
      { label: 'Managed Candidates', value: this.totalManagedCandidates, helper: 'Candidate load owned by recruiters', icon: 'ph-users-three' },
      { label: 'Linked Evaluators', value: this.totalLinkedEvaluators, helper: 'Evaluators mapped across recruiters', icon: 'ph-user-list' },
      { label: 'Avg. Candidate Load', value: this.averageCandidateLoad, helper: 'Average candidates per recruiter', icon: 'ph-chart-bar-horizontal' },
    ];
  }

  private updateSelectedRecruiterState(): void {
    const recruiter = this.selectedRecruiter;
    if (!recruiter) {
      this.selectedRecruiterHighlights = [];
      this.recruiterNarrative = '';
      this.candidateLoadPercent = 0;
      this.evaluatorCoveragePercent = 0;
      this.isEditingProfile = false;
      this.saveErrorMessage = '';
      this.saveSuccessMessage = '';
      return;
    }

    this.hydrateEditableRecruiter();

    this.candidateLoadPercent = this.totalManagedCandidates
      ? Math.round(((recruiter.candidates_count || 0) / this.totalManagedCandidates) * 100)
      : 0;
    this.evaluatorCoveragePercent = this.totalLinkedEvaluators
      ? Math.round(((recruiter.interviewers_count || 0) / this.totalLinkedEvaluators) * 100)
      : 0;

    this.selectedRecruiterHighlights = [
      {
        title: 'Directory Status',
        value: 'Active recruiter record',
        tone: 'accent',
        helper: 'Available for assignment and dashboard tracking',
      },
      {
        title: 'Candidate Load Share',
        value: `${this.candidateLoadPercent}%`,
        tone: 'neutral',
        helper: 'Share of all candidates owned across recruiters',
      },
      {
        title: 'Evaluator Coverage Share',
        value: `${this.evaluatorCoveragePercent}%`,
        tone: 'neutral',
        helper: 'Share of linked evaluators across the recruiter pool',
      },
    ];

    const candidates = recruiter.candidates_count || 0;
    const evaluators = recruiter.interviewers_count || 0;
    this.recruiterNarrative = `${recruiter.name} is currently supporting ${candidates} candidate${candidates === 1 ? '' : 's'} with ${evaluators} linked evaluator${evaluators === 1 ? '' : 's'}. Use this panel to review ownership balance, contact readiness, and recruiter coverage across the hiring team.`;
  }

  private hydrateEditableRecruiter(): void {
    this.editableRecruiter = {
      name: this.selectedRecruiter?.name || '',
      email: this.selectedRecruiter?.email || '',
      phone: this.selectedRecruiter?.phone || '',
      gender: this.selectedRecruiter?.gender || 'other',
    };
  }

  private loadRecruiterAnalytics(): void {
    if (!this.selectedRecruiter) {
      this.recruiterInterviews = [];
      this.detailErrorMessage = '';
      this.detailLoading = false;
      this.rebuildAnalyticsState();
      return;
    }

    this.detailLoading = true;
    this.detailErrorMessage = '';
    const body = new URLSearchParams();
    if (this.selectedRecruiter.email) body.append('recruiter', this.selectedRecruiter.email);
    body.append('recruiter_id', String(this.selectedRecruiter.id));
    body.append('profile_type', 'recruiter');

    this.http.post<RecruiterInterviewResponse>(`${this.getApiBaseUrl()}/get-evaluator-profile/`, body.toString(), {
      headers: new HttpHeaders({ 'Content-Type': 'application/x-www-form-urlencoded' })
    })
      .pipe(
        catchError((error) => {
          console.error('Error fetching recruiter analytics', error);
          this.detailLoading = false;
          this.detailErrorMessage = 'Failed to load recruiter analytics.';
          return of({ Success: false, Interviews: [] } as RecruiterInterviewResponse);
        })
      )
      .subscribe((response) => {
        this.recruiterInterviews = response?.Success && Array.isArray(response.Interviews)
          ? response.Interviews.slice().sort((a, b) => (this.parseDate(b.date)?.getTime() || 0) - (this.parseDate(a.date)?.getTime() || 0))
          : [];
        if (!response?.Success) {
          this.detailErrorMessage = response?.Error || 'Failed to load recruiter analytics.';
        }
        this.detailLoading = false;
        this.rebuildAnalyticsState();
      });
  }

  private rebuildAnalyticsState(): void {
    const now = new Date();
    const validDates = this.recruiterInterviews
      .map((item) => this.parseDate(item.date))
      .filter((date): date is Date => !!date);

    const years = validDates.map((date) => date.getFullYear());
    this.minPerformanceYear = years.length ? Math.min(...years) : now.getFullYear();
    this.maxPerformanceYear = years.length ? Math.max(...years) : now.getFullYear();
    if (this.performanceYear < this.minPerformanceYear || this.performanceYear > this.maxPerformanceYear) {
      this.performanceYear = this.maxPerformanceYear;
    }

    if (validDates.length) {
      const monthIndexes = validDates.map((date) => date.getFullYear() * 12 + date.getMonth());
      this.minInsightsMonthIndex = Math.min(...monthIndexes);
      this.maxInsightsMonthIndex = Math.max(...monthIndexes);
      const currentIndex = now.getFullYear() * 12 + now.getMonth();
      const clampedIndex = Math.min(Math.max(currentIndex, this.minInsightsMonthIndex), this.maxInsightsMonthIndex);
      this.insightsYear = Math.floor(clampedIndex / 12);
      this.insightsMonth = ((clampedIndex % 12) + 12) % 12;
    } else {
      this.minInsightsMonthIndex = now.getFullYear() * 12 + now.getMonth();
      this.maxInsightsMonthIndex = this.minInsightsMonthIndex;
      this.insightsYear = now.getFullYear();
      this.insightsMonth = now.getMonth();
    }

    this.rebuildYearlyPerformance();
    this.rebuildMonthlyInsights();
  }

  private rebuildYearlyPerformance(): void {
    this.yearlyPerformanceBars = this.monthLabels().map((label, index) => ({
      label,
      count: this.recruiterInterviews.filter((item) => {
        const date = this.parseDate(item.date);
        return !!date && date.getFullYear() === this.performanceYear && date.getMonth() === index;
      }).length,
    }));
  }

  private rebuildMonthlyInsights(): void {
    const monthItems = this.recruiterInterviews.filter((item) => {
      const date = this.parseDate(item.date);
      return !!date && date.getFullYear() === this.insightsYear && date.getMonth() === this.insightsMonth;
    });

    this.selectedMonthInterviews = monthItems.length;
    const activeDays = new Map<string, number>();
    const roleCounts = new Map<string, number>();
    let scheduledCount = 0;

    monthItems.forEach((item) => {
      const date = this.parseDate(item.date);
      if (!date) return;
      const key = date.toISOString().slice(0, 10);
      activeDays.set(key, (activeDays.get(key) || 0) + 1);
      const role = (item.role || 'Unassigned').toString().trim() || 'Unassigned';
      roleCounts.set(role, (roleCounts.get(role) || 0) + 1);
      if (this.normalizeStatus(item.status) === 'scheduled') scheduledCount += 1;
    });

    this.selectedMonthActiveDays = activeDays.size;
    this.selectedMonthScheduledCount = scheduledCount;
    this.selectedMonthAvgPerActiveDay = activeDays.size ? Math.round((monthItems.length / activeDays.size) * 10) / 10 : 0;

    const busiestEntry = Array.from(activeDays.entries()).sort((a, b) => b[1] - a[1])[0];
    this.selectedMonthBusiestCount = busiestEntry?.[1] || 0;
    this.selectedMonthBusiestDayLabel = busiestEntry
      ? new Date(busiestEntry[0]).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
      : '-';

    this.selectedMonthTopRoles = Array.from(roleCounts.entries())
      .map(([role, count]) => ({ role, count }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 5);
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

  private parseDate(value: string): Date | null {
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  }

  private monthLabels(): string[] {
    return ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  }
}
