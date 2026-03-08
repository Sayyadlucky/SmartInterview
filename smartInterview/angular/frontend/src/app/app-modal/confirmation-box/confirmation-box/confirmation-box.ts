import { Component, Inject } from '@angular/core';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';

@Component({
  selector: 'app-confirmation-box',
  imports: [],
  templateUrl: './confirmation-box.html',
  styleUrl: './confirmation-box.scss'
})
export class ConfirmationBox {
  title: string;
  message: string;
  confirmText: string;
  cancelText: string;
  constructor(
    public dialogRef: MatDialogRef<ConfirmationBox>,
    @Inject(MAT_DIALOG_DATA) public data: any,
  ) {
    this.title = data?.title || 'Please Confirm';
    this.message = data?.message || 'Are you sure you want to continue?';
    this.confirmText = data?.confirmText || 'Confirm';
    this.cancelText = data?.cancelText || 'Cancel';
  }

  confirmNo() {
    this.dialogRef.close(false);
  }
  confirmYes() {
    this.dialogRef.close(true);
  }
  closeDialog() {
    this.dialogRef.close(false);
  }
}
