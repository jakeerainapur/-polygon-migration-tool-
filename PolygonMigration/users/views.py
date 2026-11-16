from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.urls import reverse

# Create your views here.
def login_view(request):
    next_url = request.GET.get('next') or request.POST.get('next') or 'problems:index'
    if request.user.is_authenticated:
        if request.user.is_staff:
            return redirect(next_url)
        logout(request)
    if request.method == 'POST':
        email = (request.POST.get('email') or '').strip()
        password = request.POST.get('password')
        user = authenticate(request, username=email, email=email, password=password)
        if user is not None:
            if user.is_staff:
                login(request, user)
                return redirect(next_url)
            else:
                messages.error(request, 'You do not have staff access.')
        else:
            messages.error(request, 'Invalid email or password.')
    return render(request, 'users/login.html')

def logout_view(request):
    logout(request)
    return redirect('login')
