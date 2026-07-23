from .models import UserProfile

def global_user_profile(request):
    if request.user.is_authenticated:
        try:
            return {'userProfile': request.user.profile}
        except UserProfile.DoesNotExist:
            return {}
    return {}