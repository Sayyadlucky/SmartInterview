import { Component, Inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { HttpClient } from '@angular/common/http';  // Import HttpClient
import { catchError, of } from 'rxjs';

@Component({
  selector: 'app-role-detail',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './role-detail.html',
  styleUrl: './role-detail.scss'
})
export class RoleDetail {
  constructor(
    private http: HttpClient,
    public dialogRef: MatDialogRef<RoleDetail>,
    @Inject(MAT_DIALOG_DATA) public data: any
  ) {}

  loading: boolean = false;
  errorMessage = '';
  roleDetails: any = '';
  totalVacancies: number = 0;
  appliedCandidates: number = 0;
  shortlistedCandidates: number = 0;
  hiredCandidates: number = 0;
  description: string = '';
  roleStatus = '';
  roleDate = '';
  jobType = '';
  location = '';
  salaryRange = '';
  experienceRequired = '';
  readonly summaryCards = [
    { key: 'vacancies', label: 'Approved Headcount', icon: 'ph-briefcase-metal', value: 0 },
    { key: 'applied', label: 'Applicants Received', icon: 'ph-users-three', value: 0 },
    { key: 'inProgress', label: 'Active Pipeline', icon: 'ph-path', value: 0 },
    { key: 'hired', label: 'Closed Hires', icon: 'ph-handshake', value: 0 },
  ];
  detailHighlights: Array<{ label: string; value: string; icon: string; helper: string }> = [];

  get roleTitleWithId(): string {
    const roleName = (this.roleDetails || '').toString().trim();
    const id = (this.data?.role_id ?? '').toString().trim();
    if (!roleName) return id || 'Role Details';
    return id ? `${roleName} - ${id}` : roleName;
  }

  get initialRoleLoading(): boolean {
    return this.loading && !this.roleDetails && !this.errorMessage;
  }

closeModal() {
    this.dialogRef.close();
  }

  ngOnInit(): void {
    this.fetchRoleDetails(this.data.role_id);
  }
  fetchRoleDetails(role_id: any) {
    this.loading = true;
    this.errorMessage = '';
        let port_number = ''
        if(window.location.hostname === "127.0.0.1" || window.location.hostname === "localhost"){
          port_number = '8080'
        }
        const apiBaseUrl = `${window.location.protocol}//${window.location.hostname}:${port_number}`;
        this.http.get(apiBaseUrl + '/get-role-data/' + role_id)
          .pipe(
            catchError(error => {
              console.error('Error fetching data', error);
              this.loading = false;
              this.errorMessage = 'Unable to load role details.';
              return of([]); // Return empty array on error
            })
          )
          .subscribe((response: any) => {
            this.loading = false;
            if (response && response?.Success && response.RoleData) {
              const role = response.RoleData;
              this.roleDetails = role.name;
              this.description = role.description || '';
              this.totalVacancies = this.extractNumber(role.position);
              this.appliedCandidates = this.extractNumber(role.applications);
              this.shortlistedCandidates = this.extractNumber(role.inprogress);
              this.hiredCandidates = this.extractNumber(role.hired);
              this.roleStatus = (role.status || '').toString();
              this.roleDate = role.date || '';
              this.jobType = role.job_type || '';
              this.location = role.location || '';
              this.salaryRange = role.salary_range || '';
              this.experienceRequired = role.experience_required || '';
              this.updatePresentationState();
            } else {
              this.errorMessage = 'No role data found.';
            }
          });
  }

  get openPositions(): number {
    return Math.max(this.totalVacancies - this.hiredCandidates, 0);
  }

  get fulfillmentRate(): number {
    if (!this.totalVacancies) return 0;
    return Math.min(100, Math.round((this.hiredCandidates / this.totalVacancies) * 100));
  }

  get inProgressRate(): number {
    if (!this.appliedCandidates) return 0;
    return Math.min(100, Math.round((this.shortlistedCandidates / this.appliedCandidates) * 100));
  }

  get conversionRate(): number {
    if (!this.appliedCandidates) return 0;
    return Math.min(100, Math.round((this.hiredCandidates / this.appliedCandidates) * 100));
  }

  get urgencyLabel(): string {
    if (!this.openPositions) return 'Hiring target met';
    if (this.appliedCandidates < this.totalVacancies) return 'Pipeline needs immediate attention';
    if (this.fulfillmentRate >= 60) return 'Delivery on track';
    return 'Open positions still require coverage';
  }

  get roleStatusLabel(): string {
    const status = this.roleStatus.trim().toLowerCase();
    if (!status) return 'Status pending';
    if (status === 'active') return 'Active requisition';
    if (status === 'closed') return 'Closed requisition';
    return `${this.roleStatus} requisition`;
  }

  private updatePresentationState(): void {
    this.summaryCards[0].value = this.totalVacancies;
    this.summaryCards[1].value = this.appliedCandidates;
    this.summaryCards[2].value = this.shortlistedCandidates;
    this.summaryCards[3].value = this.hiredCandidates;

    this.detailHighlights = [
      {
        label: 'Employment Type',
        value: this.jobType || 'Not specified',
        icon: 'ph-bag-simple',
        helper: 'Contract structure for the role',
      },
      {
        label: 'Location',
        value: this.location || 'Not specified',
        icon: 'ph-map-pin',
        helper: 'Primary delivery or work location',
      },
      {
        label: 'Compensation',
        value: this.salaryRange || 'Not specified',
        icon: 'ph-currency-circle-dollar',
        helper: 'Published salary guidance',
      },
      {
        label: 'Experience',
        value: this.experienceRequired || 'Not specified',
        icon: 'ph-chart-line-up',
        helper: 'Target experience range',
      },
    ];
  }

  private extractNumber(value: any): number {
    if (Array.isArray(value)) return Number(value[0] || 0);
    return Number(value || 0);
  }

}
