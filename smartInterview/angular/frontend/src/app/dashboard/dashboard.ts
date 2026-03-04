import { Component, AfterViewInit, OnInit, ViewChild, ElementRef, SimpleChanges } from '@angular/core';
import { HttpClient } from '@angular/common/http';  // Import HttpClient
import { catchError } from 'rxjs/operators';
import { of } from 'rxjs';
import { CommonModule } from '@angular/common';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
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
  imports: [CommonModule, MatDialogModule, Evaluators],
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
  rejectedCandidates: any;
  assessmentCompletedCandidates: any;
  selectedStatus: string | null = null;
  pageSize: number = 10;          // candidates per page
  currentPage: number = 1;        // starting page
  showPagination: boolean = false;
  loginUser = '';
  activeCandidates: any;

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
    this.rejectedCandidates = [];
    this.assessmentCompletedCandidates = [];
  }
  ngOnInit(): void {
    this.fetchData();
    this.showPagination = (this.candidatesData?.length || 0) > this.pageSize;
  }

  // Example API call
  fetchData(): void {
    this.loading = true;
    let port_number = ''
    if(window.location.hostname === "127.0.0.1" || window.location.hostname === "localhost"){
      port_number = '8000'
    }
    const apiBaseUrl = `${window.location.protocol}//${window.location.hostname}:${port_number}`;
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
            if ((c?.status || '').toString().toLowerCase() === 'assessment_pending') {
              return { ...c, status: 'assessment pending' };
            }
            return c;
          });
          this.loginUser = this.data.Data.login_user.name;
          this.assign_status();
          // Render chart after data is loaded and view is initialized
          setTimeout(() => this.renderChart(), 5);
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

  this.scheduledCandidates = list.filter((c: any) => (c?.status || '').toString().toLowerCase() === 'scheduled');
  this.completedCandidates = list.filter((c: any) => (c?.status || '').toString().toLowerCase() === 'completed');
  this.cancelledCandidates = list.filter((c: any) => (c?.status || '').toString().toLowerCase() === 'cancelled');
  this.shortlistedCandidates = list.filter((c: any) => (c?.status || '').toString().toLowerCase() === 'shortlisted');
  this.hiredCandidates = list.filter((c: any) => (c?.status || '').toString().toLowerCase() === 'completed');

  // accept common variants for assessment pending/completed so mismatched casing/spacing won't break lists
  this.assessmentPendingCandidates = list.filter((c: any) => {
    const s = (c?.status || '').toString().toLowerCase();
    return s === 'assessment pending' || s === 'assessment_pending';
  });

  this.rejectedCandidates = list.filter((c: any) => (c?.status || '').toString().toLowerCase() === 'rejected');

  this.assessmentCompletedCandidates = list.filter((c: any) => {
    const s = (c?.status || '').toString().toLowerCase();
    return s === 'assessment_completed' || s === 'assessment completed' || s === 'assesment completed' || s === 'assesment_completed';
  });
  }

  trackCandidate(index: number, candidate: any): any {
  return candidate && candidate.id ? candidate.id : index;
  }

  get totalPages(): number {
  const data = this.selectedStatus
    ? this.candidatesData.filter(
        (c: any) => c.status.toLowerCase() === this.selectedStatus?.toLowerCase()
      )
    : this.candidatesData;

  return Math.ceil(data.length / this.pageSize) || 1;
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
  const data = this.selectedStatus
  ? this.candidatesData.filter(
      (c: any) => c.status.toLowerCase() === this.selectedStatus?.toLowerCase()
    )
  : this.candidatesData;
    if(data?.length > 0){
      this.showPagination = true
    }else{
      this.showPagination = false
    }
  const totalPages = Math.ceil(data?.length / this.pageSize);
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
    this.rejectedCandidates?.length || 0,
    this.assessmentPendingCandidates?.length || 0,
    this.cancelledCandidates?.length || 0
  ];

  const labels = ['Scheduled ', 'Shortlisted ', 'Hired ', 'Rejected ', 'Assessment Pending ', 'Cancelled '];
  const colors = ['#22d3ee', '#3b82f6', '#10b981', '#ef4444', '#f59e0b', '#9ca3af'];

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
