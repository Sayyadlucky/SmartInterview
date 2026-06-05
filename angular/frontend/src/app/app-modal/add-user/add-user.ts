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
  postJobStep = 1;
  aiJdPanelOpen = false;
  isAiJdGenerating = false;
  aiJdErrorMessage = '';
  aiJdSuccessMessage = '';
  aiJdSuggestion: any = null;
  aiJdSuggestionSections: Array<{ title: string; value: string; items: string[] }> = [];
  aiJdForm = {
    roleContext: '',
    mustHaveSkills: '',
    preferredSkills: '',
    keyResponsibilities: '',
    candidateLevel: '',
    workModeContext: '',
    interviewFocus: '',
    tone: 'Professional',
  };
  readonly postJobSteps = [
    {
      number: 1,
      title: 'Job Details',
      subtitle: 'Basic information',
      panelTitle: 'Basic Information',
      panelCopy: 'Start with the core role details candidates will see first.',
      icon: 'ph ph-clipboard-text',
    },
    {
      number: 2,
      title: 'Role & Requirements',
      subtitle: 'Define the role',
      panelTitle: 'Role & Requirements',
      panelCopy: 'Describe responsibilities, must-have skills, and the role scope.',
      icon: 'ph ph-list-checks',
    },
    {
      number: 3,
      title: 'Compensation & Location',
      subtitle: 'Salary and location',
      panelTitle: 'Compensation & Location',
      panelCopy: 'Add openings, salary range, and where the role is based.',
      icon: 'ph ph-map-trifold',
    },
    {
      number: 4,
      title: 'Application & Settings',
      subtitle: 'Preferences',
      panelTitle: 'Application & Settings',
      panelCopy: 'Assign the recruiter owners who will manage this opening.',
      icon: 'ph ph-sliders-horizontal',
    },
    {
      number: 5,
      title: 'Review & Publish',
      subtitle: 'Final review',
      panelTitle: 'Review & Publish',
      panelCopy: 'Confirm the Shortlistii posting details before publishing.',
      icon: 'ph ph-paper-plane-tilt',
    },
  ];
  private roleFieldErrors: Record<string, boolean> = {};

  newCandidate: any = {};
  userType: any;
  readonly roleDescriptionLimit = 1200;
  isPhoneLookupLoading = false;
  phoneLookupMessage = '';
  private phoneLookupTimeout: any = null;
  private readonly phoneLookupMinDigits = 7;
  private aiJdAbortController: AbortController | null = null;
  private aiJdTimeout: any = null;
  private aiJdRequestId = 0;
  private readonly aiJdRequestTimeoutMs = 15000;
  readonly aiJdLoadingMessages = [
    'Reading role context and hiring signals...',
    'Structuring responsibilities and must-have skills...',
    'Drafting a candidate-ready job description...',
    'Polishing tone, clarity, and screening focus...',
    'Finalizing your JD suggestion for review...',
  ];

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
    this.abortAiJdRequest();
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

  get addUserModalIconClass(): string {
    if (this.userType === 'Candidate') return 'ph ph-user-plus';
    if (this.userType === 'Recruiter') return 'ph ph-identification-card';
    if (this.userType === 'Interviewer') return 'ph ph-chalkboard-teacher';
    return 'ph ph-user-circle-plus';
  }

  get addUserModalTitle(): string {
    return this.userType === 'Candidate' ? 'Assign Candidate' : `Add ${this.userType}`;
  }

  get addUserModalSubtitle(): string {
    if (this.userType === 'Candidate') {
      return 'Create or find a candidate profile, map it to a role, and assign the hiring owner.';
    }
    return 'Add details and link the record to the correct hiring owner.';
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
    if (!this.validateAllPostJobSteps()) {
      return;
    }
    this.description = this.descriptionControl.value;
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
    return value || 'Job title preview';
  }

  get roleInitial(): string {
    const title = this.rolePreviewTitle.trim();
    return title ? title.charAt(0).toUpperCase() : 'S';
  }

  get currentPostJobStep(): any {
    return this.postJobSteps.find((step) => step.number === this.postJobStep) || this.postJobSteps[0];
  }

  get jobTypeLabel(): string {
    if (this.jobType === 'full_time') return 'Full Time';
    if (this.jobType === 'part_time') return 'Part Time';
    if (this.jobType === 'intern') return 'Intern';
    return 'Employment type';
  }

  get previewSummaryLine(): string {
    const experience = this.experienceRequired || 'experience level';
    const employment = this.jobType ? this.jobTypeLabel : 'employment type';
    const location = this.location || 'location';
    return `${employment} role for ${experience}, based in ${location}.`;
  }

  get previewReadinessScore(): number {
    const checks = [
      !!this.name.trim(),
      !!this.jobType,
      !!this.experienceRequired.trim(),
      this.descriptionPlainTextLength >= 80,
      /^\d+$/.test(this.vacancies || '') && parseInt(this.vacancies, 10) > 0,
      !!this.location.trim(),
      !!this.salaryRange.trim(),
      this.selectedRoleRecruiterIds.length > 0,
    ];
    const completed = checks.filter(Boolean).length;
    return Math.round((completed / checks.length) * 100);
  }

  get previewReadinessLabel(): string {
    if (this.previewReadinessScore >= 88) return 'Ready';
    if (this.previewReadinessScore >= 55) return 'In progress';
    return 'Draft';
  }

  get previewReadinessText(): string {
    if (this.previewReadinessScore >= 88) {
      return 'This posting has enough detail for a confident candidate review.';
    }
    if (this.previewReadinessScore >= 55) {
      return 'Add the remaining required details to make this posting publish-ready.';
    }
    return 'Start with title, employment type, experience, description, compensation, and owner details.';
  }

  openAiJdPanel(): void {
    if (this.isSubmitting) return;
    this.aiJdPanelOpen = true;
    this.aiJdErrorMessage = '';
    this.aiJdSuccessMessage = '';
    if (!this.aiJdForm.candidateLevel && this.experienceRequired) {
      this.aiJdForm.candidateLevel = this.experienceRequired;
    }
    if (!this.aiJdForm.workModeContext && this.location) {
      this.aiJdForm.workModeContext = this.location;
    }
  }

  closeAiJdPanel(): void {
    this.aiJdRequestId += 1;
    this.abortAiJdRequest();
    this.isAiJdGenerating = false;
    this.aiJdPanelOpen = false;
    this.aiJdErrorMessage = '';
    this.aiJdSuccessMessage = '';
  }

  cancelAiJdGeneration(): void {
    this.aiJdRequestId += 1;
    this.abortAiJdRequest();
    this.isAiJdGenerating = false;
    this.aiJdErrorMessage = 'AI generation was cancelled. Your role description was not changed.';
  }

  rejectAiJdSuggestion(): void {
    if (this.isAiJdGenerating) return;
    this.aiJdSuggestion = null;
    this.aiJdSuggestionSections = [];
    this.aiJdSuccessMessage = '';
    this.aiJdErrorMessage = '';
  }

  generateAiJdSuggestion(): void {
    if (this.isSubmitting || this.isAiJdGenerating) return;
    this.aiJdErrorMessage = '';
    this.aiJdSuccessMessage = '';
    const hasRoleContext = !!this.normalizeWhitespace(this.aiJdForm.roleContext || this.name);
    const hasUsefulDetails = !!this.normalizeWhitespace(this.aiJdForm.mustHaveSkills || this.aiJdForm.keyResponsibilities);
    if (!hasRoleContext || !hasUsefulDetails) {
      this.aiJdErrorMessage = 'Add role context or must-have skills so AI can generate a useful JD.';
      return;
    }

    this.abortAiJdRequest();
    this.isAiJdGenerating = true;
    this.aiJdSuggestion = null;
    this.aiJdSuggestionSections = [];
    const requestId = this.aiJdRequestId + 1;
    this.aiJdRequestId = requestId;
    const requestController = new AbortController();
    this.aiJdAbortController = requestController;
    this.aiJdTimeout = setTimeout(() => {
      if (this.aiJdRequestId === requestId) {
        this.aiJdRequestId += 1;
        requestController.abort();
        this.finishAiJdGeneration();
        this.aiJdErrorMessage = 'AI generation is taking longer than expected. Please try again with a little more context.';
      }
    }, this.aiJdRequestTimeoutMs);
    const apiBaseUrl = this.getApiBaseUrl();
    fetch(`${apiBaseUrl}/api/jobs/generate-description/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal: requestController.signal,
      body: JSON.stringify({
        ...this.aiJdForm,
        name: this.name,
        jobType: this.jobTypeLabel,
        experienceRequired: this.experienceRequired,
        location: this.location,
        salaryRange: this.salaryRange,
        vacancies: this.vacancies,
        currentDescriptionPlainText: this.descriptionPlainText,
      }),
    })
      .then(async (response) => {
        const data = await response.json().catch(() => null);
        if (!response.ok) {
          throw new Error(data?.Error || 'Unable to generate a job description right now.');
        }
        return data;
      })
      .then((data) => {
        if (this.aiJdRequestId !== requestId) return;
        if (!data?.Success || !data?.Data?.suggestion) {
          throw new Error(data?.Error || 'Unable to generate a job description right now.');
        }
        const suggestion = data.Data.suggestion;
        const sections = this.buildAiJdSuggestionSections(suggestion);
        if (!sections.length) {
          throw new Error('AI returned a suggestion without usable job description content.');
        }
        this.aiJdSuggestion = suggestion;
        this.aiJdSuggestionSections = sections;
      })
      .catch((error) => {
        if (this.aiJdRequestId !== requestId) return;
        if (error?.name === 'AbortError') {
          this.aiJdErrorMessage = 'AI generation timed out or was cancelled. Your role description was not changed.';
          return;
        }
        this.aiJdErrorMessage = error?.message || 'Unable to generate a job description right now.';
      })
      .finally(() => {
        if (this.aiJdRequestId === requestId) {
          this.finishAiJdGeneration();
        }
      });
  }

  approveAndAppendAiJd(): void {
    if (!this.aiJdSuggestion || this.isSubmitting || this.isAiJdGenerating) return;
    const generatedHtml = this.buildSafeAiJdHtml(this.aiJdSuggestion);
    if (!generatedHtml) {
      this.aiJdErrorMessage = 'Generated JD did not include enough usable content to append.';
      return;
    }

    const existingHtml = (this.descriptionControl.value || '').toString().trim();
    const dividerHtml = existingHtml
      ? '<hr><p><strong>AI Suggested Job Description</strong></p>'
      : '<p><strong>AI Suggested Job Description</strong></p>';
    this.descriptionControl.setValue(`${existingHtml}${dividerHtml}${generatedHtml}`);
    this.descriptionControl.markAsDirty();
    this.descriptionControl.markAsTouched();
    this.aiJdSuccessMessage = 'AI suggestion appended to Role Description.';
    this.aiJdSuggestion = null;
    this.aiJdSuggestionSections = [];
    this.aiJdPanelOpen = false;
  }

  get descriptionPlainText(): string {
    const raw = (this.descriptionControl.value || '').toString();
    return raw.replace(/<[^>]*>/g, ' ').replace(/&nbsp;/g, ' ').replace(/\s+/g, ' ').trim();
  }

  trackByAiJdSectionTitle(_: number, section: { title: string }): string {
    return section.title;
  }

  trackByAiJdItem(index: number, item: string): string {
    return `${index}-${item}`;
  }

  private buildAiJdSuggestionSections(suggestion: any): Array<{ title: string; value: string; items: string[] }> {
    if (!suggestion) return [];
    return [
      { title: 'Role Overview', value: this.normalizeAiJdText(suggestion.overview, 1400), items: [] },
      { title: 'Key Responsibilities', value: '', items: this.safeStringList(suggestion.responsibilities) },
      { title: 'Required Skills', value: '', items: this.safeStringList(suggestion.required_skills) },
      { title: 'Preferred Skills', value: '', items: this.safeStringList(suggestion.preferred_skills) },
      { title: 'Success Criteria', value: '', items: this.safeStringList(suggestion.success_criteria) },
      { title: 'Interview Focus', value: '', items: this.safeStringList(suggestion.interview_focus) },
    ].filter((section) => !!section.value || section.items.length > 0);
  }

  private buildSafeAiJdHtml(suggestion: any): string {
    const sections = this.buildAiJdSuggestionSections(suggestion);
    if (!sections.length) return '';
    return sections.map((section) => {
      const title = `<p><strong>${this.escapeHtml(section.title)}</strong></p>`;
      if (section.value) {
        return `${title}<p>${this.escapeHtml(section.value)}</p>`;
      }
      const items = section.items.map((item) => `<li>${this.escapeHtml(item)}</li>`).join('');
      return items ? `${title}<ul>${items}</ul>` : '';
    }).join('');
  }

  private safeStringList(value: any): string[] {
    if (!Array.isArray(value)) return [];
    return value.map((item) => this.normalizeAiJdText(item, 280)).filter(Boolean).slice(0, 8);
  }

  private normalizeAiJdText(value: any, limit: number): string {
    return this.normalizeWhitespace(String(value || '')).slice(0, limit);
  }

  private escapeHtml(value: string): string {
    return this.normalizeWhitespace(value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  private abortAiJdRequest(): void {
    if (this.aiJdAbortController) {
      this.aiJdAbortController.abort();
      this.aiJdAbortController = null;
    }
    this.clearAiJdTimeout();
  }

  private clearAiJdTimeout(): void {
    if (this.aiJdTimeout) {
      clearTimeout(this.aiJdTimeout);
      this.aiJdTimeout = null;
    }
  }

  private finishAiJdGeneration(): void {
    this.clearAiJdTimeout();
    this.aiJdAbortController = null;
    this.isAiJdGenerating = false;
  }

  nextPostJobStep(): void {
    if (this.isSubmitting) return;
    if (!this.validatePostJobStep(this.postJobStep)) return;
    this.postJobStep = Math.min(5, this.postJobStep + 1);
    this.errorMessage = '';
  }

  previousPostJobStep(): void {
    if (this.isSubmitting) return;
    this.postJobStep = Math.max(1, this.postJobStep - 1);
    this.errorMessage = '';
  }

  goToPostJobStep(stepNumber: number): void {
    if (this.isSubmitting || stepNumber === this.postJobStep) return;
    if (stepNumber < this.postJobStep) {
      this.postJobStep = stepNumber;
      this.errorMessage = '';
      return;
    }

    for (let step = this.postJobStep; step < stepNumber; step += 1) {
      if (!this.validatePostJobStep(step)) {
        this.postJobStep = step;
        return;
      }
    }
    this.postJobStep = stepNumber;
    this.errorMessage = '';
  }

  isRoleFieldInvalid(field: string): boolean {
    return !!this.roleFieldErrors[field] && this.isRoleFieldCurrentlyInvalid(field);
  }

  private validateAllPostJobSteps(): boolean {
    for (let step = 1; step <= 4; step += 1) {
      if (!this.validatePostJobStep(step)) {
        this.postJobStep = step;
        return false;
      }
    }
    return true;
  }

  private validatePostJobStep(step: number): boolean {
    this.formatPostJobStepFields(step);
    const fieldsByStep: Record<number, string[]> = {
      1: ['name', 'jobType', 'experienceRequired'],
      2: ['description'],
      3: ['vacancies', 'location', 'salaryRange'],
      4: ['recruiter'],
    };
    const fields = fieldsByStep[step] || [];
    const invalidFields = fields.filter((field) => this.isRoleFieldCurrentlyInvalid(field));

    fields.forEach((field) => {
      this.roleFieldErrors[field] = invalidFields.includes(field);
    });

    if (!invalidFields.length) {
      this.errorMessage = '';
      return true;
    }

    this.errorMessage = this.getPostJobStepError(step, invalidFields);
    return false;
  }

  private isRoleFieldCurrentlyInvalid(field: string): boolean {
    if (field === 'description') {
      return this.descriptionPlainTextLength <= 0;
    }
    if (field === 'vacancies') {
      return !/^\d+$/.test(this.vacancies || '') || parseInt(this.vacancies, 10) <= 0;
    }
    if (field === 'recruiter') {
      return !this.selectedRoleRecruiterIds.length;
    }
    const value = (this as any)[field];
    return !value || !value.toString().trim();
  }

  private getPostJobStepError(step: number, invalidFields: string[]): string {
    if (step === 1) return 'Complete the required job details before continuing.';
    if (step === 2) return 'Role description is required before continuing.';
    if (step === 3 && invalidFields.includes('vacancies')) return 'Openings must be a positive number.';
    if (step === 3) return 'Complete compensation and location details before continuing.';
    if (step === 4) return 'Please select at least one recruiter.';
    return 'All fields are required.';
  }

  formatExperienceRequired(): void {
    this.experienceRequired = this.normalizeExperienceValue(this.experienceRequired);
  }

  formatSalaryRange(): void {
    this.salaryRange = this.normalizeSalaryRangeValue(this.salaryRange);
  }

  private formatPostJobStepFields(step: number): void {
    if (step === 1) {
      this.name = this.normalizeWhitespace(this.name);
      this.formatExperienceRequired();
    }
    if (step === 3) {
      this.vacancies = this.normalizeWhitespace(this.vacancies);
      this.location = this.normalizeWhitespace(this.location);
      this.formatSalaryRange();
    }
  }

  private normalizeWhitespace(value: string): string {
    return (value || '').replace(/\s+/g, ' ').trim();
  }

  private normalizeExperienceValue(value: string): string {
    const normalized = this.normalizeWhitespace(value)
      .replace(/[–—]/g, '-')
      .replace(/\s+to\s+/gi, '-')
      .replace(/\byrs?\b/gi, 'years')
      .replace(/\byear\b/gi, 'years');

    if (!normalized) return '';
    if (/^freshers?$/i.test(normalized)) return 'Fresher';

    const rangeMatch = normalized.match(/^(\d+(?:\.\d+)?\+?)\s*(?:years)?\s*-\s*(\d+(?:\.\d+)?\+?)\s*(?:years)?$/i);
    if (rangeMatch) {
      return `${rangeMatch[1]}-${rangeMatch[2]} years`;
    }

    const singleMatch = normalized.match(/^(\d+(?:\.\d+)?\+?)(?:\s*years)?$/i);
    if (singleMatch) {
      return `${singleMatch[1]} years`;
    }

    return normalized;
  }

  private normalizeSalaryRangeValue(value: string): string {
    const normalized = this.normalizeWhitespace(value)
      .replace(/[–—]/g, '-')
      .replace(/\s+to\s+/gi, '-')
      .replace(/\blakhs?\b/gi, 'LPA')
      .replace(/\blacs?\b/gi, 'LPA')
      .replace(/\blpa\b/gi, 'LPA');

    if (!normalized) return '';

    const rangeMatch = normalized.match(/^(\d+(?:\.\d+)?\+?)\s*(?:LPA)?\s*-\s*(\d+(?:\.\d+)?\+?)\s*(?:LPA)?$/i);
    if (rangeMatch) {
      return `${rangeMatch[1]} LPA - ${rangeMatch[2]} LPA`;
    }

    const singleMatch = normalized.match(/^(\d+(?:\.\d+)?\+?)\s*(?:LPA)?$/i);
    if (singleMatch) {
      return `${singleMatch[1]} LPA`;
    }

    return normalized;
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
