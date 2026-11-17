import re
from urllib.parse import urlparse

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.contrib.auth.password_validation import validate_password
from django.utils.text import slugify

from .models import CrmContact

User = get_user_model()

FIELD_ATTRS = {
    "class": "field auth-input",
}

CRM_FIELD_ATTRS = {
    "class": "field crm-input",
}


def _slug_seed(*parts):
    for part in parts:
        slug = slugify((part or "").strip())[:64]
        if slug:
            return slug
    return ""


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


class CrmContactForm(forms.ModelForm):
    class Meta:
        model = CrmContact
        fields = (
            "first_name",
            "business_name",
            "contact_type",
            "region",
            "country",
            "website",
            "email",
            "phone",
            "email_source",
            "source",
            "personalisation_detail",
            "notes",
            "stage",
            "last_contacted_on",
            "last_contacted_channel",
            "next_follow_up_on",
            "do_not_contact",
            "response",
            "response_reason",
            "tracking_slug",
        )
        labels = {
            "contact_type": "Type",
            "personalisation_detail": "Personalisation detail",
            "notes": "Notes",
            "source": "Source",
            "stage": "Stage",
            "last_contacted_on": "Last contacted",
            "last_contacted_channel": "Last contacted channel",
            "next_follow_up_on": "Next follow-up",
            "do_not_contact": "Do not contact",
            "response": "Response",
            "response_reason": "Reason",
            "tracking_slug": "Tracking slug",
        }
        widgets = {
            "first_name": forms.TextInput(attrs={**CRM_FIELD_ATTRS, "placeholder": "First name"}),
            "business_name": forms.TextInput(attrs={**CRM_FIELD_ATTRS, "placeholder": "Business name"}),
            "contact_type": forms.Select(attrs={**CRM_FIELD_ATTRS}),
            "region": forms.TextInput(attrs={**CRM_FIELD_ATTRS, "placeholder": "Region"}),
            "country": forms.TextInput(attrs={**CRM_FIELD_ATTRS, "placeholder": "Country"}),
            "website": forms.URLInput(attrs={**CRM_FIELD_ATTRS, "placeholder": "https://"}),
            "email": forms.EmailInput(attrs={**CRM_FIELD_ATTRS, "placeholder": "Email"}),
            "phone": forms.TextInput(attrs={**CRM_FIELD_ATTRS, "placeholder": "Phone"}),
            "email_source": forms.TextInput(attrs={**CRM_FIELD_ATTRS, "placeholder": "Email source"}),
            "source": forms.TextInput(
                attrs={**CRM_FIELD_ATTRS, "placeholder": "e.g. The Celebrant Directory"}
            ),
            "personalisation_detail": forms.Textarea(
                attrs={
                    **CRM_FIELD_ATTRS,
                    "placeholder": "Personalisation detail",
                    "rows": 2,
                }
            ),
            "notes": forms.Textarea(
                attrs={
                    **CRM_FIELD_ATTRS,
                    "placeholder": "Call outcomes and anything they said",
                    "rows": 3,
                }
            ),
            "stage": forms.Select(attrs={**CRM_FIELD_ATTRS}),
            "last_contacted_on": forms.DateInput(
                attrs={**CRM_FIELD_ATTRS, "type": "date"},
                format="%Y-%m-%d",
            ),
            "last_contacted_channel": forms.Select(attrs={**CRM_FIELD_ATTRS}),
            "next_follow_up_on": forms.DateInput(
                attrs={**CRM_FIELD_ATTRS, "type": "date"},
                format="%Y-%m-%d",
            ),
            "do_not_contact": forms.CheckboxInput(attrs={"class": "crm-checkbox"}),
            "response": forms.Select(attrs={**CRM_FIELD_ATTRS}),
            "response_reason": forms.Textarea(
                attrs={
                    **CRM_FIELD_ATTRS,
                    "placeholder": "Reason",
                    "rows": 2,
                }
            ),
            "tracking_slug": forms.TextInput(
                attrs={
                    **CRM_FIELD_ATTRS,
                    "placeholder": "Tracking slug (auto if blank)",
                    "spellcheck": "false",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["tracking_slug"].required = False
        self.fields["website"].required = False
        self.fields["phone"].required = False
        self.fields["contact_type"].required = False
        self.fields["contact_type"].choices = [
            ("", "—"),
            *CrmContact.ContactType.choices,
        ]
        self.fields["source"].required = False
        self.fields["notes"].required = False
        self.fields["stage"].required = True
        self.fields["last_contacted_on"].required = False
        self.fields["last_contacted_on"].input_formats = ["%Y-%m-%d"]
        self.fields["last_contacted_channel"].required = False
        self.fields["last_contacted_channel"].choices = [
            ("", "—"),
            *CrmContact.ContactChannel.choices,
        ]
        self.fields["next_follow_up_on"].required = False
        self.fields["next_follow_up_on"].input_formats = ["%Y-%m-%d"]
        self.fields["do_not_contact"].required = False
        self.fields["response"].required = False
        self.fields["response"].choices = [
            ("", "—"),
            *CrmContact.Response.choices,
        ]
        self.fields["response_reason"].required = False

    def clean_website(self):
        website = (self.cleaned_data.get("website") or "").strip()
        if not website:
            return ""
        if "://" not in website:
            website = f"https://{website}"
        return website

    def clean_tracking_slug(self):
        slug = (self.cleaned_data.get("tracking_slug") or "").strip().lower()
        if not slug:
            slug = _slug_seed(
                self.data.get("business_name", ""),
                self.data.get("first_name", ""),
                self.data.get("email", ""),
            )
        slug = re.sub(r"[^a-z0-9_-]+", "-", slug).strip("-")[:64]
        if not slug:
            raise forms.ValidationError("Add a tracking slug, or a name/email to derive one.")
        qs = CrmContact.objects.filter(tracking_slug=slug)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("That tracking slug is already in use.")
        return slug


class CrmOutreachEmailForm(forms.Form):
    outreach_email_subject = forms.CharField(
        label="Subject",
        max_length=255,
        required=False,
        widget=forms.TextInput(
            attrs={
                **CRM_FIELD_ATTRS,
                "placeholder": "Subject",
            }
        ),
    )
    outreach_email_body = forms.CharField(
        label="Email",
        required=False,
        widget=forms.Textarea(
            attrs={
                **CRM_FIELD_ATTRS,
                "placeholder": "Draft outreach email",
                "rows": 8,
            }
        ),
    )

    def clean(self):
        cleaned = super().clean()
        subject = (cleaned.get("outreach_email_subject") or "").strip()
        body = (cleaned.get("outreach_email_body") or "").strip()
        cleaned["outreach_email_subject"] = subject
        cleaned["outreach_email_body"] = body
        if not subject and not body:
            raise forms.ValidationError("Add a subject or email body.")
        return cleaned
