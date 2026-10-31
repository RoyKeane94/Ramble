from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm

FIELD_ATTRS = {
    "class": "field auth-input",
}


class EmailAuthenticationForm(AuthenticationForm):
    username = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(
            attrs={
                **FIELD_ATTRS,
                "placeholder": "Email",
                "autofocus": True,
                "autocomplete": "username",
            }
        ),
    )
    password = forms.CharField(
        widget=forms.PasswordInput(
            attrs={
                **FIELD_ATTRS,
                "placeholder": "Password",
                "autocomplete": "current-password",
            }
        ),
    )


class StyledPasswordChangeForm(PasswordChangeForm):
    old_password = forms.CharField(
        widget=forms.PasswordInput(
            attrs={
                **FIELD_ATTRS,
                "placeholder": "Current password",
                "autocomplete": "current-password",
            }
        ),
    )
    new_password1 = forms.CharField(
        widget=forms.PasswordInput(
            attrs={
                **FIELD_ATTRS,
                "placeholder": "New password",
                "autocomplete": "new-password",
            }
        ),
    )
    new_password2 = forms.CharField(
        widget=forms.PasswordInput(
            attrs={
                **FIELD_ATTRS,
                "placeholder": "Confirm new password",
                "autocomplete": "new-password",
            }
        ),
    )
