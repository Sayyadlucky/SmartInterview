import { Component, OnDestroy, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { catchError, of } from 'rxjs';
import { MatDialog } from '@angular/material/dialog';
import { MatDialogModule } from '@angular/material/dialog';
import { CandidateProfile } from '../app-modal/candidate-profile/candidate-profile';
import { RoleDetail } from '../app-modal/role-detail/role-detail';

interface CandidateItem {
  id: number;
  name: string;
  email: string;
  status: string;
  recruiter: string;
  role: string;
  role_id?: number | null;
  score?: number | null;
  date: string;
}

interface CandidateViewModel extends CandidateItem {
  normalizedStatus: string;
  statusLabel: string;
  roleDisplay: string;
  urgencyLevel: 'high' | 'medium' | 'low';
  urgencyLabel: string;
  urgencyClass: string;
  ageLabel: string;
  dateValue: number;
  isOverdue: boolean;
  searchBlob: string;
}

interface UpcomingItem {
  id: number;
  candidate: string;
  role: string;
  recruiter: string;
  date: string;
  status: string;
}

interface RoleBreakdownItem {
  role: string;
  count: number;
  hired: number;
  scheduled: number;
}

interface RecruiterBreakdownItem {
  name: string;
  count: number;
}

interface CandidatesTabResponse {
  Success: boolean;
  Error?: string | null;
  Data?: {
    summary?: {
      total?: number;
      scheduled?: number;
      shortlisted?: number;
      hired?: number;
      rejected?: number;
      assessment_pending?: number;
      assessment_completed?: number;
      auto_screening_scheduled?: number;
      cancelled?: number;
    };
    candidates?: CandidateItem[];
    role_breakdown?: RoleBreakdownItem[];
    recruiter_breakdown?: RecruiterBreakdownItem[];
    upcoming?: UpcomingItem[];
  };
}

@Component({
  selector: 'app-candidates',
  standalone: true,
  imports: [CommonModule, FormsModule, MatDialogModule],
  templateUrl: './candidates.html',
  styleUrl: './candidates.scss'
})
export class Candidates implements OnInit, OnDestroy {
  loading = false;
  errorMessage = '';

  candidates: CandidateViewModel[] = [];
  roleBreakdown: RoleBreakdownItem[] = [];
  recruiterBreakdown: RecruiterBreakdownItem[] = [];
  upcoming: UpcomingItem[] = [];

  summary = {
    total: 0,
    scheduled: 0,
    shortlisted: 0,
    hired: 0,
    rejected: 0,
    assessment_pending: 0,
    assessment_completed: 0,
    auto_screening_scheduled: 0,
    cancelled: 0,
  };

  searchTerm = '';
  statusFilter = 'all';
  recruiterFilter = 'all';
  roleFilter = 'all';
  sortBy = 'recent';
  attentionOnly = false;
  pageSize = 10;
  currentPage = 1;
  filteredCandidatesCache: CandidateViewModel[] = [];
  recruiterOptionsCache: string[] = [];
  roleOptionsCache: Array<{ id: string; name: string }> = [];
  overdueCountValue = 0;
  thisWeekCandidatesValue = 0;
  attentionCandidatesCache: CandidateViewModel[] = [];
  private readonly statusUpdateListener = () => this.loadCandidatesTabData();
  readonly pageSizeOptions = [10, 25, 50];

  readonly statusFilters = [
    { key: 'all', label: 'All' },
    { key: 'scheduled', label: 'Scheduled' },
    { key: 'shortlisted', label: 'Shortlisted' },
    { key: 'offer made', label: 'Offer Made' },
    { key: 'offer accepted', label: 'Offer Accepted' },
    { key: 'offer declined', label: 'Offer Declined' },
    { key: 'hired', label: 'Hired' },
    { key: 'rejected', label: 'Rejected' },
    { key: 'assessment pending', label: 'Assessment Pending' },
    { key: 'auto screening scheduled', label: 'Auto Screening' },
    { key: 'cancelled', label: 'Cancelled' },
  ];

  constructor(private http: HttpClient, private dialog: MatDialog) {}

  ngOnInit(): void {
    window.addEventListener('candidate-status-updated', this.statusUpdateListener as EventListener);
    window.addEventListener('global-data-refresh', this.statusUpdateListener as EventListener);
    this.loadCandidatesTabData();
  }

  ngOnDestroy(): void {
    window.removeEventListener('candidate-status-updated', this.statusUpdateListener as EventListener);
    window.removeEventListener('global-data-refresh', this.statusUpdateListener as EventListener);
  }

  get totalPages(): number {
    return Math.max(1, Math.ceil(this.filteredCandidatesCache.length / this.pageSize));
  }

  get filteredCandidates(): CandidateViewModel[] {
    return this.filteredCandidatesCache;
  }

  get pagedCandidates(): CandidateViewModel[] {
    const start = (this.currentPage - 1) * this.pageSize;
    return this.filteredCandidates.slice(start, start + this.pageSize);
  }

  get pageStart(): number {
    if (!this.filteredCandidates.length) return 0;
    return (this.currentPage - 1) * this.pageSize + 1;
  }

  get pageEnd(): number {
    return Math.min(this.currentPage * this.pageSize, this.filteredCandidates.length);
  }

  get activeFilterCount(): number {
    let count = 0;
    if (this.statusFilter !== 'all') count += 1;
    if (this.recruiterFilter !== 'all') count += 1;
    if (this.roleFilter !== 'all') count += 1;
    if (this.attentionOnly) count += 1;
    if (this.searchTerm.trim()) count += 1;
    return count;
  }

  setStatusFilter(status: string): void {
    this.statusFilter = status;
    this.currentPage = 1;
    this.applyCandidateFilters();
  }

  clearAllFilters(): void {
    this.searchTerm = '';
    this.statusFilter = 'all';
    this.recruiterFilter = 'all';
    this.roleFilter = 'all';
    this.sortBy = 'recent';
    this.attentionOnly = false;
    this.currentPage = 1;
    this.applyCandidateFilters();
  }

  toggleAttentionOnly(): void {
    this.attentionOnly = !this.attentionOnly;
    this.currentPage = 1;
    this.applyCandidateFilters();
  }

  onSearchChange(): void {
    this.currentPage = 1;
    this.applyCandidateFilters();
  }

  onFiltersChanged(): void {
    this.currentPage = 1;
    this.applyCandidateFilters();
  }

  setPageSize(size: string | number): void {
    const nextSize = Number(size);
    if (!Number.isFinite(nextSize) || nextSize <= 0) return;
    this.pageSize = nextSize;
    this.currentPage = 1;
    this.applyCandidateFilters();
  }

  clearSearch(): void {
    this.searchTerm = '';
    this.currentPage = 1;
    this.applyCandidateFilters();
  }

  prevPage(): void {
    if (this.currentPage > 1) this.currentPage -= 1;
  }

  nextPage(): void {
    if (this.currentPage < this.totalPages) this.currentPage += 1;
  }

  trackCandidate(_index: number, item: CandidateViewModel): number {
    return item.id;
  }

  openCandidateProfile(candidate: CandidateViewModel): void {
    const dialogRef = this.dialog.open(CandidateProfile, {
      width: '95vw',
      maxWidth: '980px',
      maxHeight: '92vh',
      panelClass: 'candidate-profile-dialog',
      autoFocus: false,
      data: { candidate }
    });

    dialogRef.afterClosed().subscribe((result) => {
      if (!result) return;

      if (result.action === 'updated' && result.candidate) {
        const updated = this.enrichCandidate(result.candidate as CandidateItem);
        const index = this.candidates.findIndex((c) => c.id === updated.id);
        if (index !== -1) {
          this.candidates[index] = updated;
          this.rebuildSummaryFromCandidates();
          this.rebuildCandidateCaches();
          this.applyCandidateFilters();
        }
      }

      if (result.action === 'openRole' && result.candidate?.role_id) {
        this.openRoleDetail(result.candidate.role_id);
      }
    });
  }

  openRoleDetail(roleId?: number | null): void {
    if (!roleId) return;
    this.dialog.open(RoleDetail, {
      width: 'min(1120px, 96vw)',
      maxWidth: '96vw',
      maxHeight: '92vh',
      panelClass: 'role-detail-dialog',
      data: { role_id: roleId }
    });
  }

  getStatusCount(status: string): number {
    if (status === 'all') return this.summary.total;
    if (status === 'hired') return this.summary.hired;
    const key = status.replace(/\s+/g, '_') as keyof typeof this.summary;
    return Number(this.summary[key] || 0);
  }

  get recruiterOptions(): string[] {
    return this.recruiterOptionsCache;
  }

  get roleOptions(): Array<{ id: string; name: string }> {
    return this.roleOptionsCache;
  }

  get overdueCount(): number {
    return this.overdueCountValue;
  }

  get thisWeekCandidates(): number {
    return this.thisWeekCandidatesValue;
  }

  get shortlistedCount(): number {
    return Number(this.summary.shortlisted || 0);
  }

  get activePipelineCount(): number {
    return Number(this.summary.scheduled || 0) + Number(this.summary.shortlisted || 0);
  }

  get pipelineCoverage(): number {
    if (!this.summary.total) return 0;
    return Math.round((this.activePipelineCount / this.summary.total) * 100);
  }

  get hireRate(): number {
    if (!this.summary.total) return 0;
    return Math.round((Number(this.summary.hired || 0) / this.summary.total) * 100);
  }

  get shortlistRate(): number {
    if (!this.summary.total) return 0;
    return Math.round((Number(this.summary.shortlisted || 0) / this.summary.total) * 100);
  }

  get attentionCandidates(): CandidateViewModel[] {
    return this.attentionCandidatesCache;
  }

  roleBarWidth(item: RoleBreakdownItem): number {
    const max = this.roleBreakdown[0]?.count || 1;
    return Math.max(8, Math.round((item.count / max) * 100));
  }

  formatRoleWithId(role: string, roleId?: number | null): string {
    const roleName = (role || '').toString().trim();
    const id = (roleId ?? '').toString().trim();
    if (!roleName) return id;
    return id ? `${roleName} - ${id}` : roleName;
  }

  private getApiBaseUrl(): string {
    let portNumber = '';
    if (window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost') {
      portNumber = '8080';
    }
    return `${window.location.protocol}//${window.location.hostname}:${portNumber}`;
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

  private getValidDate(value: string): Date | null {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  private getAgeInDays(value: string): number | null {
    const d = this.getValidDate(value);
    if (!d) return null;
    const diff = Date.now() - d.getTime();
    return Math.max(0, Math.floor(diff / (24 * 60 * 60 * 1000)));
  }

  private getStatusLabel(status: string): string {
    const normalized = this.normalizeStatus(status);
    if (!normalized) return 'Unknown';
    return normalized.replace(/\b\w/g, (match) => match.toUpperCase());
  }

  private isClosedStatus(status: string): boolean {
    const normalized = this.normalizeStatus(status);
    return ['hired', 'completed', 'offer declined', 'rejected', 'cancelled'].includes(normalized);
  }

  private getUrgencyLevel(status: string, age: number | null): 'high' | 'medium' | 'low' {
    if (this.isClosedStatus(status)) return 'low';
    const ageValue = age ?? 0;
    if ((status === 'shortlisted' && ageValue >= 3) || (status === 'scheduled' && ageValue >= 3) || ageValue >= 7) return 'high';
    if (ageValue >= 3) return 'medium';
    return 'low';
  }

  private getAgeLabel(days: number | null): string {
    if (days === null) return 'Unknown';
    if (days === 0) return 'Today';
    if (days === 1) return '1 day';
    return `${days} days`;
  }

  private enrichCandidate(item: CandidateItem): CandidateViewModel {
    const normalizedStatus = this.normalizeStatus(item.status);
    const age = this.getAgeInDays(item.date);
    const urgencyLevel = this.getUrgencyLevel(normalizedStatus, age);
    const dateValue = this.getValidDate(item.date)?.getTime() || 0;
    const roleDisplay = this.formatRoleWithId(item.role, item.role_id);

    return {
      ...item,
      status: normalizedStatus,
      normalizedStatus,
      statusLabel: this.getStatusLabel(normalizedStatus),
      roleDisplay,
      urgencyLevel,
      urgencyLabel: this.getStatusLabel(urgencyLevel),
      urgencyClass: urgencyLevel,
      ageLabel: this.getAgeLabel(age),
      dateValue,
      isOverdue: !this.isClosedStatus(normalizedStatus) && age !== null && age >= 5,
      searchBlob: [
        item.name,
        item.email,
        item.recruiter,
        item.role,
        item.role_id,
        normalizedStatus,
      ]
        .map((value) => (value || '').toString().toLowerCase())
        .join(' '),
    };
  }

  private sortByUrgency(a: CandidateViewModel, b: CandidateViewModel): number {
    const rank = { high: 3, medium: 2, low: 1 };
    const ra = rank[a.urgencyLevel];
    const rb = rank[b.urgencyLevel];
    if (ra !== rb) return rb - ra;
    return a.dateValue - b.dateValue;
  }

  private sortCandidates(a: CandidateViewModel, b: CandidateViewModel): number {
    if (this.sortBy === 'oldest') return a.dateValue - b.dateValue;
    if (this.sortBy === 'name') return a.name.localeCompare(b.name);
    if (this.sortBy === 'urgency') return this.sortByUrgency(a, b);
    return b.dateValue - a.dateValue;
  }

  private loadCandidatesTabData(): void {
    this.loading = true;
    this.errorMessage = '';
    const apiBaseUrl = this.getApiBaseUrl();

    this.http.get<CandidatesTabResponse>(`${apiBaseUrl}/candidates-tab-data/`)
      .pipe(
        catchError((error) => {
          console.error('Error fetching candidates tab data', error);
          this.loading = false;
          this.errorMessage = 'Unable to load candidates data.';
          return of({ Success: false, Data: {} } as CandidatesTabResponse);
        })
      )
      .subscribe((response) => {
        if (!response?.Success) {
          this.errorMessage = response?.Error || 'Unable to load candidates data.';
          this.loading = false;
          return;
        }

        const data = response.Data || {};
        this.summary = {
          ...this.summary,
          ...(data.summary || {})
        };
        this.candidates = (data.candidates || []).map((item) => this.enrichCandidate(item));
        this.roleBreakdown = data.role_breakdown || [];
        this.recruiterBreakdown = data.recruiter_breakdown || [];
        this.upcoming = data.upcoming || [];
        this.rebuildCandidateCaches();
        this.applyCandidateFilters();

        this.currentPage = 1;
        this.loading = false;
      });
  }

  private rebuildSummaryFromCandidates(): void {
    const counts = {
      total: this.candidates.length,
      scheduled: 0,
      shortlisted: 0,
      hired: 0,
      rejected: 0,
      assessment_pending: 0,
      assessment_completed: 0,
      auto_screening_scheduled: 0,
      cancelled: 0,
    };

    this.candidates.forEach((item) => {
      const s = item.normalizedStatus;
      if (s === 'hired' || s === 'completed') counts.hired += 1;
      else if (s === 'scheduled') counts.scheduled += 1;
      else if (s === 'shortlisted' || s === 'offer made' || s === 'offer accepted') counts.shortlisted += 1;
      else if (s === 'rejected') counts.rejected += 1;
      else if (s === 'assessment pending') counts.assessment_pending += 1;
      else if (s === 'assessment completed') counts.assessment_completed += 1;
      else if (s === 'auto screening scheduled') counts.auto_screening_scheduled += 1;
      else if (s === 'cancelled') counts.cancelled += 1;
    });

    this.summary = counts;
  }

  private rebuildCandidateCaches(): void {
    this.recruiterOptionsCache = Array.from(
      new Set(this.candidates.map((item) => item.recruiter).filter(Boolean))
    ).sort((a, b) => a.localeCompare(b));

    const roleMap = new Map<string, string>();
    this.candidates.forEach((item) => {
      if (!item.role_id) return;
      roleMap.set(String(item.role_id), item.role);
    });
    this.roleOptionsCache = Array.from(roleMap.entries())
      .map(([id, name]) => ({ id, name }))
      .sort((a, b) => a.name.localeCompare(b.name));

    const now = Date.now();
    this.thisWeekCandidatesValue = this.candidates.filter((item) => {
      return !!item.dateValue && now - item.dateValue <= 7 * 24 * 60 * 60 * 1000;
    }).length;
    this.overdueCountValue = this.candidates.filter((item) => item.isOverdue).length;
    this.attentionCandidatesCache = this.candidates
      .filter((item) => item.urgencyLevel !== 'low')
      .sort((a, b) => this.sortByUrgency(a, b))
      .slice(0, 6);
  }

  private applyCandidateFilters(): void {
    const term = this.searchTerm.trim().toLowerCase();
    const byFilters = this.candidates.filter((item) => {
      if (this.statusFilter === 'all') return true;
      if (this.statusFilter === 'hired') return item.normalizedStatus === 'hired' || item.normalizedStatus === 'completed';
      if (this.statusFilter === 'shortlisted') {
        return item.normalizedStatus === 'shortlisted' || item.normalizedStatus === 'offer made' || item.normalizedStatus === 'offer accepted';
      }
      return item.normalizedStatus === this.statusFilter;
    }).filter((item) => {
      if (this.recruiterFilter !== 'all' && item.recruiter !== this.recruiterFilter) return false;
      if (this.roleFilter !== 'all') {
        const roleId = (item.role_id ?? '').toString();
        if (roleId !== this.roleFilter) return false;
      }
      if (this.attentionOnly && item.urgencyLevel === 'low') return false;
      return true;
    });

    const filtered = !term ? byFilters : byFilters.filter((item) => item.searchBlob.includes(term));

    this.filteredCandidatesCache = filtered.sort((a, b) => this.sortCandidates(a, b));
    this.currentPage = Math.min(this.currentPage, this.totalPages);
  }
}
