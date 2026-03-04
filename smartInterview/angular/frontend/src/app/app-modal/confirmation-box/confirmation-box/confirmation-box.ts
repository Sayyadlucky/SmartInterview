import { Component, Inject } from '@angular/core';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';

@Component({
  selector: 'app-confirmation-box',
  imports: [],
  templateUrl: './confirmation-box.html',
  styleUrl: './confirmation-box.scss'
})
export class ConfirmationBox {
  message: string;
  constructor(
    public dialogRef: MatDialogRef<ConfirmationBox>,
    @Inject(MAT_DIALOG_DATA) public data: any,
  ) {
    this.message = data.message;
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
