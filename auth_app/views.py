from django.shortcuts import render, redirect
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from django.http import JsonResponse, HttpResponseRedirect
from django.views.decorators.csrf import csrf_exempt
from .models import ChatMessage, Prescription, ChatSession  # Import ChatSession here
from datetime import datetime
from dotenv import load_dotenv
from groq import Groq
from django.utils import timezone
from django.db import transaction
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter 
from django.http import FileResponse
import json
import os
import traceback 

# Load environment variables from .env file
load_dotenv()

# Initialize GROQ API client
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

from HealthMate.utils.helpers import (
    get_or_create_session,
    save_user_message,
    retrieve_latest_prescription,
    generate_initial_response,
    create_prompt,
    get_llm_response,
    end_current_chat_session,
    generate_and_store_prescription,
    generate_prescription_data,
    clean_prescription_response,
    create_prescription_pdf_file,
    store_prescription_in_db,
    store_combined_chat_messages,
    create_prescription_pdf
)

def register_view(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('dashboard')
    else:
        form = UserCreationForm(initial={'username':'', 'password1':'', 'password2':''})
    return render(request, 'auth/register.html', {'form': form})

@csrf_exempt
def login_view(request):
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            ChatSession.objects.create(user=user)
            return redirect('dashboard')
    else:
        form = AuthenticationForm(initial={'username':'', 'password':''})
    return render(request, 'auth/login.html', {'form': form})

@login_required
def dashboard_view(request):
    initial_message = f"👨‍⚕️ <strong>Dr. Assistant:</strong> <br><strong>Welcome {request.user.username},</strong> how can I assist you today?"

    try:
        user_sessions = ChatSession.objects.filter(user=request.user).order_by('-start_time')
        previous_session = user_sessions[1] if user_sessions.count() > 1 else None

        if previous_session:
            previous_messages = previous_session.messages.order_by('-timestamp')

            if previous_messages.exists():
                created = False
                initial_message = generate_initial_response(request.user.username, created, previous_messages)
            else:
                created = True
                initial_message = generate_initial_response(request.user.username, created, previous_messages)

    except ChatSession.DoesNotExist:
        pass

    return render(request, 'dashboard.html', {'initial_message': initial_message})

@csrf_exempt
def chatbot_response(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        user_message = data['message']

        # Retrieve or create a session for the user
        current_session, created = get_or_create_session(request.user)
        if current_session is None:
            return JsonResponse({'error': 'User not authenticated'}, status=401)
        # Save the user's message
        save_user_message(current_session, user_message)

        # Retrieve the latest prescription if it exists
        prescription_content = retrieve_latest_prescription(request.user)

        # Retrieve previous messages
        previous_messages = ChatMessage.objects.filter(session=current_session).order_by('timestamp')
        messages = [{"role": msg.chat[0]['role'], "content": msg.chat[0]['content']} for msg in previous_messages]

        # Add the latest prescription to the conversation if it exists
        if prescription_content:
            messages.insert(0, prescription_content)

        # Add the current user's message to the conversation
        messages.append({"role": "user", "content": user_message})

        # Generate the initial response
        initial_response = generate_initial_response(request.user.username, created, previous_messages)

        # Create the prompt for the LLM
        prompt = create_prompt(created, prescription_content)

        # Add the prompt to the conversation
        messages.insert(0, {"role": "system", "content": prompt})

        # Get the LLM response
        response = get_llm_response(messages)

        # Beautify the response for display
        beautified_response = f"👨‍⚕️ <strong>Dr. Assistant:</strong> <br>{response}"

        # Save the system's response to the database
        ChatMessage.objects.create(session=current_session, chat=[{"role": "system", "content": beautified_response}])

        return JsonResponse({'response': beautified_response, 'initial_response': initial_response})

def logout_view(request):
    if request.user.is_authenticated:
        # Log out the user
        logout(request)

    return redirect('login')

@csrf_exempt
@login_required
def book_appointment(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        time_slot = data.get('time_slot')

        if time_slot:
            # Log out the user after booking the appointment
            logout(request)
            return JsonResponse({'status': 'success', 'message': 'Appointment booked successfully.'})
        else:
            return JsonResponse({'status': 'error', 'message': 'Invalid time slot.'}, status=400)
    else:
        return JsonResponse({'status': 'error', 'message': 'Invalid request method.'}, status=405)

@csrf_exempt
@login_required
def end_session_and_generate_prescription(request):
    if request.method == 'POST':
        try:
            with transaction.atomic():
                # Generate and store the prescription
                file_response, filename = generate_and_store_prescription(request.user)

                # End the current chat session
                end_current_chat_session(request.user)

            # Return the file response to download the PDF
            return file_response
        except Exception as e:
            # Log the error for debugging purposes
            error_trace = traceback.format_exc()
            print(f"Error during prescription generation: {error_trace}")

            # Return an error response as JSON
            return JsonResponse({
                'status': 'error',
                'message': 'An error occurred while generating the prescription. Please try again later.'
            }, status=500)
    else:
        return JsonResponse({
            'status': 'error',
            'message': 'Invalid request method.'
        }, status=405)