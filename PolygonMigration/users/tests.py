from django.test import TestCase, Client
from django.urls import reverse
from users.models import User

class UserAuthTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.staff_user = User.objects.create_user(
            email='staff@example.com',
            password='StaffPassword123',
            username='staffuser',
            first_name='Staff',
            last_name='Member',
            contact_number='1234567890',
            college='Engineering College',
            graduation_year=2024,
            gender='MALE',
            is_staff=True,
            is_active=True
        )
        self.regular_user = User.objects.create_user(
            email='student@example.com',
            password='StudentPassword123',
            username='studentuser',
            first_name='Student',
            last_name='User',
            contact_number='0987654321',
            college='Arts College',
            graduation_year=2025,
            gender='FEMALE',
            is_staff=False,
            is_active=True
        )

    def test_staff_login_successful(self):
        response = self.client.post(reverse('login'), {
            'email': 'staff@example.com',
            'password': 'StaffPassword123'
        })
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('problems:index'))

    def test_staff_login_case_insensitive(self):
        response = self.client.post(reverse('login'), {
            'email': 'STAFF@example.com',
            'password': 'StaffPassword123'
        })
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('problems:index'))

    def test_regular_user_cannot_access_staff_app(self):
        response = self.client.post(reverse('login'), {
            'email': 'student@example.com',
            'password': 'StudentPassword123'
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'You do not have staff access.')

    def test_authenticated_staff_visiting_login_redirects_to_index(self):
        self.client.force_login(self.staff_user)
        response = self.client.get(reverse('login'))
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('problems:index'))

    def test_logout_redirects_to_login(self):
        self.client.force_login(self.staff_user)
        response = self.client.post(reverse('logout'))
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('login'))
