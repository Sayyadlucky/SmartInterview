import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ConfirmationBox } from './confirmation-box';

describe('ConfirmationBox', () => {
  let component: ConfirmationBox;
  let fixture: ComponentFixture<ConfirmationBox>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ConfirmationBox]
    })
    .compileComponents();

    fixture = TestBed.createComponent(ConfirmationBox);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
