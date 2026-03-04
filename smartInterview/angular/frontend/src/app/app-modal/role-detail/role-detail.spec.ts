import { ComponentFixture, TestBed } from '@angular/core/testing';

import { RoleDetail } from './role-detail';

describe('RoleDetail', () => {
  let component: RoleDetail;
  let fixture: ComponentFixture<RoleDetail>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [RoleDetail]
    })
    .compileComponents();

    fixture = TestBed.createComponent(RoleDetail);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
