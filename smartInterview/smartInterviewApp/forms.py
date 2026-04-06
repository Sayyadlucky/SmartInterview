from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.models import User
import imghdr
import zipfile

from smartInterviewApp.models import UserProfile


class LoginForm(AuthenticationForm):
    username = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'floating-input peer',
            'placeholder': ' ',
            'id': 'email',
            'autocomplete': 'email'
        })
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'floating-input peer',
            'placeholder': ' ',
            'id': 'password',
            'autocomplete': 'current-password'
        })
    )


def validate_resume_upload(resume):
    name = (resume.name or '').lower()
    allowed_extensions = ('.pdf', '.docx')
    if not name.endswith(allowed_extensions):
        raise forms.ValidationError('Upload a PDF or DOCX resume only.')

    header = resume.read(8)
    resume.seek(0)

    if name.endswith('.pdf'):
        if not header.startswith(b'%PDF'):
            raise forms.ValidationError('The uploaded PDF file is invalid or corrupted.')

    if name.endswith('.docx'):
        if not zipfile.is_zipfile(resume):
            resume.seek(0)
            raise forms.ValidationError('The uploaded DOCX file is invalid or corrupted.')
        resume.seek(0)
        try:
            with zipfile.ZipFile(resume) as archive:
                names = set(archive.namelist())
                if 'word/document.xml' not in names:
                    raise forms.ValidationError('The uploaded DOCX file is missing required Word document data.')
        finally:
            resume.seek(0)

    max_size = 5 * 1024 * 1024
    if resume.size > max_size:
        raise forms.ValidationError('Resume must be 5 MB or smaller.')
    return resume


def validate_profile_picture_upload(profile_picture):
    name = (profile_picture.name or '').lower()
    allowed_extensions = ('.png', '.jpg', '.jpeg', '.webp')
    if not name.endswith(allowed_extensions):
        raise forms.ValidationError('Upload a PNG, JPG, JPEG, or WEBP profile photo only.')

    header = profile_picture.read(512)
    profile_picture.seek(0)
    image_type = imghdr.what(None, h=header)
    if image_type not in {'png', 'jpeg', 'webp'}:
        raise forms.ValidationError('The uploaded profile photo is invalid or unsupported.')

    max_size = 3 * 1024 * 1024
    if profile_picture.size > max_size:
        raise forms.ValidationError('Profile photo must be 3 MB or smaller.')
    return profile_picture


class CandidateLoginForm(AuthenticationForm):
    username = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'portal-input',
            'placeholder': 'Email address',
            'autocomplete': 'username',
        })
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'portal-input',
            'placeholder': 'Password',
            'autocomplete': 'current-password',
        })
    )


class CandidateProfileUpdateForm(forms.Form):
    first_name = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={'class': 'portal-input', 'placeholder': 'First name'}),
    )
    last_name = forms.CharField(
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={'class': 'portal-input', 'placeholder': 'Last name'}),
    )
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={'class': 'portal-input', 'placeholder': 'Email address'}),
    )
    phone = forms.CharField(
        max_length=20,
        widget=forms.TextInput(attrs={'class': 'portal-input', 'placeholder': 'Mobile number'}),
    )
    gender = forms.ChoiceField(
        choices=UserProfile.Gender_CHOICES,
        widget=forms.Select(attrs={'class': 'portal-input'}),
    )
    profile_picture = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(attrs={
            'class': 'portal-input portal-input--file',
            'accept': 'image/png,image/jpeg,image/jpg,image/webp',
        }),
    )
    resume = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(attrs={
            'class': 'portal-input portal-input--file',
            'accept': '.pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        }),
    )

    def __init__(self, *args, user: User | None = None, profile: UserProfile | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.profile = profile
        if user and not self.is_bound:
            self.initial['first_name'] = user.first_name
            self.initial['last_name'] = user.last_name
            self.initial['email'] = user.email
        if profile and not self.is_bound:
            self.initial['phone'] = profile.phone or ''
            self.initial['gender'] = profile.gender or 'other'

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip().lower()
        if User.objects.exclude(id=getattr(self.user, 'id', None)).filter(email=email).exists():
            raise forms.ValidationError('This email is already associated with another account.')
        return email

    def clean_phone(self):
        phone = ''.join(ch for ch in (self.cleaned_data.get('phone') or '') if ch.isdigit())
        if len(phone) < 10:
            raise forms.ValidationError('Enter a valid mobile number.')
        return phone

    def clean_profile_picture(self):
        profile_picture = self.cleaned_data.get('profile_picture')
        if not profile_picture:
            return profile_picture
        return validate_profile_picture_upload(profile_picture)

    def clean_resume(self):
        resume = self.cleaned_data.get('resume')
        if not resume:
            return resume
        return validate_resume_upload(resume)


class CandidateSignupForm(forms.Form):
    first_name = forms.CharField(
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'signup-input',
            'autocomplete': 'given-name',
            'placeholder': 'First name',
        }),
    )
    last_name = forms.CharField(
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'signup-input',
            'autocomplete': 'family-name',
            'placeholder': 'Last name',
        }),
    )
    email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={
            'class': 'signup-input',
            'autocomplete': 'email',
            'autocapitalize': 'off',
            'inputmode': 'email',
            'placeholder': 'Email address',
            'spellcheck': 'false',
        }),
    )
    phone = forms.CharField(
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'signup-input',
            'autocomplete': 'tel',
            'inputmode': 'numeric',
            'placeholder': 'Mobile number',
        }),
    )
    gender = forms.ChoiceField(
        choices=(('', 'Select gender'),) + UserProfile.Gender_CHOICES,
        required=False,
        widget=forms.Select(attrs={
            'class': 'signup-input',
        }),
    )
    password = forms.CharField(
        min_length=8,
        widget=forms.PasswordInput(attrs={
            'class': 'signup-input',
            'autocomplete': 'new-password',
            'placeholder': 'Create password',
            'spellcheck': 'false',
        }),
        help_text='Use at least 8 characters.',
    )
    confirm_password = forms.CharField(
        min_length=8,
        widget=forms.PasswordInput(attrs={
            'class': 'signup-input',
            'autocomplete': 'new-password',
            'placeholder': 'Confirm password',
            'spellcheck': 'false',
        }),
    )
    profile_picture = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(attrs={
            'class': 'signup-input signup-input--file',
            'accept': 'image/png,image/jpeg,image/jpg,image/webp',
        })
    )
    resume = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(attrs={
            'class': 'signup-input signup-input--file',
            'accept': '.pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        })
    )

    def __init__(self, *args, user=None, manual_mode=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.manual_mode = manual_mode

        if manual_mode:
            self.fields['first_name'].required = True
            self.fields['email'].required = True
            self.fields['phone'].required = True
            self.fields['gender'].required = True

    def clean_password(self):
        password = self.cleaned_data['password']
        validate_password(password, self.user)
        return password

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip().lower()
        if not email:
            return email
        if User.objects.exclude(id=getattr(self.user, 'id', None)).filter(email__iexact=email).exists():
            raise forms.ValidationError('This email is already associated with another account.')
        return email

    def clean_phone(self):
        phone = ''.join(ch for ch in (self.cleaned_data.get('phone') or '') if ch.isdigit())
        if not phone:
            return phone
        if len(phone) < 10:
            raise forms.ValidationError('Enter a valid mobile number.')
        return phone

    def clean_resume(self):
        resume = self.cleaned_data.get('resume')
        if not resume:
            return resume
        return validate_resume_upload(resume)

    def clean_profile_picture(self):
        profile_picture = self.cleaned_data.get('profile_picture')
        if not profile_picture:
            return profile_picture
        return validate_profile_picture_upload(profile_picture)

    def clean(self):
        cleaned_data = super().clean()
        if self.manual_mode:
            if not (cleaned_data.get('first_name') or '').strip():
                self.add_error('first_name', 'First name is required.')
            if not cleaned_data.get('email'):
                self.add_error('email', 'Email is required.')
            if not cleaned_data.get('phone'):
                self.add_error('phone', 'Mobile number is required.')
            if not cleaned_data.get('gender'):
                self.add_error('gender', 'Gender is required.')
        password = cleaned_data.get('password')
        confirm_password = cleaned_data.get('confirm_password')
        if password and confirm_password and password != confirm_password:
            self.add_error('confirm_password', 'Passwords do not match.')
        return cleaned_data
