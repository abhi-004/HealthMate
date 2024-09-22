import pytest
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from .models import ChatSession, ChatMessage, Prescription
from django.utils import timezone
import json

class AuthAppTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='testuser', password='testpassword')
        self.login_url = reverse('login')
        self.register_url = reverse('register')
        self.dashboard_url = reverse('dashboard')
        self.chatbot_response_url = reverse('chatbot_response')
        self.book_appointment_url = reverse('book_appointment')
        self.end_session_url = reverse('end_session_and_generate_prescription')
        self.logout_url = reverse('logout')

    def test_register_view(self):
        response = self.client.post(self.register_url, {
            'username': 'newuser',
            'password1': 'hello@123',
            'password2': 'hello@123'
        })
        self.assertEqual(response.status_code, 302)  # Redirect after successful registration
        self.assertTrue(User.objects.filter(username='newuser').exists())

    def test_invalid_register_view(self):
        response = self.client.post(self.register_url, {
            'username': 'newuser',
            'password1': 'hello@123',
            'password2': 'differentpassword'
        })
        self.assertEqual(response.status_code, 200)  # Should return to the registration page
        self.assertFalse(User.objects.filter(username='newuser').exists())

    def test_login_view(self):
        response = self.client.post(self.login_url, {
            'username': 'testuser',
            'password': 'testpassword'
        })
        self.assertEqual(response.status_code, 302)  # Redirect after successful login
        self.assertTrue('_auth_user_id' in self.client.session)

    def test_invalid_login_view(self):
        response = self.client.post(self.login_url, {
            'username': 'testuser',
            'password': 'wrongpassword'
        })
        self.assertEqual(response.status_code, 200)  # Should return to the login page
        self.assertFalse('_auth_user_id' in self.client.session)

    def test_dashboard_view(self):
        self.client.login(username='testuser', password='testpassword')
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Dr. Assistant')

    def test_dashboard_view_without_login(self):
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 302)  # Redirect to login page

    def test_chatbot_response(self):
        self.client.login(username='testuser', password='testpassword')
        response = self.client.post(self.chatbot_response_url, json.dumps({'message': 'Hello'}), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertIn('response', response.json())

    def test_chatbot_response_without_login(self):
        response = self.client.post(self.chatbot_response_url, json.dumps({'message': 'Hello'}), content_type='application/json')
        self.assertEqual(response.status_code, 401) 

    def test_book_appointment(self):
        self.client.login(username='testuser', password='testpassword')
        response = self.client.post(self.book_appointment_url, json.dumps({'time_slot': '2023-10-10T10:00:00Z'}), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'success')

    def test_book_appointment_with_invalid_data(self):
        self.client.login(username='testuser', password='testpassword')
        response = self.client.post(self.book_appointment_url, json.dumps({'time_slot': ''}), content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['status'], 'error')

    def test_end_session_and_generate_prescription(self):
        self.client.login(username='testuser', password='testpassword')
        ChatSession.objects.create(user=self.user, start_time=timezone.now())
        response = self.client.post(self.end_session_url, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'success')

    def test_end_session_without_active_session(self):
        self.client.login(username='testuser', password='testpassword')
        response = self.client.post(self.end_session_url, content_type='application/json')
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()['status'], 'error')

    def test_logout_view(self):
        self.client.login(username='testuser', password='testpassword')
        response = self.client.get(self.logout_url)
        self.assertEqual(response.status_code, 302)  # Redirect after logout
        self.assertFalse('_auth_user_id' in self.client.session)