"""
Tests for the HealthScribe Django API.

These tests cover:
  - User registration and authentication
  - Medical record creation, retrieval, and saving
  - Allergy cross-referencing and discovery
  - Edge cases (empty data, duplicate users, invalid records)

We use Django's built-in TestCase which gives us a fresh in-memory
SQLite database for each test — no real database needed.
"""
from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from rest_framework import status
from .models import MedicalRecord, HealthEntity, UserProfile
from unittest.mock import patch


class AuthenticationTests(TestCase):
    """
    Tests for user registration and login.
    We want to make sure:
      - New users can sign up and get JWT tokens back
      - Duplicate usernames/emails are rejected
      - Login works and returns valid tokens
      - Short passwords are rejected
    """

    def setUp(self):
        """
        Runs before each test. We create a fresh API client
        so every test starts with a clean slate.
        """
        self.client = APIClient()

    def test_register_new_user_successfully(self):
        """A new user should be created and get JWT tokens back."""
        response = self.client.post('/api/auth/register/', {
            'username': 'testpatient',
            'email': 'test@example.com',
            'password': 'securepassword123'
        })

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('tokens', response.data)
        self.assertIn('access', response.data['tokens'])
        self.assertIn('refresh', response.data['tokens'])
        self.assertEqual(response.data['user']['username'], 'testpatient')

        # Also check that the user actually exists in the database
        self.assertTrue(User.objects.filter(username='testpatient').exists())

    def test_register_creates_user_profile(self):
        """Registration should automatically create a UserProfile for the new user."""
        self.client.post('/api/auth/register/', {
            'username': 'profiletest',
            'email': 'profile@example.com',
            'password': 'securepassword123'
        })

        user = User.objects.get(username='profiletest')
        self.assertTrue(UserProfile.objects.filter(user=user).exists())

    def test_register_duplicate_username_fails(self):
        """Trying to register with the same username should fail with 400."""
        User.objects.create_user(username='taken', email='first@example.com', password='password123')

        response = self.client.post('/api/auth/register/', {
            'username': 'taken',
            'email': 'second@example.com',
            'password': 'password123'
        })

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_duplicate_email_fails(self):
        """Trying to register with an already used email should fail."""
        User.objects.create_user(username='user1', email='same@example.com', password='password123')

        response = self.client.post('/api/auth/register/', {
            'username': 'user2',
            'email': 'same@example.com',
            'password': 'password123'
        })

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_short_password_fails(self):
        """Passwords shorter than 6 characters should be rejected by the serializer."""
        response = self.client.post('/api/auth/register/', {
            'username': 'shortpw',
            'email': 'short@example.com',
            'password': '123'
        })

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_missing_fields_fails(self):
        """Missing required fields should be rejected."""
        response = self.client.post('/api/auth/register/', {
            'username': 'nopass'
        })

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_login_with_valid_credentials(self):
        """A registered user should be able to log in and get tokens."""
        User.objects.create_user(username='logintest', email='login@example.com', password='password123')

        response = self.client.post('/api/auth/login/', {
            'username': 'logintest',
            'password': 'password123'
        })

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)

    def test_login_with_wrong_password_fails(self):
        """Wrong password should not return tokens."""
        User.objects.create_user(username='logintest2', email='login2@example.com', password='password123')

        response = self.client.post('/api/auth/login/', {
            'username': 'logintest2',
            'password': 'wrongpassword'
        })

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class ProfileTests(TestCase):
    """
    Tests for the user profile endpoint.
    This is a protected endpoint — only authenticated users can access it.
    """

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='profileuser',
            email='profile@example.com',
            password='password123'
        )
        # Create a profile with known allergies
        UserProfile.objects.create(user=self.user, known_allergies="Penicillin,Aspirin")

        # Log in to get a JWT token
        login_response = self.client.post('/api/auth/login/', {
            'username': 'profileuser',
            'password': 'password123'
        })
        self.token = login_response.data['access']
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token}')

    def test_get_profile_returns_user_data(self):
        """Authenticated user should see their profile info."""
        response = self.client.get('/api/auth/profile/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['username'], 'profileuser')
        self.assertEqual(response.data['email'], 'profile@example.com')
        self.assertEqual(response.data['known_allergies'], 'Penicillin,Aspirin')

    def test_profile_requires_authentication(self):
        """Without a token, the profile endpoint should return 401."""
        unauthenticated_client = APIClient()
        response = unauthenticated_client.get('/api/auth/profile/')

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class SaveRecordTests(TestCase):
    """
    Tests for saving medical records.
    This is the core business logic — we test:
      - Creating new records with symptoms, medicines, vitals
      - The allergy warning system
      - New allergy discovery
      - Input validation (missing data, bad record IDs)
    """

    def setUp(self):
        """Create a test user and authenticate them."""
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='recorduser',
            email='record@example.com',
            password='password123'
        )
        UserProfile.objects.create(user=self.user, known_allergies="Penicillin")

        login_response = self.client.post('/api/auth/login/', {
            'username': 'recorduser',
            'password': 'password123'
        })
        self.token = login_response.data['access']
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token}')

    @patch('api.views.requests.post')
    def test_save_record_with_full_data(self, mock_embed_post):
        """Saving a record with symptoms, medicines, and vitals should create all entities."""
        mock_embed_post.return_value.status_code = 200

        response = self.client.post('/api/save_record/', {
            'verified_data': {
                'symptoms': ['Headache', 'Fever'],
                'medicines': [
                    {'name': 'Paracetamol', 'dosage': '500mg', 'reason': 'Headache'},
                    {'name': 'Ibuprofen', 'dosage': '400mg', 'reason': 'Fever'}
                ],
                'vitals': {'bp': '120/80', 'pulse': '72'},
                'allergies': []
            }
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['message'], 'Data saved successfully')

        # Verify entities were created in the database
        record = MedicalRecord.objects.filter(user=self.user).first()
        self.assertIsNotNone(record)
        self.assertEqual(record.category, 'Consultation')  # Because symptoms exist

        symptoms = HealthEntity.objects.filter(record=record, type='SYMPTOM')
        self.assertEqual(symptoms.count(), 2)

        medicines = HealthEntity.objects.filter(record=record, type='MEDICINE')
        self.assertEqual(medicines.count(), 2)

        vitals = HealthEntity.objects.filter(record=record, type='VITAL')
        self.assertEqual(vitals.count(), 2)

    @patch('api.views.requests.post')
    def test_save_record_no_symptoms_is_general_checkup(self, mock_embed_post):
        """A record with no symptoms should be categorized as 'General Checkup'."""
        mock_embed_post.return_value.status_code = 200

        self.client.post('/api/save_record/', {
            'verified_data': {
                'symptoms': [],
                'medicines': [],
                'vitals': {'bp': '120/80'},
                'allergies': []
            }
        }, format='json')

        record = MedicalRecord.objects.filter(user=self.user).first()
        self.assertEqual(record.category, 'General Checkup')

    @patch('api.views.requests.post')
    def test_allergy_warning_is_triggered(self, mock_embed_post):
        """If the user is allergic to Penicillin and a medicine contains it, we should get a warning."""
        mock_embed_post.return_value.status_code = 200

        response = self.client.post('/api/save_record/', {
            'verified_data': {
                'symptoms': ['Infection'],
                'medicines': [
                    {'name': 'Penicillin V', 'dosage': '250mg', 'reason': 'Infection'}
                ],
                'vitals': {},
                'allergies': []
            }
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # The response should contain a warning about the allergy
        warnings = response.data.get('warnings', [])
        self.assertTrue(len(warnings) > 0)
        self.assertIn('allergic', warnings[0].lower())

    @patch('api.views.requests.post')
    def test_no_allergy_warning_for_safe_medicine(self, mock_embed_post):
        """A medicine that doesn't match any known allergies should not trigger warnings."""
        mock_embed_post.return_value.status_code = 200

        response = self.client.post('/api/save_record/', {
            'verified_data': {
                'symptoms': ['Fever'],
                'medicines': [
                    {'name': 'Paracetamol', 'dosage': '500mg', 'reason': 'Fever'}
                ],
                'vitals': {},
                'allergies': []
            }
        }, format='json')

        warnings = response.data.get('warnings', [])
        self.assertEqual(len(warnings), 0)

    @patch('api.views.requests.post')
    def test_new_allergy_is_saved_to_profile(self, mock_embed_post):
        """When AI discovers a new allergy, it should be added to the user profile."""
        mock_embed_post.return_value.status_code = 200

        self.client.post('/api/save_record/', {
            'verified_data': {
                'symptoms': [],
                'medicines': [],
                'vitals': {},
                'allergies': ['Sulfa', 'Latex']
            }
        }, format='json')

        profile = UserProfile.objects.get(user=self.user)
        # Original was "Penicillin", now should include the new ones
        self.assertIn('Sulfa', profile.known_allergies)
        self.assertIn('Latex', profile.known_allergies)
        # Original allergy should still be there
        self.assertIn('Penicillin', profile.known_allergies)

    @patch('api.views.requests.post')
    def test_duplicate_allergy_not_added_again(self, mock_embed_post):
        """An allergy already in the profile should not be duplicated."""
        mock_embed_post.return_value.status_code = 200

        self.client.post('/api/save_record/', {
            'verified_data': {
                'symptoms': [],
                'medicines': [],
                'vitals': {},
                'allergies': ['Penicillin']  # Already known
            }
        }, format='json')

        profile = UserProfile.objects.get(user=self.user)
        # "Penicillin" should appear only once
        allergy_count = profile.known_allergies.lower().split(',').count('penicillin')
        self.assertEqual(allergy_count, 1)

    @patch('api.views.requests.post')
    def test_medicine_linked_to_symptom(self, mock_embed_post):
        """If a medicine's 'reason' matches a symptom name, they should be linked in the DB."""
        mock_embed_post.return_value.status_code = 200

        self.client.post('/api/save_record/', {
            'verified_data': {
                'symptoms': ['Headache'],
                'medicines': [
                    {'name': 'Paracetamol', 'dosage': '500mg', 'reason': 'Headache'}
                ],
                'vitals': {},
                'allergies': []
            }
        }, format='json')

        medicine = HealthEntity.objects.filter(type='MEDICINE', name='Paracetamol').first()
        self.assertIsNotNone(medicine.related_symptom)
        self.assertEqual(medicine.related_symptom.name, 'Headache')

    def test_save_record_missing_verified_data_returns_400(self):
        """Sending a request without 'verified_data' should return 400."""
        response = self.client.post('/api/save_record/', {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['error'], 'missing_data')

    def test_save_record_invalid_record_id_returns_404(self):
        """Passing a record_id that doesn't exist should return 404."""
        response = self.client.post('/api/save_record/', {
            'record_id': 99999,
            'verified_data': {
                'symptoms': [],
                'medicines': [],
                'vitals': {},
                'allergies': []
            }
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_save_record_requires_authentication(self):
        """Without a JWT token, saving should return 401."""
        unauthenticated_client = APIClient()
        response = unauthenticated_client.post('/api/save_record/', {
            'verified_data': {'symptoms': [], 'medicines': [], 'vitals': {}, 'allergies': []}
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class GetRecordTests(TestCase):
    """
    Tests for retrieving saved medical records.
    """

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='getuser',
            email='get@example.com',
            password='password123'
        )
        UserProfile.objects.create(user=self.user)

        login_response = self.client.post('/api/auth/login/', {
            'username': 'getuser',
            'password': 'password123'
        })
        self.token = login_response.data['access']
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token}')

    def test_get_records_empty_for_new_user(self):
        """A user with no records should get an empty list back."""
        response = self.client.get('/api/save_record/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 0)

    def test_get_records_returns_saved_data(self):
        """After saving a record, GET should return it with all entities."""
        # Create a record manually
        record = MedicalRecord.objects.create(user=self.user, category='Consultation')
        HealthEntity.objects.create(record=record, type='SYMPTOM', name='Cough')
        HealthEntity.objects.create(record=record, type='MEDICINE', name='Benadryl', value='10ml')
        HealthEntity.objects.create(record=record, type='VITAL', name='temp', value='99.1')

        response = self.client.get('/api/save_record/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

        returned_record = response.data[0]
        self.assertEqual(returned_record['category'], 'Consultation')
        self.assertEqual(len(returned_record['symptoms']), 1)
        self.assertEqual(returned_record['symptoms'][0], 'Cough')
        self.assertEqual(len(returned_record['medicines']), 1)
        self.assertEqual(returned_record['medicines'][0]['name'], 'Benadryl')
        self.assertEqual(len(returned_record['vitals']), 1)

    def test_records_are_user_scoped(self):
        """User A should NOT see User B's records."""
        # Create a record for user A
        MedicalRecord.objects.create(user=self.user, category='Test')

        # Create user B with their own record
        other_user = User.objects.create_user(username='other', email='other@test.com', password='pass123')
        MedicalRecord.objects.create(user=other_user, category='Other Test')

        # User A should only see 1 record (their own)
        response = self.client.get('/api/save_record/')
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['category'], 'Test')

    def test_get_records_requires_authentication(self):
        """Unauthenticated requests should be rejected."""
        unauthenticated_client = APIClient()
        response = unauthenticated_client.get('/api/save_record/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class ModelTests(TestCase):
    """
    Tests for the database models themselves.
    These make sure __str__ methods, relationships, and defaults work correctly.
    """

    def test_user_profile_str(self):
        user = User.objects.create_user(username='strtest', password='pass123')
        profile = UserProfile.objects.create(user=user)
        self.assertEqual(str(profile), 'strtest')

    def test_medical_record_str(self):
        user = User.objects.create_user(username='recstr', password='pass123')
        record = MedicalRecord.objects.create(user=user, category='Lab Report')
        self.assertIn('recstr', str(record))

    def test_health_entity_str(self):
        user = User.objects.create_user(username='entstr', password='pass123')
        record = MedicalRecord.objects.create(user=user)
        entity = HealthEntity.objects.create(record=record, type='MEDICINE', name='Aspirin')
        self.assertEqual(str(entity), 'MEDICINE: Aspirin')

    def test_user_profile_default_allergies_empty(self):
        """A new profile should have no allergies by default."""
        user = User.objects.create_user(username='noallergy', password='pass123')
        profile = UserProfile.objects.create(user=user)
        self.assertEqual(profile.known_allergies, '')

    def test_health_entity_related_symptom_nullable(self):
        """Medicines can exist without a linked symptom."""
        user = User.objects.create_user(username='nullsym', password='pass123')
        record = MedicalRecord.objects.create(user=user)
        medicine = HealthEntity.objects.create(
            record=record, type='MEDICINE', name='Vitamin D', value='60000 IU'
        )
        self.assertIsNone(medicine.related_symptom)

    def test_cascade_delete_removes_entities(self):
        """Deleting a MedicalRecord should also delete all associated HealthEntities."""
        user = User.objects.create_user(username='cascade', password='pass123')
        record = MedicalRecord.objects.create(user=user)
        HealthEntity.objects.create(record=record, type='SYMPTOM', name='Nausea')
        HealthEntity.objects.create(record=record, type='MEDICINE', name='Ondansetron')

        self.assertEqual(HealthEntity.objects.filter(record=record).count(), 2)

        record.delete()

        # After deleting the record, entities should be gone too
        self.assertEqual(HealthEntity.objects.count(), 0)
