from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm, UserCreationForm

User = get_user_model()

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


class RegisterForm(UserCreationForm):
    email = forms.EmailField(
        widget=forms.EmailInput(
            attrs={
                **FIELD_ATTRS,
                "placeholder": "Email",
                "autofocus": True,
                "autocomplete": "email",
            }
        ),
    )
    password1 = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(
            attrs={
                **FIELD_ATTRS,
                "placeholder": "Password",
                "autocomplete": "new-password",
            }
        ),
    )
    password2 = forms.CharField(
        label="Confirm password",
        widget=forms.PasswordInput(
            attrs={
                **FIELD_ATTRS,
                "placeholder": "Confirm password",
                "autocomplete": "new-password",
            }
        ),
    )

    class Meta:
        model = User
        fields = ("email",)


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
