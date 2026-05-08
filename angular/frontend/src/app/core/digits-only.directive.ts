import { Directive, ElementRef, HostListener, inject } from '@angular/core';
import { NgControl } from '@angular/forms';

@Directive({
  selector: 'input[appDigitsOnly]',
  standalone: true,
})
export class DigitsOnlyDirective {
  private readonly elementRef = inject(ElementRef<HTMLInputElement>);
  private readonly ngControl = inject(NgControl, { optional: true });

  @HostListener('input')
  onInput(): void {
    this.applySanitizedValue();
  }

  @HostListener('paste', ['$event'])
  onPaste(event: ClipboardEvent): void {
    const pasted = event.clipboardData?.getData('text') || '';
    if (!/\D/.test(pasted)) {
      return;
    }
    event.preventDefault();
    this.setValue(this.toDigits(pasted));
  }

  @HostListener('drop', ['$event'])
  onDrop(event: DragEvent): void {
    event.preventDefault();
  }

  @HostListener('keydown', ['$event'])
  onKeyDown(event: KeyboardEvent): void {
    const allowedKeys = new Set([
      'Backspace',
      'Delete',
      'Tab',
      'Escape',
      'Enter',
      'ArrowLeft',
      'ArrowRight',
      'ArrowUp',
      'ArrowDown',
      'Home',
      'End',
    ]);

    if (allowedKeys.has(event.key) || event.metaKey || event.ctrlKey) {
      return;
    }

    if (!/^\d$/.test(event.key)) {
      event.preventDefault();
    }
  }

  private applySanitizedValue(): void {
    const current = this.elementRef.nativeElement.value;
    const sanitized = this.toDigits(current);
    if (current === sanitized) {
      return;
    }
    this.setValue(sanitized);
  }

  private setValue(value: string): void {
    const input = this.elementRef.nativeElement;
    input.value = value;
    this.ngControl?.control?.setValue(value, {
      emitEvent: false,
      emitModelToViewChange: false,
      emitViewToModelChange: false,
    });
    input.dispatchEvent(new Event('input', { bubbles: true }));
  }

  private toDigits(value: string): string {
    return (value || '').replace(/\D/g, '');
  }
}
