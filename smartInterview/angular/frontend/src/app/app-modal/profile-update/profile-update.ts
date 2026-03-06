import { Component, Inject, Input, OnChanges, OnInit, SimpleChanges } from '@angular/core';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';  // Import HttpClient
import { catchError } from 'rxjs/operators';
import { of } from 'rxjs';

@Component({
  selector: 'app-profile-update',
  imports: [CommonModule],
  providers: [],
  templateUrl: './profile-update.html',
  styleUrls: ['./profile-update.scss']
})
export class ProfileUpdate implements OnInit {
  candidate: any;
  filteredStatuses: any = {};

  constructor(
    public dialogRef: MatDialogRef<ProfileUpdate>,
    @Inject(MAT_DIALOG_DATA) public data: any,
  ) {
    this.candidate = data.candidate;
  }

  ngOnInit() {
    if (this.candidate !== undefined && this.candidate !== null) {
      this.calculateStatus();
    } else {
      console.warn('Candidate input is undefined or null');
    }
  }

  calculateStatus(): void {
    if (!this.candidate || !this.candidate.status) {
      this.filteredStatuses = {};
      return;
    }

    // Normalize status to handle case/typo variants like "Assesment_Completed" or "assessment_Pending"
    const normalize = (s: string) =>
      s
        .toString()
        .trim()
        .toLowerCase()
        .replace(/\s+/g, '_')
        .replace(/-+/g, '_')
        .replace(/assesment/g, 'assessment');

    const status = normalize(this.candidate.status);

    const DEFAULT = {
      scheduled: 'In Progress',
      rejected: 'Disqualified',
      shortlisted: 'Shortlisted',
      completed: 'Hired',
      cancelled: 'Cancelled',
      assessment_pending: 'Assessments Pending',
    };

    const OVERRIDES: Record<string, Record<string, string>> = {
      scheduled: {
        rejected: 'Disqualified',
        shortlisted: 'Shortlisted',
        cancelled: 'Cancelled',
      },
      completed: {}, // no transitions
      shortlisted: {
        completed: 'Hired',
        rejected: 'Disqualified',
        cancelled: 'Cancelled',
      },
      assessment_completed: {
        scheduled: 'In Progress',
        rejected: 'Disqualified',
        cancelled: 'Cancelled',
      },
      assessment_pending: {
        scheduled: 'In Progress',
        rejected: 'Disqualified',
        cancelled: 'Cancelled',
      },
      rejected: {
        assessment_pending: 'Assessments Pending',
        cancelled: 'Cancelled',
      },
    };

    this.filteredStatuses = OVERRIDES[status] ?? DEFAULT;
  }

  formatRoleWithId(role: string, roleId?: number | null): string {
    const roleName = (role || '').toString().trim();
    const id = (roleId ?? '').toString().trim();
    if (!roleName) return id;
    return id ? `${roleName} - ${id}` : roleName;
  }

  changeStatus(newStatus: string) {
    // Update the candidate's status
    this.candidate.status = newStatus;
    this.updateStatusInDb();
  }

  updateStatusInDb(): void{
    let port_number = ''
    if(window.location.hostname === "127.0.0.1" || window.location.hostname === "localhost"){
      port_number = '8000'
    }
     const apiBaseUrl = `${window.location.protocol}//${window.location.hostname}:${port_number}`;
      const updateUrl = `${apiBaseUrl}/update-candidate-status/`;           
        const formData = new FormData();
        formData.append('candidateId', this.candidate.id);
        formData.append('newStatus', this.candidate.status);

        fetch(updateUrl, {
          method: 'POST',
          body: formData
        })
        .then(response => response.json())
        .then(data => {
          if (data && data.Success) {
          this.closeDialog();
          }
        })
        .catch(error => {
          console.error('Error fetching data', error);
        });
    }

  closeDialog(){
    // Close the dialog
    this.dialogRef.close(this.candidate);
  }

  cancel() {
    this.dialogRef.close(null); // nothing changed
  }
}
