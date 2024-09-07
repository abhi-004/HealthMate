from django.urls import path
from .views import register_view, login_view, dashboard_view, logout_view, chatbot_response, end_session_and_generate_prescription, book_appointment
from django.conf.urls.static import static
from django.conf import settings


urlpatterns = [
    path('register/', register_view, name='register'),
    path('login/', login_view, name='login'),
    path('dashboard/', dashboard_view, name='dashboard'),
    path('logout/', logout_view, name='logout'),
    path('chatbot_response/', chatbot_response, name='chatbot_response'),
    path('end-session-and-generate-prescription/', end_session_and_generate_prescription, name='end_session_and_generate_prescription'),
    path('book_appointment/', book_appointment, name='book_appointment'),  # Add this line


]