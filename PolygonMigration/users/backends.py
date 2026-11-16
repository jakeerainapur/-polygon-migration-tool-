from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model
from django.db.models import Q

class EmailBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        UserModel = get_user_model()
        identifier = kwargs.get('email', username)
        if identifier is None or password is None:
            return None
        try:
            user = UserModel.objects.get(Q(email__iexact=identifier) | Q(username__iexact=identifier))
        except (UserModel.DoesNotExist, UserModel.MultipleObjectsReturned):
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None 