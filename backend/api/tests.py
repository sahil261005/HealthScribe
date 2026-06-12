from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from rest_framework import status
from .models import MedicalRecord, HealthEntity, UserProfile
from unittest.mock import patch


class AuthenticationTests(TestCase):

    def setUp(self):
        self.client = APIClient()

    def test_register_new_user(self):
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
        self.assertTrue(User.objects.filter(username='testpatient').exists())

    def test_register_creates_profile(self):
        self.client.post('/api/auth/register/', {
            'username': 'profiletest',
            'email': 'profile@example.com',
            'password': 'securepassword123'
        })

        user = User.objects.get(username='profiletest')
        self.assertTrue(UserProfile.objects.filter(user=user).exists())

    def test_register_duplicate_username(self):
        User.objects.create_user(username='taken', email='first@example.com', password='password123')

        response = self.client.post('/api/auth/register/', {
            'username': 'taken',
            'email': 'second@example.com',
            'password': 'password123'
        })

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_duplicate_email(self):
        User.objects.create_user(username='user1', email='same@example.com', password='password123')

        response = self.client.post('/api/auth/register/', {
            'username': 'user2',
            'email': 'same@example.com',
            'password': 'password123'
        })

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_short_password(self):
        response = self.client.post('/api/auth/register/', {
            'username': 'shortpw',
            'email': 'short@example.com',
            'password': '123'
        })

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_missing_fields(self):
        response = self.client.post('/api/auth/register/', {
            'username': 'nopass'
        })

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_login_valid(self):
        User.objects.create_user(username='logintest', email='login@example.com', password='password123')

        response = self.client.post('/api/auth/login/', {
            'username': 'logintest',
            'password': 'password123'
        })

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)

    def test_login_wrong_password(self):
        User.objects.create_user(username='logintest2', email='login2@example.com', password='password123')

        response = self.client.post('/api/auth/login/', {
            'username': 'logintest2',
            'password': 'wrongpassword'
        })

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class ProfileTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='profileuser',
            email='profile@example.com',
            password='password123'
        )
        UserProfile.objects.create(user=self.user, known_allergies="Penicillin,Aspirin")

        login_response = self.client.post('/api/auth/login/', {
            'username': 'profileuser',
            'password': 'password123'
        })
        self.token = login_response.data['access']
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token}')

    def test_get_profile(self):
        response = self.client.get('/api/auth/profile/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['username'], 'profileuser')
        self.assertEqual(response.data['email'], 'profile@example.com')
        self.assertEqual(response.data['known_allergies'], 'Penicillin,Aspirin')

    def test_profile_needs_auth(self):
        no_auth_client = APIClient()
        response = no_auth_client.get('/api/auth/profile/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class SaveRecordTests(TestCase):

    def setUp(self):
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
    def test_save_full_record(self, mock_post):
        mock_post.return_value.status_code = 200

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

        record = MedicalRecord.objects.filter(user=self.user).first()
        self.assertIsNotNone(record)
        self.assertEqual(record.category, 'Consultation')

        self.assertEqual(HealthEntity.objects.filter(record=record, type='SYMPTOM').count(), 2)
        self.assertEqual(HealthEntity.objects.filter(record=record, type='MEDICINE').count(), 2)
        self.assertEqual(HealthEntity.objects.filter(record=record, type='VITAL').count(), 2)

    @patch('api.views.requests.post')
    def test_no_symptoms_is_general_checkup(self, mock_post):
        mock_post.return_value.status_code = 200

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
    def test_allergy_warning(self, mock_post):
        mock_post.return_value.status_code = 200

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
        warnings = response.data.get('warnings', [])
        self.assertTrue(len(warnings) > 0)
        self.assertIn('allergic', warnings[0].lower())

    @patch('api.views.requests.post')
    def test_no_warning_for_safe_medicine(self, mock_post):
        mock_post.return_value.status_code = 200

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
    def test_new_allergy_saved_to_profile(self, mock_post):
        mock_post.return_value.status_code = 200

        self.client.post('/api/save_record/', {
            'verified_data': {
                'symptoms': [],
                'medicines': [],
                'vitals': {},
                'allergies': ['Sulfa', 'Latex']
            }
        }, format='json')

        profile = UserProfile.objects.get(user=self.user)
        self.assertIn('Sulfa', profile.known_allergies)
        self.assertIn('Latex', profile.known_allergies)
        self.assertIn('Penicillin', profile.known_allergies)

    @patch('api.views.requests.post')
    def test_duplicate_allergy_not_added(self, mock_post):
        mock_post.return_value.status_code = 200

        self.client.post('/api/save_record/', {
            'verified_data': {
                'symptoms': [],
                'medicines': [],
                'vitals': {},
                'allergies': ['Penicillin']
            }
        }, format='json')

        profile = UserProfile.objects.get(user=self.user)
        count = profile.known_allergies.lower().split(',').count('penicillin')
        self.assertEqual(count, 1)

    @patch('api.views.requests.post')
    def test_medicine_linked_to_symptom(self, mock_post):
        mock_post.return_value.status_code = 200

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

    def test_missing_verified_data(self):
        response = self.client.post('/api/save_record/', {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['error'], 'missing_data')

    def test_invalid_record_id(self):
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

    def test_save_needs_auth(self):
        no_auth_client = APIClient()
        response = no_auth_client.post('/api/save_record/', {
            'verified_data': {'symptoms': [], 'medicines': [], 'vitals': {}, 'allergies': []}
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class GetRecordTests(TestCase):

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

    def test_empty_records(self):
        response = self.client.get('/api/save_record/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 0)

    def test_returns_saved_records(self):
        record = MedicalRecord.objects.create(user=self.user, category='Consultation')
        HealthEntity.objects.create(record=record, type='SYMPTOM', name='Cough')
        HealthEntity.objects.create(record=record, type='MEDICINE', name='Benadryl', value='10ml')
        HealthEntity.objects.create(record=record, type='VITAL', name='temp', value='99.1')

        response = self.client.get('/api/save_record/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

        data = response.data[0]
        self.assertEqual(data['category'], 'Consultation')
        self.assertEqual(len(data['symptoms']), 1)
        self.assertEqual(data['symptoms'][0], 'Cough')
        self.assertEqual(len(data['medicines']), 1)
        self.assertEqual(data['medicines'][0]['name'], 'Benadryl')
        self.assertEqual(len(data['vitals']), 1)

    def test_records_are_user_scoped(self):
        MedicalRecord.objects.create(user=self.user, category='Test')

        other_user = User.objects.create_user(username='other', email='other@test.com', password='pass123')
        MedicalRecord.objects.create(user=other_user, category='Other Test')

        response = self.client.get('/api/save_record/')
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['category'], 'Test')

    def test_get_records_needs_auth(self):
        no_auth_client = APIClient()
        response = no_auth_client.get('/api/save_record/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class ModelTests(TestCase):

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

    def test_default_empty_allergies(self):
        user = User.objects.create_user(username='noallergy', password='pass123')
        profile = UserProfile.objects.create(user=user)
        self.assertEqual(profile.known_allergies, '')

    def test_medicine_without_symptom(self):
        user = User.objects.create_user(username='nullsym', password='pass123')
        record = MedicalRecord.objects.create(user=user)
        medicine = HealthEntity.objects.create(
            record=record, type='MEDICINE', name='Vitamin D', value='60000 IU'
        )
        self.assertIsNone(medicine.related_symptom)

    def test_cascade_delete(self):
        user = User.objects.create_user(username='cascade', password='pass123')
        record = MedicalRecord.objects.create(user=user)
        HealthEntity.objects.create(record=record, type='SYMPTOM', name='Nausea')
        HealthEntity.objects.create(record=record, type='MEDICINE', name='Ondansetron')

        self.assertEqual(HealthEntity.objects.filter(record=record).count(), 2)
        record.delete()
        self.assertEqual(HealthEntity.objects.count(), 0)
