import { Component, OnInit } from '@angular/core';
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
export class Candidates implements OnInit {
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
  pageSize = 10;
  currentPage = 1;

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
    this.loadCandidatesTabData();
  }

  get totalPages(): number {
    return Math.max(1, Math.ceil(this.filteredCandidates.length / this.pageSize));
  }

  get filteredCandidates(): CandidateItem[] {
    const term = this.searchTerm.trim().toLowerCase();
    const byStatus = this.candidates.filter((item) => {
      if (this.statusFilter === 'all') return true;
      const normalized = this.normalizeStatus(item.status);
      if (this.statusFilter === 'hired') return normalized === 'hired' || normalized === 'completed';
      return normalized === this.statusFilter;
    });

    if (!term) return byStatus;

    return byStatus.filter((item) =>
      [item.name, item.email, item.recruiter, item.role, item.status]
        .map((v) => (v || '').toString().toLowerCase())
        .some((v) => v.includes(term))
    );
  }

  get pagedCandidates(): CandidateItem[] {
    const start = (this.currentPage - 1) * this.pageSize;
    return this.filteredCandidates.slice(start, start + this.pageSize);
  }

  setStatusFilter(status: string): void {
    this.statusFilter = status;
    this.currentPage = 1;
  }

  clearSearch(): void {
    this.searchTerm = '';
    this.currentPage = 1;
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
      width: '550px',
      data: { role_id: roleId }
    });
  }

  getStatusCount(status: string): number {
    if (status === 'all') return this.summary.total;
    if (status === 'hired') return this.summary.hired;
    const key = status.replace(/\s+/g, '_') as keyof typeof this.summary;
    return Number(this.summary[key] || 0);
  }

  roleBarWidth(item: RoleBreakdownItem): number {
    const max = this.roleBreakdown[0]?.count || 1;
    return Math.max(8, Math.round((item.count / max) * 100));
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
}
