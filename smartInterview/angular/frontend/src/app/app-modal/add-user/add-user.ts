import { Component, CUSTOM_ELEMENTS_SCHEMA, Inject } from '@angular/core';
import { BrowserModule } from '@angular/platform-browser';
import { NgModule } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { HttpClient } from '@angular/common/http';  // Import HttpClient
import { catchError, of } from 'rxjs';
import { ReactiveFormsModule, FormControl } from '@angular/forms';
import { QuillModule } from 'ngx-quill';

@Component({
  selector: 'app-add-user',
  imports: [FormsModule, BrowserModule, QuillModule, ReactiveFormsModule],
  templateUrl: './add-user.html',
  styleUrls: ['./add-user.scss'],
  schemas: [CUSTOM_ELEMENTS_SCHEMA],
})
export class AddUser {
  NewRole: any;
  descriptionControl: FormControl = new FormControl('');
  constructor(
    private http: HttpClient,
    public dialogRef: MatDialogRef<AddUser>,
    @Inject(MAT_DIALOG_DATA) public data: any
  ) {}

  isAddUser = true;
  name: string = '';
  email: string = '';
  phone: string = '';
  role: string = '';
  errorMessage: string = '';
  description: string = '';
  vacancies: string = '';
  recruiter_list: any[] = [];
  recruiter: string = '';
  role_list: any[] = [];
  gender: string = '';

  newCandidate: any = {};
  userType: any;

  ngOnInit() {
    this.userType = this.data.type;
    if(this.userType === 'Role'){
      this.isAddUser = false;
      this.getHrList();
    }
    if(this.userType === 'Candidate'){
      this.getRoleList();
    }
  }
  getRoleList() {
    let port_number = ''
        if(window.location.hostname === "127.0.0.1" || window.location.hostname === "localhost"){
          port_number = '8000'
        }
        const apiBaseUrl = `${window.location.protocol}//${window.location.hostname}:${port_number}`;
        this.http.get(apiBaseUrl + '/get-role-list/') 
          .pipe(
            catchError(error => {
              console.error('Error fetching data', error);
              return of([]); // Return empty array on error
            })
          )
          .subscribe(response => {
            this.data = response;
            if(this.data?.RoleData){
              this.role_list = this.data.RoleData;
            }
          });
  }

  getRecruiters(recruiterId: any) {
    const selectedValue = (recruiterId.target as HTMLSelectElement).value;
    let port_number = ''
        if(window.location.hostname === "127.0.0.1" || window.location.hostname === "localhost"){
          port_number = '8000'
        }
        const apiBaseUrl = `${window.location.protocol}//${window.location.hostname}:${port_number}`;
        this.http.get(apiBaseUrl + '/get-vacancy-recruiters/'+selectedValue) 
          .pipe(
            catchError(error => {
              console.error('Error fetching data', error);
              return of([]); // Return empty array on error
            })
          )
          .subscribe(response => {
            this.data = response;
            if(this.data?.RecruiterData){
              this.recruiter_list = this.data.RecruiterData;
            }
          });
  }

  getHrList() {
    let port_number = ''
        if(window.location.hostname === "127.0.0.1" || window.location.hostname === "localhost"){
          port_number = '8000'
        }
        const apiBaseUrl = `${window.location.protocol}//${window.location.hostname}:${port_number}`;
        this.http.get(apiBaseUrl + '/get-hr-list/') 
          .pipe(
            catchError(error => {
              console.error('Error fetching data', error);
              return of([]); // Return empty array on error
            })
          )
          .subscribe(response => {
            this.data = response;
            if(this.data?.RecruiterData){
              this.recruiter_list = this.data.RecruiterData;
            }
          });
  }

  closeModal() {
    this.dialogRef.close();
  }
  addCandidate() {
    if (!this.name || !this.email || !this.phone || !this.gender) {
      this.errorMessage = 'All fields are required.';
      return;
    }
    if(this.userType !== 'Recruiter' && !this.role){
      this.errorMessage = 'All fields are required.';
      return;
    }
    // Name must contain at least one space between words
    if (!/\S+\s+\S+/.test(this.name)) {
      this.errorMessage = 'Name must contain first and last name.';
      return;
    }
    const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailPattern.test(this.email)) {
      this.errorMessage = 'Please enter a valid email address.';
      return;
    }
    this.errorMessage = '';
    let port_number = ''
    if(window.location.hostname === "127.0.0.1" || window.location.hostname === "localhost"){
      port_number = '8000'
    }
     const apiBaseUrl = `${window.location.protocol}//${window.location.hostname}:${port_number}`;
      const addUrl = `${apiBaseUrl}/add-user/`;

        const formData = new URLSearchParams();
        formData.append('email', this.email);
        formData.append('name', this.name);
        formData.append('phone', this.phone);
        formData.append('role', this.userType);
        formData.append('profile', this.role);
        formData.append('gender', this.gender);
        formData.append('recruiter', this.recruiter);

        fetch(addUrl, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/x-www-form-urlencoded'
          },
          body: formData.toString()
        })
        .then(response => response.json())
        .then(data => {
          if (data && data.Success) {
            if(this.userType === 'Recruiter'){
              this.newCandidate.id = data.RecruiterData.id;
              this.newCandidate.name = data.RecruiterData.name;
              this.newCandidate.email = data.RecruiterData.email;
              this.newCandidate.phone = data.RecruiterData.phone;
              this.newCandidate.role = data.RecruiterData.role;
              this.newCandidate.gender = data.RecruiterData.gender;
            }else{
              this.newCandidate.id = data.CandidateDetails.id;
              this.newCandidate.name = data.CandidateDetails.name;
              this.newCandidate.email = data.CandidateDetails.email;
              this.newCandidate.phone = data.CandidateDetails.phone;
              this.newCandidate.role = data.CandidateDetails.role;
              this.newCandidate.status = data.CandidateDetails.status;
              this.newCandidate.recruiter = data.CandidateDetails.recruiter;
              this.newCandidate.score = data.CandidateDetails.score;
              this.newCandidate.notes = data.CandidateDetails.notes;
            }
            this.dialogRef.close(this.newCandidate);
          } else{
            this.errorMessage = data.Error || 'Error adding candidate. Please try again.';
          }
        })
        .catch(error => {
          this.errorMessage = error.Message || 'Error adding candidate. Please try again.';
        });
  }
  addRole() {
    if (!this.name || !this.descriptionControl.value || !this.vacancies) {
      this.errorMessage = 'All fields are required.';
      return;
    }
    this.description = this.descriptionControl.value;
    if (!/^\d+$/.test(this.vacancies) || parseInt(this.vacancies, 10) <= 0) {
      this.errorMessage = 'Vacancies must be a positive number.';
      return;
    }
    this.errorMessage = '';
    let port_number = ''
    if(window.location.hostname === "127.0.0.1" || window.location.hostname === "localhost"){
      port_number = '8000'
    }
     const apiBaseUrl = `${window.location.protocol}//${window.location.hostname}:${port_number}`;
      const addUrl = `${apiBaseUrl}/add-role/`;

        const formData = new URLSearchParams();
        formData.append('description', this.description);
        formData.append('name', this.name);
        formData.append('vacancies', this.vacancies);
        formData.append('status', 'active');
        formData.append('recruiter', this.recruiter);

        fetch(addUrl, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/x-www-form-urlencoded'
          },
          body: formData.toString()
        })
        .then(response => response.json())
        .then(data => {
          if (data && data.Success) {
            this.NewRole = {};
            this.NewRole.id = data.Data.RoleDetails.id;
            this.NewRole.name = data.Data.RoleDetails.name;
            this.NewRole.description = data.Data.RoleDetails.description;
            this.NewRole.vacancies = data.Data.RoleDetails.vacancies;
            this.NewRole.date = data.Data.RoleDetails.date;
            this.NewRole.status = data.Data.RoleDetails.status;
            this.dialogRef.close(this.NewRole);
          } else{
            this.errorMessage = data.Error || 'Error adding role. Please try again.';
          }
        })
        .catch(error => {
          this.errorMessage = error.Message || 'Error adding role. Please try again.';
        });
  }
}

