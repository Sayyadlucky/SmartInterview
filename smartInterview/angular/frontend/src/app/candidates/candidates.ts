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

  candidates: CandidateItem[] = [];
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
  filteredCandidatesCache: CandidateItem[] = [];
  recruiterOptionsCache: string[] = [];
  roleOptionsCache: Array<{ id: string; name: string }> = [];
  overdueCountValue = 0;
  thisWeekCandidatesValue = 0;
  attentionCandidatesCache: CandidateItem[] = [];
  private readonly statusUpdateListener = () => this.loadCandidatesTabData();

  readonly statusFilters = [
    { key: 'all', label: 'All' },
    { key: 'scheduled', label: 'Scheduled' },
    { key: 'shortlisted', label: 'Shortlisted' },
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

  get filteredCandidates(): CandidateItem[] {
    return this.filteredCandidatesCache;
  }

  get pagedCandidates(): CandidateItem[] {
    const start = (this.currentPage - 1) * this.pageSize;
    return this.filteredCandidates.slice(start, start + this.pageSize);
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

  trackCandidate(_index: number, item: CandidateItem): number {
    return item.id;
  }

  openCandidateProfile(candidate: CandidateItem): void {
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
        const updated = result.candidate as CandidateItem;
        const index = this.candidates.findIndex((c) => c.id === updated.id);
        if (index !== -1) {
          this.candidates[index] = { ...this.candidates[index], ...updated, status: this.normalizeStatus(updated.status) };
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
      width: '95vw',
      maxWidth: '920px',
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

  get pipelineCoverage(): number {
    if (!this.summary.total) return 0;
    return Math.round(((this.summary.scheduled + this.summary.shortlisted) / this.summary.total) * 100);
  }

  get attentionCandidates(): CandidateItem[] {
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

  urgencyLabel(item: CandidateItem): string {
    const level = this.getUrgencyLevel(item);
    if (level === 'high') return 'High';
    if (level === 'medium') return 'Medium';
    return 'Low';
  }

  urgencyClass(item: CandidateItem): string {
    const level = this.getUrgencyLevel(item);
    if (level === 'high') return 'high';
    if (level === 'medium') return 'medium';
    return 'low';
  }

  ageLabel(item: CandidateItem): string {
    const days = this.getAgeInDays(item.date);
    if (days === null) return 'Unknown';
    if (days === 0) return 'Today';
    if (days === 1) return '1 day';
    return `${days} days`;
  }

  private getApiBaseUrl(): string {
    let portNumber = '';
    if (window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost') {
      portNumber = '8000';
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

  private isClosedStatus(status: string): boolean {
    const normalized = this.normalizeStatus(status);
    return ['hired', 'completed', 'rejected', 'cancelled'].includes(normalized);
  }

  private isOverdue(item: CandidateItem): boolean {
    if (this.isClosedStatus(item.status)) return false;
    const age = this.getAgeInDays(item.date);
    return age !== null && age >= 5;
  }

  private getUrgencyLevel(item: CandidateItem): 'high' | 'medium' | 'low' {
    const status = this.normalizeStatus(item.status);
    if (this.isClosedStatus(status)) return 'low';
    const age = this.getAgeInDays(item.date) ?? 0;
    if ((status === 'shortlisted' && age >= 3) || (status === 'scheduled' && age >= 3) || age >= 7) return 'high';
    if (age >= 3) return 'medium';
    return 'low';
  }

  private sortByUrgency(a: CandidateItem, b: CandidateItem): number {
    const rank = { high: 3, medium: 2, low: 1 };
    const ra = rank[this.getUrgencyLevel(a)];
    const rb = rank[this.getUrgencyLevel(b)];
    if (ra !== rb) return rb - ra;
    const da = this.getValidDate(a.date)?.getTime() || 0;
    const db = this.getValidDate(b.date)?.getTime() || 0;
    return da - db;
  }

  private sortCandidates(a: CandidateItem, b: CandidateItem): number {
    const dateA = this.getValidDate(a.date)?.getTime() || 0;
    const dateB = this.getValidDate(b.date)?.getTime() || 0;
    if (this.sortBy === 'oldest') return dateA - dateB;
    if (this.sortBy === 'name') return a.name.localeCompare(b.name);
    if (this.sortBy === 'urgency') return this.sortByUrgency(a, b);
    return dateB - dateA;
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
        this.candidates = (data.candidates || []).map((item) => ({
          ...item,
          status: this.normalizeStatus(item.status)
        }));
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
      const s = this.normalizeStatus(item.status);
      if (s === 'hired' || s === 'completed') counts.hired += 1;
      else if (s === 'scheduled') counts.scheduled += 1;
      else if (s === 'shortlisted') counts.shortlisted += 1;
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
      const t = this.getValidDate(item.date)?.getTime();
      return !!t && now - t <= 7 * 24 * 60 * 60 * 1000;
    }).length;
    this.overdueCountValue = this.candidates.filter((item) => this.isOverdue(item)).length;
    this.attentionCandidatesCache = this.candidates
      .filter((item) => this.getUrgencyLevel(item) !== 'low')
      .sort((a, b) => this.sortByUrgency(a, b))
      .slice(0, 6);
  }

  private applyCandidateFilters(): void {
    const term = this.searchTerm.trim().toLowerCase();
    const byFilters = this.candidates.filter((item) => {
      if (this.statusFilter === 'all') return true;
      const normalized = this.normalizeStatus(item.status);
      if (this.statusFilter === 'hired') return normalized === 'hired' || normalized === 'completed';
      return normalized === this.statusFilter;
    }).filter((item) => {
      if (this.recruiterFilter !== 'all' && item.recruiter !== this.recruiterFilter) return false;
      if (this.roleFilter !== 'all') {
        const roleId = (item.role_id ?? '').toString();
        if (roleId !== this.roleFilter) return false;
      }
      if (this.attentionOnly && this.getUrgencyLevel(item) === 'low') return false;
      return true;
    });

    const filtered = !term ? byFilters : byFilters.filter((item) =>
      [item.name, item.email, item.recruiter, item.role, item.status]
        .map((v) => (v || '').toString().toLowerCase())
        .some((v) => v.includes(term))
    );

    this.filteredCandidatesCache = filtered.sort((a, b) => this.sortCandidates(a, b));
  }
}
