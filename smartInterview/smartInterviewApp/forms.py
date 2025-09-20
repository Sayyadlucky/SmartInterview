from django import forms
from django.contrib.auth.forms import AuthenticationForm

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
