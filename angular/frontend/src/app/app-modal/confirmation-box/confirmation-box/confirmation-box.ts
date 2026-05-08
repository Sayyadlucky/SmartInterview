import { Component, Inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';

@Component({
  selector: 'app-confirmation-box',
  imports: [CommonModule],
  templateUrl: './confirmation-box.html',
  styleUrl: './confirmation-box.scss'
})
export class ConfirmationBox {
  title: string;
  message: string;
  confirmText: string;
  cancelText: string;
  mode: 'confirm' | 'export';
  selectedFormat: 'excel' | 'pdf' | 'word';
  exportSummary: any;
  constructor(
    public dialogRef: MatDialogRef<ConfirmationBox>,
    @Inject(MAT_DIALOG_DATA) public data: any,
  ) {
    this.title = data?.title || 'Please Confirm';
    this.message = data?.message || 'Are you sure you want to continue?';
    this.confirmText = data?.confirmText || 'Confirm';
    this.cancelText = data?.cancelText || 'Cancel';
    this.mode = data?.mode === 'export' ? 'export' : 'confirm';
    this.selectedFormat = data?.defaultFormat || 'excel';
    this.exportSummary = data?.exportSummary || null;
  }

  confirmNo() {
    this.dialogRef.close(false);
  }
  confirmYes() {
    this.dialogRef.close(this.mode === 'export' ? this.selectedFormat : true);
  }
  closeDialog() {
    this.dialogRef.close(false);
  }
}
