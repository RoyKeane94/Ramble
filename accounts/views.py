from django.contrib.auth.decorators import login_required
from django.contrib.auth import update_session_auth_hash
from django.shortcuts import render

from django.contrib.auth import login
from django.contrib.auth.views import LoginView, LogoutView
from django.urls import reverse_lazy
from django.views.generic import CreateView

from notes.models import Note

from .forms import EmailAuthenticationForm, RegisterForm, StyledPasswordChangeForm


class RambleLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = EmailAuthenticationForm
    redirect_authenticated_user = True


class RegisterView(CreateView):
    form_class = RegisterForm
    template_name = "accounts/register.html"
    success_url = reverse_lazy("notes:list")

    def form_valid(self, form):
        response = super().form_valid(form)
        login(self.request, self.object, backend="django.contrib.auth.backends.ModelBackend")
        return response


class RambleLogoutView(LogoutView):
    next_page = reverse_lazy("login")


@login_required
def settings(request):
    password_form = StyledPasswordChangeForm(request.user)
    password_saved = False

    if request.method == "POST" and request.POST.get("intent") == "password":
        password_form = StyledPasswordChangeForm(request.user, request.POST)
        if password_form.is_valid():
            user = password_form.save()
            update_session_auth_hash(request, user)
            password_saved = True
            password_form = StyledPasswordChangeForm(request.user)

    notes = Note.objects.filter(user=request.user)
    latest = notes.order_by("-updated_at").first()
    return render(
        request,
        "accounts/settings.html",
        {
            "password_form": password_form,
            "password_saved": password_saved,
            "note_count": notes.count(),
            "last_synced": latest.updated_at if latest else None,
        },
    )
