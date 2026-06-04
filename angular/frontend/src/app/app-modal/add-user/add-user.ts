import { Component, CUSTOM_ELEMENTS_SCHEMA, Inject, inject } from '@angular/core';
import { BrowserModule } from '@angular/platform-browser';
import { NgModule } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { HttpClient } from '@angular/common/http';  // Import HttpClient
import { catchError, of } from 'rxjs';
import { ReactiveFormsModule, FormControl } from '@angular/forms';
import { QuillModule } from 'ngx-quill';
import { AppToastService } from '../../core/app-toast.service';
import { DigitsOnlyDirective } from '../../core/digits-only.directive';

@Component({
  selector: 'app-add-user',
  imports: [FormsModule, BrowserModule, QuillModule, ReactiveFormsModule, DigitsOnlyDirective],
  templateUrl: './add-user.html',
  styleUrls: ['./add-user.scss'],
  schemas: [CUSTOM_ELEMENTS_SCHEMA],
})
export class AddUser {
  private readonly toast = inject(AppToastService);
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
  password: string = '';
  role: string = '';
  errorMessage: string = '';
  description: string = '';
  vacancies: string = '';
  jobType: string = '';
  location: string = '';
  salaryRange: string = '';
  experienceRequired: string = '';
  recruiter_list: any[] = [];
  recruiter: string = '';
  recruiterSearchQuery = '';
  selectedRoleRecruiterIds: string[] = [];
  showRoleRecruiterMenu = false;
  role_list: any[] = [];
  roleQuery = '';
  showCandidateRoleMenu = false;
  isRoleSearchActive = false;
  isRoleListLoading = false;
  roleListMessage = '';
  isRecruiterListLoading = false;
  recruiterListMessage = '';
  isSharedRecruiterListLoading = false;
  sharedRecruiterListMessage = '';
  gender: string = '';
  isSubmitting = false;

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
    if(this.userType === 'Interviewer'){
      this.getHrList();
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
      port_number = '8080';
    }
    return `${window.location.protocol}//${window.location.hostname}:${port_number}`;
  }

  private normalizePhone(value: string): string {
    return (value || '').replace(/\D/g, '');
  }

  getGenderIconClass(): string {
    if (this.gender === 'male') return 'ph ph-gender-male';
    if (this.gender === 'female') return 'ph ph-gender-female';
    if (this.gender === 'other') return 'ph ph-gender-nonbinary';
    return 'ph ph-user';
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
        this.isRoleListLoading = true;
        this.roleListMessage = 'Loading role catalog...';
        this.http.get(apiBaseUrl + '/get-role-list/')
          .pipe(
            catchError(error => {
              console.error('Error fetching data', error);
              this.isRoleListLoading = false;
              this.roleListMessage = 'Unable to load roles right now.';
              return of(null);
            })
          )
          .subscribe(response => {
            this.isRoleListLoading = false;
            this.data = response;
            if(this.data?.RoleData){
              this.role_list = this.data.RoleData;
              this.syncCandidateRoleLabel();
            }
            this.roleListMessage = this.role_list.length
              ? 'Search and select a role to continue.'
              : 'No roles are available right now.';
          });
  }

  getRecruiters(recruiterId: any) {
    const selectedValue = typeof recruiterId === 'string'
      ? recruiterId
      : (recruiterId.target as HTMLSelectElement).value;
    if (!selectedValue) {
      this.recruiter_list = [];
      this.recruiter = '';
      this.isRecruiterListLoading = false;
      this.recruiterListMessage = '';
      return;
    }
    this.isRecruiterListLoading = true;
    this.recruiterListMessage = 'Loading recruiters for the selected role...';
    this.recruiter_list = [];
    this.recruiter = '';
    const apiBaseUrl = this.getApiBaseUrl();
    this.http.get(apiBaseUrl + '/get-vacancy-recruiters/'+selectedValue)
      .pipe(
        catchError(error => {
          console.error('Error fetching data', error);
          this.isRecruiterListLoading = false;
          this.recruiterListMessage = 'Unable to load recruiters right now.';
          return of(null);
        })
      )
      .subscribe(response => {
        this.isRecruiterListLoading = false;
        this.data = response;
        if(this.data?.RecruiterData){
          this.recruiter_list = this.data.RecruiterData;
        }
        this.recruiterListMessage = this.recruiter_list.length
          ? `${this.recruiter_list.length} recruiter${this.recruiter_list.length === 1 ? '' : 's'} available for this role.`
          : 'No recruiters are currently mapped to this role.';
      });
  }

  get filteredCandidateRoles(): any[] {
    const search = (this.roleQuery || '').trim().toLowerCase();
    if (search.length < 3) {
      return [];
    }
    return (this.role_list || []).filter((r: any) => {
      const label = `${r.name || ''} ${r.id || ''}`.toLowerCase();
      return label.includes(search);
    }).slice(0, 50);
  }

  onCandidateRoleInputFocus(): void {
    this.isRoleSearchActive = true;
    this.showCandidateRoleMenu = true;
  }

  onCandidateRoleInputChange(value: string): void {
    this.roleQuery = value;
    this.isRoleSearchActive = !!value.trim();
    this.showCandidateRoleMenu = true;
    if (!value.trim()) {
      this.role = '';
      this.recruiter_list = [];
      this.recruiter = '';
      this.isRecruiterListLoading = false;
      this.recruiterListMessage = '';
      return;
    }
    this.role = '';
    this.recruiter_list = [];
    this.recruiter = '';
    this.isRecruiterListLoading = false;
    this.recruiterListMessage = 'Select a role to load recruiters.';
  }

  onCandidateRoleInputBlur(): void {
    setTimeout(() => {
      this.showCandidateRoleMenu = false;
      this.isRoleSearchActive = false;
      this.syncCandidateRoleLabel();
    }, 120);
  }

  selectCandidateRole(roleId: any, roleName: string): void {
    if (this.isSubmitting) return;
    this.role = String(roleId);
    this.roleQuery = `${roleName} - ${roleId}`;
    this.isRoleSearchActive = false;
    this.showCandidateRoleMenu = false;
    this.getRecruiters(this.role);
  }

  private syncCandidateRoleLabel(): void {
    const selected = (this.role_list || []).find((r: any) => String(r.id) === String(this.role));
    this.roleQuery = selected ? `${selected.name} - ${selected.id}` : '';
  }

  get isRecruiterSelectDisabled(): boolean {
    if (this.isSubmitting) {
      return true;
    }
    if (this.userType === 'Candidate') {
      return !this.role || this.isRoleSearchActive || this.isRecruiterListLoading;
    }
    if (this.userType === 'Interviewer') {
      return this.isSharedRecruiterListLoading;
    }
    return false;
  }

  get isCandidateRoleInputDisabled(): boolean {
    return this.userType === 'Candidate' && (this.isRoleListLoading || this.isSubmitting);
  }

  getHrList() {
        const apiBaseUrl = this.getApiBaseUrl();
        this.isSharedRecruiterListLoading = true;
        this.sharedRecruiterListMessage = this.userType === 'Role'
          ? 'Loading recruiter list...'
          : 'Loading recruiter / HR list...';
        this.http.get(apiBaseUrl + '/get-hr-list/')
          .pipe(
            catchError(error => {
              console.error('Error fetching data', error);
              this.isSharedRecruiterListLoading = false;
              this.sharedRecruiterListMessage = 'Unable to load recruiter options right now.';
              return of(null);
            })
          )
          .subscribe(response => {
            this.isSharedRecruiterListLoading = false;
            this.data = response;
            if(this.data?.RecruiterData){
              this.recruiter_list = this.data.RecruiterData;
            }
            this.sharedRecruiterListMessage = this.recruiter_list.length
              ? `${this.recruiter_list.length} recruiter${this.recruiter_list.length === 1 ? '' : 's'} available.`
              : 'No recruiter options are available right now.';
          });
  }

  private setSubmitting(value: boolean): void {
    this.isSubmitting = value;
    this.dialogRef.disableClose = value;
    if (value) {
      this.descriptionControl.disable({ emitEvent: false });
    } else {
      this.descriptionControl.enable({ emitEvent: false });
    }
  }

  closeModal() {
    if (this.isSubmitting) {
      return;
    }
    this.dialogRef.close();
  }
  addCandidate() {
    if (this.isSubmitting) {
      return;
    }
    if (!this.name || !this.email || !this.phone || !this.gender) {
      this.errorMessage = 'All fields are required.';
      return;
    }
    if (this.userType === 'Recruiter' && !this.password) {
      this.errorMessage = 'Password is required for recruiter login.';
      return;
    }
    if (this.userType === 'Recruiter' && this.password.length < 8) {
      this.errorMessage = 'Recruiter password must be at least 8 characters.';
      return;
    }
    if(this.userType === 'Candidate' && !this.role){
      this.errorMessage = 'All fields are required.';
      return;
    }
    if(this.userType === 'Interviewer' && !this.recruiter){
      this.errorMessage = 'Please select a recruiter for this evaluator.';
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
    this.setSubmitting(true);
     const apiBaseUrl = this.getApiBaseUrl();
      const addUrl = `${apiBaseUrl}/add-user/`;

        const formData = new URLSearchParams();
        formData.append('email', this.email);
        formData.append('name', this.name);
        formData.append('phone', this.phone);
        formData.append('password', this.password);
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
            if(this.userType === 'Recruiter' || this.userType === 'Interviewer'){
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
            const addedEntity = this.userType === 'Recruiter'
              ? 'Recruiter added'
              : this.userType === 'Interviewer'
                ? 'Interviewer added'
                : 'Candidate added';
            const addedDetail = this.userType === 'Candidate'
              ? `${this.newCandidate.name || this.name} is now available in ${this.role || 'the hiring workflow'}.`
              : `${this.newCandidate.name || this.name} is now available in the hiring workspace.`;
            this.toast.showSuccess(addedEntity, addedDetail);
            window.dispatchEvent(new CustomEvent('global-data-refresh', {
              detail: {
                entity: this.userType === 'Recruiter' ? 'recruiter' : this.userType === 'Interviewer' ? 'interviewer' : 'candidate',
                action: 'add',
                updatedAt: new Date().toISOString(),
              }
            }));
            this.dialogRef.close(this.newCandidate);
          } else{
            this.errorMessage = data.Error || 'Error adding candidate. Please try again.';
            this.toast.showError('Unable to save record', this.errorMessage);
          }
        })
        .catch(error => {
          this.errorMessage = error.Message || 'Error adding candidate. Please try again.';
          this.toast.showError('Unable to save record', this.errorMessage);
        })
        .finally(() => {
          this.setSubmitting(false);
        });
  }
  addRole() {
    if (this.isSubmitting) {
      return;
    }
    if (!this.name || !this.descriptionControl.value || !this.vacancies || !this.jobType || !this.location || !this.salaryRange || !this.experienceRequired) {
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
    this.setSubmitting(true);
     const apiBaseUrl = this.getApiBaseUrl();
      const addUrl = `${apiBaseUrl}/add-role/`;

        const formData = new URLSearchParams();
        formData.append('description', this.description);
        formData.append('name', this.name);
        formData.append('vacancies', this.vacancies);
        formData.append('job_type', this.jobType);
        formData.append('location', this.location);
        formData.append('salary_range', this.salaryRange);
        formData.append('experience_required', this.experienceRequired);
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
            this.NewRole.job_type = data.Data.RoleDetails.job_type;
            this.NewRole.location = data.Data.RoleDetails.location;
            this.NewRole.salary_range = data.Data.RoleDetails.salary_range;
            this.NewRole.experience_required = data.Data.RoleDetails.experience_required;
            this.NewRole.date = data.Data.RoleDetails.date;
            this.NewRole.status = data.Data.RoleDetails.status;
            this.toast.showSuccess('Role created', `${this.NewRole.name || this.name} is now available for hiring workflows.`);
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
            this.toast.showError('Unable to create role', this.errorMessage);
          }
        })
        .catch(error => {
          this.errorMessage = error.Message || 'Error adding role. Please try again.';
          this.toast.showError('Unable to create role', this.errorMessage);
        })
        .finally(() => {
          this.setSubmitting(false);
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
    if (this.isSubmitting) return;
    const current = Number(this.vacancies || 0);
    const next = Math.max(0, current) + 1;
    this.vacancies = String(next);
  }

  decrementVacancies(): void {
    if (this.isSubmitting) return;
    const current = Number(this.vacancies || 0);
    const next = Math.max(1, current - 1);
    this.vacancies = String(next);
  }

  get filteredRoleRecruiters(): any[] {
    const search = (this.recruiterSearchQuery || '').trim().toLowerCase();
    if (search.length < 3) {
      return [];
    }
    return (this.recruiter_list || []).filter((r: any) => {
      const id = String(r.id);
      if (this.selectedRoleRecruiterIds.includes(id)) return false;
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
    if (this.isSubmitting) return;
    const value = String(id);
    if (!value || this.selectedRoleRecruiterIds.includes(value)) return;
    this.selectedRoleRecruiterIds = [...this.selectedRoleRecruiterIds, value];
    this.recruiterSearchQuery = '';
    this.showRoleRecruiterMenu = true;
  }

  removeRoleRecruiter(id: any): void {
    if (this.isSubmitting) return;
    const value = String(id);
    this.selectedRoleRecruiterIds = this.selectedRoleRecruiterIds.filter((x) => x !== value);
  }

  getRoleRecruiterName(id: any): string {
    const selected = this.recruiter_list.find((r: any) => String(r.id) === String(id));
    return selected?.name || `Recruiter ${id}`;
  }
}
