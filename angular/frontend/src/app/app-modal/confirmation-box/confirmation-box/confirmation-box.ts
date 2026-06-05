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
  subtitle: string;
  confirmText: string;
  cancelText: string;
  mode: 'confirm' | 'export';
  selectedFormat: 'excel' | 'pdf' | 'word';
  exportSummary: any;
  actionTitle: string;
  entityLabel: string;
  entityName: string;
  entityId: string;
  warningText: string;
  isDanger: boolean;
  isSuccess: boolean;
  iconClass: string;
  detailIconClass: string;

  constructor(
    public dialogRef: MatDialogRef<ConfirmationBox>,
    @Inject(MAT_DIALOG_DATA) public data: any,
  ) {
    this.mode = data?.mode === 'export' ? 'export' : 'confirm';
    this.title = data?.title || (this.mode === 'export' ? 'Export Candidate Data' : 'Confirm Action');
    this.subtitle = data?.subtitle || data?.message || 'Please review the details below before proceeding.';
    this.confirmText = data?.confirmText || 'Confirm';
    this.cancelText = data?.cancelText || 'Cancel';
    this.selectedFormat = data?.defaultFormat || 'excel';
    this.exportSummary = data?.exportSummary || null;
    this.actionTitle = data?.actionTitle || data?.action || data?.actionLabel || data?.title || data?.message || this.confirmText || 'Confirm';
    this.entityLabel = data?.entityLabel || data?.recordLabel || data?.itemLabel || '';
    this.entityName = data?.entityName || data?.candidateName || data?.roleName || data?.itemName || '';
    this.entityId = (data?.entityId ?? data?.candidateId ?? data?.roleId ?? data?.itemId ?? '').toString();
    this.isDanger = Boolean(data?.danger || data?.destructive || data?.isDanger);
    this.isSuccess = Boolean(data?.success || data?.isSuccess);
    this.warningText = data?.warning || (
      this.mode === 'export'
        ? 'The export will include candidate data visible to your current workspace permissions.'
        : 'This action will update the selected record and may notify relevant stakeholders.'
    );
    this.iconClass = this.mode === 'export'
      ? 'ph ph-files'
      : this.isDanger
        ? 'ph ph-warning-octagon'
        : this.isSuccess
          ? 'ph ph-check-circle'
          : 'ph ph-question';
    this.detailIconClass = this.mode === 'export' ? 'ph ph-download-simple' : 'ph ph-file-text';
  }

  get confirmButtonText(): string {
    return this.mode === 'export' ? `Export as ${this.formatLabel(this.selectedFormat)}` : this.confirmText;
  }

  get selectedFormatLabel(): string {
    return this.formatLabel(this.selectedFormat);
  }

  selectFormat(format: 'excel' | 'pdf' | 'word'): void {
    this.selectedFormat = format;
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

  private formatLabel(format: 'excel' | 'pdf' | 'word'): string {
    if (format === 'pdf') return 'PDF';
    if (format === 'word') return 'Word';
    return 'Excel';
  }
}
