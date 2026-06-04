import { Component, Input, OnDestroy, OnInit } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { catchError } from 'rxjs/operators';
import { of } from 'rxjs';
import { CommonModule } from '@angular/common';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { RecuiterProfile } from '../recuiter-profile/recuiter-profile';
import { AddUser } from '../app-modal/add-user/add-user';
import { FormsModule } from '@angular/forms';

interface Recruiter {
  id: number;
  user_id?: number;
  profile_id?: number;
  name: string;
  email: string;
  role: string;
  phone?: string;
  gender?: string;
  interviews_count?: number;
  hr_name?: string;
  interviewers_count?: number;
  candidates_count?: number;
  recruiter_id?: number;
  recruiter_name?: string;
}

interface RecruiterResponse {
  Success: boolean;
  Error?: string | null;
  RecruiterData?: Recruiter[];
  Data?: { RecruiterData?: Recruiter[] };
}

@Component({
  selector: 'app-evaluators',
  imports: [CommonModule, RecuiterProfile, FormsModule, MatDialogModule],
  templateUrl: './evaluators.html',
  styleUrls: ['./evaluators.scss']
})
export class Evaluators implements OnInit, OnDestroy {
  @Input() mode: 'evaluator' | 'recruiter' = 'evaluator';
  loading = false;
  errorMessage = '';
  recruitersList: Recruiter[] = [];
  allRecruiters: Recruiter[] = [];
  selectedEvaluator: Recruiter | null = null;
  searchTerm = '';
  private searchTimeoutId: ReturnType<typeof setTimeout> | null = null;
  private readonly statusUpdateListener = () => this.loadEvaluators();

  constructor(private http: HttpClient, private dialog: MatDialog) {}

  ngOnInit(): void {
    window.addEventListener('candidate-status-updated', this.statusUpdateListener as EventListener);
    window.addEventListener('global-data-refresh', this.statusUpdateListener as EventListener);
    this.loadEvaluators();
  }

  ngOnDestroy(): void {
    window.removeEventListener('candidate-status-updated', this.statusUpdateListener as EventListener);
    window.removeEventListener('global-data-refresh', this.statusUpdateListener as EventListener);
    if (this.searchTimeoutId) {
      clearTimeout(this.searchTimeoutId);
    }
  }

  get hasSelectedEvaluator(): boolean {
    return !!this.selectedEvaluator;
  }

  get totalEvaluators(): number {
    return this.allRecruiters.length;
  }

  get panelTitle(): string {
    return this.mode === 'recruiter' ? 'Recruiters' : 'Evaluators';
  }

  get panelSubtitle(): string {
    return this.mode === 'recruiter'
      ? 'Recruiter records and their interview activity'
      : 'Interviewers linked under recruiter accounts';
  }

  get addButtonLabel(): string {
    return this.mode === 'recruiter' ? 'Add Recruiter' : 'Add Evaluator';
  }

  get emptyStateTitle(): string {
    return this.mode === 'recruiter' ? 'No recruiters found' : 'No evaluators found';
  }

  get emptyStateText(): string {
    return this.mode === 'recruiter'
      ? 'Try a different search keyword or add a recruiter.'
      : 'Try a different search keyword or add an evaluator.';
  }

  getSecondaryMeta(recruiter: Recruiter): string {
    if (this.mode === 'recruiter') {
      return `${recruiter.role} • ${recruiter.interviewers_count || 0} evaluators • ${recruiter.candidates_count || 0} candidates`;
    }
    return `${recruiter.role} • ${recruiter.interviews_count || 0} interviews • ${recruiter.email}`;
  }

  get displayedEvaluatorsCount(): number {
    return this.recruitersList.length;
  }

  get totalManagedCandidates(): number {
    return this.allRecruiters.reduce((sum, recruiter) => sum + (recruiter.candidates_count || 0), 0);
  }

  get totalLinkedEvaluators(): number {
    return this.allRecruiters.reduce((sum, recruiter) => sum + (recruiter.interviewers_count || 0), 0);
  }

  get averageCandidatesPerRecruiter(): number {
    if (!this.totalEvaluators) return 0;
    return Math.round(this.totalManagedCandidates / this.totalEvaluators);
  }

  get recruiterSummaryCards(): Array<{ label: string; value: number; helper: string; icon: string }> {
    return [
      {
        label: 'Recruiters',
        value: this.totalEvaluators,
        helper: 'Total recruiter records available',
        icon: 'ph-identification-badge',
      },
      {
        label: 'Managed Candidates',
        value: this.totalManagedCandidates,
        helper: 'Candidate workload owned by recruiters',
        icon: 'ph-users-three',
      },
      {
        label: 'Linked Evaluators',
        value: this.totalLinkedEvaluators,
        helper: 'Interviewers mapped to recruiters',
        icon: 'ph-user-list',
      },
      {
        label: 'Avg. Candidate Load',
        value: this.averageCandidatesPerRecruiter,
        helper: 'Average candidates per recruiter',
        icon: 'ph-chart-bar-horizontal',
      },
    ];
  }

  private getApiBaseUrl(): string {
    let portNumber = '';
    if (window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost') {
      portNumber = '8080';
    }
    return `${window.location.protocol}//${window.location.hostname}:${portNumber}`;
  }

  private parseRecruiterData(response: RecruiterResponse | any): Recruiter[] {
    return response?.RecruiterData || response?.Data?.RecruiterData || [];
  }

  private syncSelectedEvaluatorReference(): void {
    if (!this.selectedEvaluator) return;
    this.selectedEvaluator = this.allRecruiters.find((r) => r.id === this.selectedEvaluator?.id) || null;
  }

  loadEvaluators(): void {
    this.loading = true;
    this.errorMessage = '';
    const apiBaseUrl = this.getApiBaseUrl();

    const endpoint = this.mode === 'recruiter' ? '/get-hr-list/' : '/get-evaluator/';
    this.http.get<RecruiterResponse>(`${apiBaseUrl}${endpoint}`)
      .pipe(
        catchError((error) => {
          console.error(`Error fetching ${this.mode}s`, error);
          this.loading = false;
          this.errorMessage = this.mode === 'recruiter'
            ? 'Failed to load recruiters. Please try again.'
            : 'Failed to load evaluators. Please try again.';
          return of({ Success: false, RecruiterData: [] } as RecruiterResponse);
        })
      )
      .subscribe((response) => {
        const list = this.parseRecruiterData(response);
        this.allRecruiters = list;
        this.applyLocalFilter();
        this.syncSelectedEvaluatorReference();
        this.loading = false;
      });
  }

  openProfile(recruiter: Recruiter): void {
    this.selectedEvaluator = recruiter;
  }

  addEvaluator(): void {
    const dialogRef = this.dialog.open(AddUser, {
      width: '550px',
      data: { type: this.mode === 'recruiter' ? 'Recruiter' : 'Interviewer' }
    });

    dialogRef.afterClosed().subscribe((result) => {
      if (result) {
        this.loadEvaluators();
      }
    });
  }

  clearSearch(): void {
    this.searchTerm = '';
    this.applyLocalFilter();
  }

  filterEvaluators(): void {
    this.errorMessage = '';
    this.applyLocalFilter();

    const term = this.searchTerm.trim();
    if (!term.length) {
      if (this.searchTimeoutId) {
        clearTimeout(this.searchTimeoutId);
      }
      return;
    }

    if (this.searchTimeoutId) {
      clearTimeout(this.searchTimeoutId);
    }
    this.searchTimeoutId = setTimeout(() => this.searchEvaluatorsRemote(term), 300);
  }

  private applyLocalFilter(): void {
    const term = this.searchTerm.trim().toLowerCase();
    if (!term) {
      this.recruitersList = this.allRecruiters;
    } else {
      this.recruitersList = this.allRecruiters.filter((r) =>
        [r.name, r.email, r.role, r.phone, r.hr_name]
          .map((v) => (v || '').toString().toLowerCase())
          .some((v) => v.includes(term))
      );
    }

    if (this.selectedEvaluator && !this.recruitersList.some((item) => item.id === this.selectedEvaluator?.id)) {
      this.selectedEvaluator = null;
    }
  }

  private searchEvaluatorsRemote(term: string): void {
    if (this.mode === 'recruiter') {
      this.loading = false;
      return;
    }

    const apiBaseUrl = this.getApiBaseUrl();
    const body = new URLSearchParams();
    body.set('name', term);

    this.loading = true;
    this.http
      .post<RecruiterResponse>(`${apiBaseUrl}/evaluator-search/`, body.toString(), {
        headers: new HttpHeaders({ 'Content-Type': 'application/x-www-form-urlencoded' })
      })
      .pipe(
        catchError((error) => {
          console.error('Error searching evaluators', error);
          this.loading = false;
          this.errorMessage = 'Search failed. Showing local results only.';
          return of({ Success: false, RecruiterData: [] } as RecruiterResponse);
        })
      )
      .subscribe((response) => {
        const remoteList = this.parseRecruiterData(response);
        if (response?.Success) {
          this.recruitersList = remoteList;
          if (this.selectedEvaluator && !this.recruitersList.some((item) => item.id === this.selectedEvaluator?.id)) {
            this.selectedEvaluator = null;
          }
        } else if (!this.errorMessage) {
          this.errorMessage = response?.Error || 'Search failed.';
        }
        this.loading = false;
      });
  }

  getInitials(name: string): string {
    const parts = (name || '').trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return 'NA';
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
  }
}
