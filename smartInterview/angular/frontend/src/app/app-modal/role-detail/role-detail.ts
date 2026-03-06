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
          port_number = '8000'
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

  private extractNumber(value: any): number {
    if (Array.isArray(value)) return Number(value[0] || 0);
    return Number(value || 0);
  }

}
