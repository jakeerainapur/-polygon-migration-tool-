from django.test import TestCase, Client
from django.urls import reverse
from unittest.mock import patch, MagicMock
from users.models import User
from problems.models import Problem, ProblemTag, SampleTestCase, ProblemTestCase
from problems.polygon_api import PolygonAPI

class ProblemMigrationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.staff_user = User.objects.create_user(
            email='staff@example.com',
            password='StaffPassword123',
            username='staffuser',
            first_name='Staff',
            last_name='User',
            contact_number='1234567890',
            college='Tech',
            graduation_year=2024,
            gender='MALE',
            is_staff=True,
            is_active=True
        )
        self.client.force_login(self.staff_user)

    def test_problem_model_has_notes_and_genie_chat(self):
        problem = Problem.objects.create(
            polygon_id='1001',
            title='Sample Problem',
            slug='sample-problem',
            difficulty='easy',
            notes='<p>Special notes</p>',
            genie_chat=True
        )
        self.assertEqual(problem.notes, '<p>Special notes</p>')
        self.assertTrue(problem.genie_chat)
        queried = Problem.objects.get(polygon_id='1001')
        self.assertEqual(queried.title, 'Sample Problem')

    def test_duplicate_problem_titles_slug_disambiguation(self):
        """Test Q3 edge case: two problems with identical titles 'Two Sum' get unique slugs."""
        # Problem 1
        p1 = Problem.objects.create(
            polygon_id='2001',
            title='Two Sum',
            slug='two-sum',
            difficulty='easy'
        )
        
        # When problem 2 with the same title is migrated via view logic
        with patch.object(PolygonAPI, 'get_problem_info', return_value={'timeLimit': 1000, 'memoryLimit': 256, 'name': 'Two Sum'}), \
             patch.object(PolygonAPI, 'download_and_extract_package', return_value='<html><div class="title">Two Sum</div></html>'), \
             patch.object(PolygonAPI, 'get_all_test_cases', return_value=[]), \
             patch.object(PolygonAPI, '_make_request', return_value=[]):
            
            response = self.client.post(reverse('problems:index'), {
                'problem_id': '2002',
                'migrate_to_db': '1',
                'difficulty': 'medium',
            })
            self.assertEqual(response.status_code, 200)
            self.assertIn('db_success', response.context)
            
            p2 = Problem.objects.get(polygon_id='2002')
            self.assertNotEqual(p1.slug, p2.slug)
            self.assertEqual(p2.slug, 'two-sum-1')

    def test_test_case_re_migration_deletes_stale_records(self):
        """Test Q2 edge case: reducing test cases on Polygon deletes obsolete test cases on re-migration."""
        problem = Problem.objects.create(
            polygon_id='3001',
            title='Test Reduction',
            slug='test-reduction',
            difficulty='medium'
        )
        
        # Initially migrate 20 test cases
        for i in range(1, 21):
            ProblemTestCase.objects.create(
                problem=problem,
                input=f"input_{i}",
                output=f"output_{i}",
                order=i,
                is_sample=(i <= 3)
            )
        self.assertEqual(ProblemTestCase.objects.filter(problem=problem).count(), 20)
        
        # Now 12 test cases remain on Polygon
        reduced_test_cases = [
            {'index': i, 'input': f"new_input_{i}", 'output': f"new_output_{i}", 'is_sample': (i <= 2), 'description': ''}
            for i in range(1, 13)
        ]
        
        with patch.object(PolygonAPI, 'get_problem_info', return_value={'timeLimit': 1000, 'memoryLimit': 256, 'name': 'Test Reduction'}), \
             patch.object(PolygonAPI, 'download_and_extract_package', return_value='<html><div class="title">Test Reduction</div></html>'), \
             patch.object(PolygonAPI, 'get_all_test_cases', return_value=reduced_test_cases), \
             patch.object(PolygonAPI, 'get_test_cases_from_redis', return_value=reduced_test_cases), \
             patch.object(PolygonAPI, '_make_request', return_value=[]):
            
            response = self.client.post(reverse('problems:index'), {
                'problem_id': '3001',
                'migrate_test_cases_to_db': '1',
            })
            self.assertEqual(response.status_code, 200)
            
            # Verify count is now 12, not 20
            self.assertEqual(ProblemTestCase.objects.filter(problem=problem).count(), 12)

    def test_test_case_full_content_preservation(self):
        """Test Q4 edge case: test cases larger than 260 bytes are not truncated."""
        problem = Problem.objects.create(
            polygon_id='4001',
            title='Large Test Case Problem',
            slug='large-test-case-problem',
            difficulty='hard'
        )
        
        large_input = "1 " * 500  # 1000 characters
        large_output = "2 " * 500  # 1000 characters
        large_test_cases = [
            {'index': 1, 'input': large_input, 'output': large_output, 'is_sample': False, 'description': 'large case'}
        ]
        
        with patch.object(PolygonAPI, 'get_problem_info', return_value={'timeLimit': 1000, 'memoryLimit': 256, 'name': 'Large Test'}), \
             patch.object(PolygonAPI, 'download_and_extract_package', return_value='<html><div class="title">Large Test</div></html>'), \
             patch.object(PolygonAPI, 'get_all_test_cases', return_value=large_test_cases), \
             patch.object(PolygonAPI, 'get_test_cases_from_redis', return_value=large_test_cases), \
             patch.object(PolygonAPI, '_make_request', return_value=[]):
            
            response = self.client.post(reverse('problems:index'), {
                'problem_id': '4001',
                'migrate_test_cases_to_db': '1',
            })
            self.assertEqual(response.status_code, 200)
            
            tc = ProblemTestCase.objects.get(problem=problem, order=1)
            self.assertEqual(len(tc.input), len(large_input))
            self.assertEqual(tc.input, large_input)
            self.assertEqual(len(tc.output), len(large_output))
            self.assertEqual(tc.output, large_output)

    def test_zero_samples_migration(self):
        """Test Q1 edge case: Problem with 0 samples and 15 regular test cases."""
        tests = [
            {'index': i, 'input': f"in_{i}", 'output': f"out_{i}", 'is_sample': False, 'description': ''}
            for i in range(1, 16)
        ]
        with patch.object(PolygonAPI, 'get_problem_info', return_value={'timeLimit': 1000, 'memoryLimit': 256, 'name': 'Zero Sample Problem'}), \
             patch.object(PolygonAPI, 'download_and_extract_package', return_value='<html><div class="title">Zero Sample Problem</div></html>'), \
             patch.object(PolygonAPI, 'get_all_test_cases', return_value=tests), \
             patch.object(PolygonAPI, 'get_test_cases_from_redis', return_value=tests), \
             patch.object(PolygonAPI, '_make_request', return_value=[]):
            
            response = self.client.post(reverse('problems:index'), {
                'problem_id': '5001',
                'migrate_to_db': '1',
                'difficulty': 'easy',
            })
            self.assertEqual(response.status_code, 200)
            
            p = Problem.objects.get(polygon_id='5001')
            self.assertEqual(p.sample_test_cases.count(), 0)

    def test_polygon_api_delete_azure_blob_does_not_raise_attribute_error(self):
        """Test that delete_azure_blob exists on PolygonAPI and runs safely."""
        api = PolygonAPI()
        # Should not raise AttributeError
        api.delete_azure_blob(123)

    def test_non_numeric_problem_id_returns_friendly_error(self):
        """Test entering a non-numeric string (e.g. username) shows a clean validation error."""
        response = self.client.post(reverse('problems:index'), {
            'problem_id': 'mallikarjun@123'
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('error', response.context)
        self.assertIn('not a valid Polygon Problem ID', response.context['error'])
