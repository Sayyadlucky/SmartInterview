import { Component, AfterViewInit, OnInit, ViewChild, ElementRef, SimpleChanges, Input } from '@angular/core';
import { HttpClient } from '@angular/common/http';  // Import HttpClient
import { catchError } from 'rxjs/operators';
import { of } from 'rxjs';
import { CommonModule } from '@angular/common';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { RecuiterProfile } from "../recuiter-profile/recuiter-profile";
import { AddUser } from '../app-modal/add-user/add-user';
import { NgModule } from '@angular/core';
import { FormsModule } from '@angular/forms';

@Component({
  selector: 'app-evaluators',
  imports: [CommonModule, RecuiterProfile, FormsModule],
  templateUrl: './evaluators.html',
  styleUrls: ['./evaluators.scss']
})
export class Evaluators {

  constructor(private http: HttpClient, private dialog: MatDialog) {}  // Inject HttpClient and MatDialog
  data: any;
  loading: boolean = false;
  weekDays = ['S', 'M', 'T', 'W', 'T', 'F', 'S'];
  calendarDays: any[] = [];
  monthName = '';
  year = 0;
  recruiters_list: any[] = [];
  home_recruiters_list: any[] = [];
  is_profile_clicked: boolean = false;
  selectedEvaluator: any;
  searchTerm: string = '';
  
  // Example availability data (map evaluator's availability)
  availability: string[] = ['2025-09-10', '2025-09-18'];

  ngOnInit(): void {
    this.getEvaluator();
  }

  

  getEvaluator(){
    this.loading = true;
    let port_number = ''
        if(window.location.hostname === "127.0.0.1" || window.location.hostname === "localhost"){
          port_number = '8000'
        }
        const apiBaseUrl = `${window.location.protocol}//${window.location.hostname}:${port_number}`;
        this.http.get(apiBaseUrl + '/get-evaluator/?') // Replace with your API URL
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
            if(this.data?.RecruiterData){
             this.recruiters_list = this.data.RecruiterData;
             this.home_recruiters_list = this.data.RecruiterData;
            }
          });
  }

  openProfile(recruiter: any) {
    this.is_profile_clicked = false;
    setTimeout(() => {
      this.is_profile_clicked = true;
      this.selectedEvaluator = recruiter;
    }, 0);
  }

  addRecruiter() {
    const dialogRef = this.dialog.open(AddUser, {
          width: '550px',
          data: { type: 'Recruiter' }
        });
    
        dialogRef.afterClosed().subscribe(result => {
        if (result) {
          this.recruiters_list.push(result);
        }
        });
  }
  filterEvaluators() {
    if (!this.searchTerm) {
     this.recruiters_list = this.home_recruiters_list; // If search term is empty, fetch all evaluators
      return;
    }
    if(this.searchTerm.length > 3){
      clearTimeout((this as any)._searchTimeout);
      (this as any)._searchTimeout = setTimeout(() => {
        this.getfilteredEvaluators();
      }, 500); // 500ms after user stops typing
    }
  }
  getfilteredEvaluators() {
    let port_number = ''
        if(window.location.hostname === "127.0.0.1" || window.location.hostname === "localhost"){
          port_number = '8000'
        }
        const apiBaseUrl = `${window.location.protocol}//${window.location.hostname}:${port_number}`;
         const formData = new URLSearchParams();
        formData.append('name', this.searchTerm);

        fetch(`${apiBaseUrl}/evaluator-search/`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/x-www-form-urlencoded'
          },
          body: formData.toString()
        })
        .then(response => response.json())
        .then(data => {
          if (data && data.Success) {
            this.recruiters_list = data.RecruiterData || [];
          }else{
            alert('Error fetching profile data. Please try again.');
          }
        })
        .catch(error => {
          alert('Error fetching profile data. Please try again.');
        });
  }
}