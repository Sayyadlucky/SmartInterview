import { Component, AfterViewInit, OnInit, ViewChild, ElementRef, SimpleChanges } from '@angular/core';
import { HttpClient } from '@angular/common/http';  // Import HttpClient
import { catchError } from 'rxjs/operators';
import { of } from 'rxjs';
import { CommonModule } from '@angular/common';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { FormsModule } from '@angular/forms';
import { ProfileUpdate } from '../app-modal/profile-update/profile-update';
import { Evaluators } from '../evaluators/evaluators';
import { Chart, registerables } from 'chart.js';
import { CdkObserveContent } from "@angular/cdk/observers";
import * as XLSX from 'xlsx';
import { AddUser } from '../app-modal/add-user/add-user';
import { ConfirmationBox } from '../app-modal/confirmation-box/confirmation-box/confirmation-box';
import { RoleDetail } from '../app-modal/role-detail/role-detail';

Chart.register(...registerables);

@Component({
  selector: 'app-dashboard',
  standalone: true,
  templateUrl: './dashboard.html',
  styleUrls: ['./dashboard.scss'],
  imports: [CommonModule, MatDialogModule, Evaluators, FormsModule],
})
export class Dashboard implements OnInit, AfterViewInit {
  data: any;
  loading = false;
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
  activeCandidates: any;
  searchQuery = '';
  lastUpdatedAt: Date = new Date();
  roleCatalog: any[] = [];

  @ViewChild('sourcePerformanceCanvas', { static: false }) sourceCanvas!: ElementRef<HTMLCanvasElement>;
  private sourceChart!: Chart;
  rolesData: any;

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
    // --- Tabs ---
    const tabs = document.querySelectorAll('.tab-btn');
    const tabContents = document.querySelectorAll('.tab-content');
    tabs.forEach(tab => {
      tab.addEventListener('click', () => {
        tabs.forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        const target = tab.getAttribute('data-tab');
        tabContents.forEach(c => c.classList.remove('active'));
        document.getElementById(target!)?.classList.add('active');
      });
    });
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
    this.fetchData();
    this.fetchRoleCatalog();
    this.showPagination = (this.candidatesData?.length || 0) > this.pageSize;
  }

  private getApiBaseUrl(): string {
    let port_number = '';
    if (window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost') {
      port_number = '8000';
    }
    return `${window.location.protocol}//${window.location.hostname}:${port_number}`;
  }

  // Example API call
  fetchData(): void {
    this.loading = true;
    const apiBaseUrl = this.getApiBaseUrl();
    this.http.get(apiBaseUrl + '/dashboard-data/') // Replace with your API URL
      .pipe(
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
          this.candidatesData = this.data.Data.candidate_data;
          this.candidatesData = this.candidatesData.map((c: any) => {
            const normalized = this.normalizeStatus(c?.status);
            if (normalized === 'assessment pending') return { ...c, status: 'assessment pending' };
            if (normalized === 'auto screening scheduled') return { ...c, status: 'auto screening scheduled' };
            return c;
          });
          this.loginUser = this.data.Data.login_user.name;
          this.lastUpdatedAt = new Date();
          this.assign_status();
          // Render chart after data is loaded and view is initialized
          setTimeout(() => this.renderChart(), 5);
        }
      });
  }

  fetchRoleCatalog(): void {
    const apiBaseUrl = this.getApiBaseUrl();
    this.http.get(apiBaseUrl + '/get-role-list/')
      .pipe(
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

  profileUpdate(candidate?: any): void {
    const dialogRef = this.dialog.open(ProfileUpdate, {
      disableClose: true,
      width: '550px',
      data: { candidate }
    });

     dialogRef.afterClosed().subscribe(result => {
      if (result) {
        // result = updated candidate data returned from dialog
        this.updateCandidateData(result);
      }
    });
  }

  updateCandidateData(updatedCandidate: any) {
    // Replace the candidate in the local array with the updated one
    const index = this.candidatesData.findIndex(
      (c: any) => c.id === updatedCandidate.id
    );
    if (index > -1) {
      this.candidatesData[index] = updatedCandidate;
      this.assign_status();
      // Render chart after data is loaded and view is initialized
      setTimeout(() => this.renderChart(), 5);
    }
  }

  assign_status(){
  const list = this.candidatesData || [];

  this.scheduledCandidates = list.filter((c: any) => this.normalizeStatus(c?.status) === 'scheduled');
  this.completedCandidates = list.filter((c: any) => this.normalizeStatus(c?.status) === 'completed');
  this.cancelledCandidates = list.filter((c: any) => this.normalizeStatus(c?.status) === 'cancelled');
  this.shortlistedCandidates = list.filter((c: any) => this.normalizeStatus(c?.status) === 'shortlisted');
  this.hiredCandidates = list.filter((c: any) => this.normalizeStatus(c?.status) === 'completed');
  this.assessmentPendingCandidates = list.filter((c: any) => this.normalizeStatus(c?.status) === 'assessment pending');
  this.autoScreeningScheduledCandidates = list.filter((c: any) => this.normalizeStatus(c?.status) === 'auto screening scheduled');
  this.rejectedCandidates = list.filter((c: any) => this.normalizeStatus(c?.status) === 'rejected');
  this.assessmentCompletedCandidates = list.filter((c: any) => this.normalizeStatus(c?.status) === 'assessment completed');
  }

  trackCandidate(index: number, candidate: any): any {
  return candidate && candidate.id ? candidate.id : index;
  }

  get totalPages(): number {
  const statusFiltered = this.selectedStatus
    ? this.candidatesData.filter(
        (c: any) => this.normalizeStatus(c?.status) === this.normalizeStatus(this.selectedStatus)
      )
    : this.candidatesData;

  const search = this.searchQuery.trim().toLowerCase();
  const data = search
    ? statusFiltered.filter((c: any) =>
        [c?.name, c?.status, c?.recruiter, c?.role]
          .map((v: any) => (v || '').toString().toLowerCase())
          .some((v: string) => v.includes(search))
      )
    : statusFiltered;

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

  get filteredCandidates() {
  const statusFiltered = this.selectedStatus
  ? this.candidatesData.filter(
      (c: any) => this.normalizeStatus(c?.status) === this.normalizeStatus(this.selectedStatus)
    )
  : this.candidatesData;

  const search = this.searchQuery.trim().toLowerCase();
  const data = search
    ? statusFiltered.filter((c: any) =>
        [c?.name, c?.status, c?.recruiter, c?.role]
          .map((v: any) => (v || '').toString().toLowerCase())
          .some((v: string) => v.includes(search))
      )
    : statusFiltered;

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
  this.currentPage = 1; // reset to first page after filtering
}

clearSearch(): void {
  this.searchQuery = '';
  this.currentPage = 1;
}

get totalFilteredCandidatesCount(): number {
  return this.filteredCandidates?.length || 0;
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
  
private renderChart(): void {
  if (!this.sourceCanvas || !this.sourceCanvas.nativeElement) {
    // Canvas not yet available
    return;
  }
  const ctx = this.sourceCanvas.nativeElement;

  // Destroy previous chart if exists
  if (this.sourceChart) {
    this.sourceChart.destroy();
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
      datasets: [{ data: values, backgroundColor: colors }]
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      cutout: '50%'
    }
  });
}

openConfirmation(message: string = 'Are you sure you want to export Candidate data?'): void {
   const dialogRef = this.dialog.open(ConfirmationBox, {
      disableClose: true,
      width: '750px',
      data: { message }
    });

     dialogRef.afterClosed().subscribe(result => {
      if (result) {
        // Generate XLXS file for exported data
        (async () => {
          try {
            const allCandidates = (this.candidatesData || []).slice();
            const filtered = this.selectedStatus
              ? allCandidates.filter((c: any) => (c?.status || '').toString().toLowerCase() === this.selectedStatus!.toLowerCase())
              : allCandidates;

            if (!filtered.length) {
              window.alert('No candidates to export.');
              return;
            }

            // normalize nested objects to simple values for Excel
            const normalize = (val: any) => {
              if (val === null || val === undefined) return '';
              if (typeof val === 'object') {
                if ('name' in val && typeof val.name !== 'object') return val.name;
                return JSON.stringify(val);
              }
              return val;
            };

            const sheetData = filtered.map((c: any) => {
              const row: any = {};
              Object.keys(c).forEach(key => row[key] = normalize(c[key]));
              return row;
            });

            const XLSX = await import('xlsx');
            const ws = XLSX.utils.json_to_sheet(sheetData);
            const wb = XLSX.utils.book_new();
            XLSX.utils.book_append_sheet(wb, ws, 'Candidates');

            const wbout = XLSX.write(wb, { bookType: 'xlsx', type: 'array' });
            const blob = new Blob([wbout], { type: 'application/octet-stream' });
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `candidates_${(new Date()).toISOString().slice(0,19).replace(/[:T]/g,'-')}.xlsx`;
            document.body.appendChild(a);
            a.click();
            a.remove();
            window.URL.revokeObjectURL(url);
          } catch (err) {
            console.error('Export failed', err);
            window.alert('Failed to export candidates to Excel.');
          }
        })();
      }
    });
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
      disableClose: true,
      width: '550px',
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
}
