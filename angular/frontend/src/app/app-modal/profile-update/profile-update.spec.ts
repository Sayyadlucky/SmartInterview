import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ProfileUpdate } from './profile-update';

describe('ProfileUpdate', () => {
  let component: ProfileUpdate;
  let fixture: ComponentFixture<ProfileUpdate>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ProfileUpdate]
    })
    .compileComponents();

    fixture = TestBed.createComponent(ProfileUpdate);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
