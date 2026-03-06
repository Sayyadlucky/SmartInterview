import { Component, OnDestroy, OnInit } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { catchError } from 'rxjs/operators';
import { of } from 'rxjs';
import { CommonModule } from '@angular/common';
import { MatDialog } from '@angular/material/dialog';
import { RecuiterProfile } from '../recuiter-profile/recuiter-profile';
import { AddUser } from '../app-modal/add-user/add-user';
import { FormsModule } from '@angular/forms';

interface Recruiter {
  id: number;
  name: string;
  email: string;
  role: string;
  phone?: string;
  gender?: string;
  interviews_count?: number;
}

interface RecruiterResponse {
  Success: boolean;
  Error?: string | null;
  RecruiterData?: Recruiter[];
  Data?: { RecruiterData?: Recruiter[] };
}

@Component({
  selector: 'app-evaluators',
  imports: [CommonModule, RecuiterProfile, FormsModule],
  templateUrl: './evaluators.html',
  styleUrls: ['./evaluators.scss']
})
export class Evaluators implements OnInit, OnDestroy {
  loading = false;
  errorMessage = '';
  recruitersList: Recruiter[] = [];
  allRecruiters: Recruiter[] = [];
  selectedEvaluator: Recruiter | null = null;
  searchTerm = '';
  private searchTimeoutId: ReturnType<typeof setTimeout> | null = null;

  constructor(private http: HttpClient, private dialog: MatDialog) {}

  ngOnInit(): void {
    this.loadEvaluators();
  }

  ngOnDestroy(): void {
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

  get displayedEvaluatorsCount(): number {
    return this.recruitersList.length;
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

  private syncSelectedEvaluatorReference(): void {
    if (!this.selectedEvaluator) return;
    const updated = this.allRecruiters.find((r) => r.id === this.selectedEvaluator?.id);
    if (updated) {
      this.selectedEvaluator = updated;
    }
  }

  loadEvaluators(): void {
    this.loading = true;
    this.errorMessage = '';
    const apiBaseUrl = this.getApiBaseUrl();

    this.http.get<RecruiterResponse>(`${apiBaseUrl}/get-evaluator/`)
      .pipe(
        catchError((error) => {
          console.error('Error fetching evaluators', error);
          this.loading = false;
          this.errorMessage = 'Failed to load evaluators. Please try again.';
          return of({ Success: false, RecruiterData: [] } as RecruiterResponse);
        })
      )
      .subscribe((response) => {
        const list = this.parseRecruiterData(response);
        this.allRecruiters = list;
        this.recruitersList = list;
        this.syncSelectedEvaluatorReference();
        this.loading = false;
      });
  }

  openProfile(recruiter: Recruiter): void {
    this.selectedEvaluator = recruiter;
  }

  addRecruiter(): void {
    const dialogRef = this.dialog.open(AddUser, {
      width: '550px',
      data: { type: 'Recruiter' }
    });

    dialogRef.afterClosed().subscribe((result) => {
      if (result) {
        const recruiter = result as Recruiter;
        this.allRecruiters = [recruiter, ...this.allRecruiters];
        this.applyLocalFilter();
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
      return;
    }

    this.recruitersList = this.allRecruiters.filter((r) =>
      [r.name, r.email, r.role, r.phone]
        .map((v) => (v || '').toString().toLowerCase())
        .some((v) => v.includes(term))
    );
  }

  private searchEvaluatorsRemote(term: string): void {
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
