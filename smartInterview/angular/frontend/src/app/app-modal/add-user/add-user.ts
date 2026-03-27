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
  recruiterSearchQuery = '';
  selectedRoleRecruiterIds: string[] = [];
  showRoleRecruiterMenu = false;
  role_list: any[] = [];
  gender: string = '';

  newCandidate: any = {};
  userType: any;
  readonly roleDescriptionLimit = 1200;
  isPhoneLookupLoading = false;
  phoneLookupMessage = '';
  private phoneLookupTimeout: any = null;
  private readonly phoneLookupMinDigits = 7;

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

  ngOnDestroy(): void {
    if (this.phoneLookupTimeout) {
      clearTimeout(this.phoneLookupTimeout);
      this.phoneLookupTimeout = null;
    }
  }

  private getApiBaseUrl(): string {
    let port_number = '';
    if (window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost') {
      port_number = '8000';
    }
    return `${window.location.protocol}//${window.location.hostname}:${port_number}`;
  }

  private normalizePhone(value: string): string {
    return (value || '').replace(/\D/g, '');
  }

  onPhoneInput(value: string): void {
    this.phone = value;
    this.phoneLookupMessage = '';
    this.errorMessage = '';

    if (this.phoneLookupTimeout) {
      clearTimeout(this.phoneLookupTimeout);
      this.phoneLookupTimeout = null;
    }

    const normalized = this.normalizePhone(value);
    if (normalized.length < this.phoneLookupMinDigits) {
      this.isPhoneLookupLoading = false;
      return;
    }

    this.isPhoneLookupLoading = true;
    this.phoneLookupTimeout = setTimeout(() => {
      this.lookupUserByPhone(normalized);
    }, 450);
  }

  private lookupUserByPhone(phone: string): void {
    const apiBaseUrl = this.getApiBaseUrl();
    this.http
      .get(`${apiBaseUrl}/lookup-user-by-phone/`, { params: { phone } })
      .pipe(
        catchError((error) => {
          console.error('Error looking up user by phone', error);
          this.isPhoneLookupLoading = false;
          this.phoneLookupMessage = '';
          return of(null);
        })
      )
      .subscribe((response: any) => {
        this.isPhoneLookupLoading = false;
        if (!response?.Success || !response?.Data) {
          this.phoneLookupMessage = '';
          return;
        }

        if (!response.Data.found || !response.Data.user) {
          this.phoneLookupMessage = '';
          return;
        }

        const user = response.Data.user;
        this.name = user.name || '';
        this.email = user.email || '';
        this.gender = user.gender || '';
        this.phoneLookupMessage = 'Existing profile found. Details auto-filled.';
      });
  }

  getRoleList() {
        const apiBaseUrl = this.getApiBaseUrl();
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
        const apiBaseUrl = this.getApiBaseUrl();
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
        const apiBaseUrl = this.getApiBaseUrl();
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
     const apiBaseUrl = this.getApiBaseUrl();
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
              this.newCandidate.notification = data.Notification || null;
              this.newCandidate.signupRequired = !!data.SignupRequired;
              this.newCandidate.candidateExists = !!data.CandidateExists;
            }
            window.dispatchEvent(new CustomEvent('global-data-refresh', {
              detail: {
                entity: this.userType === 'Recruiter' ? 'recruiter' : 'candidate',
                action: 'add',
                updatedAt: new Date().toISOString(),
              }
            }));
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
    if (!this.selectedRoleRecruiterIds.length) {
      this.errorMessage = 'Please select at least one recruiter.';
      return;
    }
    this.description = this.descriptionControl.value;
    if (!/^\d+$/.test(this.vacancies) || parseInt(this.vacancies, 10) <= 0) {
      this.errorMessage = 'Vacancies must be a positive number.';
      return;
    }
    this.errorMessage = '';
     const apiBaseUrl = this.getApiBaseUrl();
      const addUrl = `${apiBaseUrl}/add-role/`;

        const formData = new URLSearchParams();
        formData.append('description', this.description);
        formData.append('name', this.name);
        formData.append('vacancies', this.vacancies);
        formData.append('status', 'active');
        this.selectedRoleRecruiterIds.forEach((id) => formData.append('recruiter', id));

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
            window.dispatchEvent(new CustomEvent('global-data-refresh', {
              detail: {
                entity: 'role',
                action: 'add',
                roleId: this.NewRole.id,
                updatedAt: new Date().toISOString(),
              }
            }));
            this.dialogRef.close(this.NewRole);
          } else{
            this.errorMessage = data.Error || 'Error adding role. Please try again.';
          }
        })
        .catch(error => {
          this.errorMessage = error.Message || 'Error adding role. Please try again.';
        });
  }

  get descriptionPlainTextLength(): number {
    const raw = (this.descriptionControl.value || '').toString();
    const plain = raw.replace(/<[^>]*>/g, ' ').replace(/&nbsp;/g, ' ').replace(/\s+/g, ' ').trim();
    return plain.length;
  }

  get selectedRecruiterName(): string {
    if (!this.selectedRoleRecruiterIds.length) return 'Not assigned';
    const names = this.recruiter_list
      .filter((r: any) => this.selectedRoleRecruiterIds.includes(String(r.id)))
      .map((r: any) => r.name);
    if (names.length <= 2) return names.join(', ');
    return `${names[0]}, ${names[1]} +${names.length - 2}`;
  }

  get rolePreviewTitle(): string {
    const value = (this.name || '').trim();
    return value || 'Role title preview';
  }

  incrementVacancies(): void {
    const current = Number(this.vacancies || 0);
    const next = Math.max(0, current) + 1;
    this.vacancies = String(next);
  }

  decrementVacancies(): void {
    const current = Number(this.vacancies || 0);
    const next = Math.max(1, current - 1);
    this.vacancies = String(next);
  }

  get filteredRoleRecruiters(): any[] {
    const search = (this.recruiterSearchQuery || '').trim().toLowerCase();
    return (this.recruiter_list || []).filter((r: any) => {
      const id = String(r.id);
      if (this.selectedRoleRecruiterIds.includes(id)) return false;
      if (!search) return true;
      return (r.name || '').toString().toLowerCase().includes(search);
    }).slice(0, 50);
  }

  openRoleRecruiterMenu(): void {
    this.showRoleRecruiterMenu = true;
  }

  closeRoleRecruiterMenu(): void {
    setTimeout(() => {
      this.showRoleRecruiterMenu = false;
    }, 120);
  }

  addRoleRecruiter(id: any): void {
    const value = String(id);
    if (!value || this.selectedRoleRecruiterIds.includes(value)) return;
    this.selectedRoleRecruiterIds = [...this.selectedRoleRecruiterIds, value];
    this.recruiterSearchQuery = '';
    this.showRoleRecruiterMenu = true;
  }

  removeRoleRecruiter(id: any): void {
    const value = String(id);
    this.selectedRoleRecruiterIds = this.selectedRoleRecruiterIds.filter((x) => x !== value);
  }

  getRoleRecruiterName(id: any): string {
    const selected = this.recruiter_list.find((r: any) => String(r.id) === String(id));
    return selected?.name || `Recruiter ${id}`;
  }
}
