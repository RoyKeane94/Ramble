from urllib.parse import urlparse

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.contrib.auth.password_validation import validate_password

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


class SignupForm(forms.Form):
    email = forms.EmailField(
        label="Email",
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

    def clean_email(self):
        email = User.objects.normalize_email(self.cleaned_data["email"])
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def clean_password1(self):
        password = self.cleaned_data["password1"]
        validate_password(password)
        return password

    def clean(self):
        cleaned = super().clean()
        password1 = cleaned.get("password1")
        password2 = cleaned.get("password2")
        if password1 and password2 and password1 != password2:
            self.add_error("password2", "Passwords do not match.")
        return cleaned


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


class TakeReadyWebhookForm(forms.Form):
    """HTTPS routine webhook URL + Bearer key from Grok Bot."""

    url = forms.CharField(
        label="Webhook URL",
        max_length=500,
        widget=forms.URLInput(
            attrs={
                **FIELD_ATTRS,
                "placeholder": "https://… webhook URL",
                "autocomplete": "off",
                "spellcheck": "false",
            }
        ),
    )
    key = forms.CharField(
        label="Bearer key",
        max_length=200,
        widget=forms.PasswordInput(
            attrs={
                **FIELD_ATTRS,
                "placeholder": "Bearer key",
                "autocomplete": "off",
                "spellcheck": "false",
            },
            render_value=True,
        ),
    )

    def clean_url(self):
        url = (self.cleaned_data.get("url") or "").strip()
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise forms.ValidationError("Use an https webhook URL.")
        return url

    def clean_key(self):
        key = (self.cleaned_data.get("key") or "").strip()
        if not key:
            raise forms.ValidationError("Bearer key is required.")
        return key
