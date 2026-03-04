import { Component, Inject } from '@angular/core';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { HttpClient } from '@angular/common/http';  // Import HttpClient
import { catchError, of } from 'rxjs';

@Component({
  selector: 'app-role-detail',
  imports: [],
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
  roleDetails: any = '';
  totalCandidates: number = 0;
  appliedCandidates: number = 0;
  shortlistedCandidates: number = 0;
  HiredCandidates: number = 0;
  description: string = '';
  responseData: any;

closeModal() {
    this.dialogRef.close();
  }

  ngOnInit(): void {
    this.fetchRoleDetails(this.data.role_id);
  }
  fetchRoleDetails(role_id: any) {
    this.loading = true;
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
              return of([]); // Return empty array on error
            })
          )
          .subscribe(response => {
            // this.data = response;
            this.loading = false;
            this.responseData = response;
            if (this.responseData && this.responseData?.Success && this.responseData.RoleData) {
              const role = this.responseData.RoleData;
              this.roleDetails = role.name;
              this.description = role.description || '';
              this.totalCandidates = role.applications[0];
              this.appliedCandidates = role.applications[0];
              this.shortlistedCandidates = role.inprogress[0];
              this.HiredCandidates = role.hired[0];
            }
          });
  }


}
