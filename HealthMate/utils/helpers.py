from django.utils import timezone
from django.http import JsonResponse, FileResponse
from django.db import transaction
from auth_app.models import ChatMessage, Prescription, ChatSession
from datetime import datetime
import json
import os
import traceback
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem
from reportlab.pdfgen import canvas
from groq import Groq

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def get_or_create_session(user):
    try:
        if not user.is_authenticated:
            return None, False 
        session = ChatSession.objects.filter(user=user).latest('start_time')
        return session, False
    except ChatSession.DoesNotExist:
        session = ChatSession.objects.create(user=user, start_time=timezone.now())
        return session, True

def save_user_message(session, message):
    ChatMessage.objects.create(session=session, chat=[{"role": "user", "content": message}])

def retrieve_latest_prescription(user):
    try:
        last_prescription = Prescription.objects.filter(user=user).latest('created_at')
        medicines_prescribed_str = ', '.join(
            [json.dumps(med) if isinstance(med, dict) else str(med) for med in last_prescription.medicines_prescribed]
        )
        return {
            "role": "system",
            "content": (
                f"Previous Prescription: \n"
                f"Health Issue: {last_prescription.health_issue}\n"
                f"Symptoms: {', '.join(last_prescription.symptoms)}\n"
                f"Medicines Prescribed: {medicines_prescribed_str}\n"
                f"Lifestyle Advice: {last_prescription.lifestyle_advice}"
            )
        }
    except Prescription.DoesNotExist:
        return None

def generate_initial_response(username, created, previous_messages):
    if created:
        return f"👨‍⚕️ <strong>Dr. Assistant:</strong> <br><strong>Hi {username},</strong> how are you feeling today?"
    else:
        last_visit_time = previous_messages.first().timestamp
        hours_since_last_visit = (timezone.now() - last_visit_time).total_seconds() / 3600
        return (
            f"👨‍⚕️ <strong>Dr. Assistant:</strong> <br>"
            f"<strong>Welcome back, {username}!</strong><br>"
            f"You last visited <strong>{hours_since_last_visit:.2f}</strong> hours ago.<br>"
            "How can I assist you with your health today?"
        )

def create_prompt(created, prescription_content):
    if created:
        return (
            "You are a 20-year experienced doctor, and there is a first-time patient coming to you "
            "telling the symptoms that they are facing. You need to understand the health issues based on "
            "the symptoms that the user is describing and prescribe some medications and lifestyle advice."
        )
    else:
        return (
            "You are a 20-year experienced doctor, and there is a returning patient coming to you telling the symptoms "
            "that they are facing. You need to understand the health issues based on the symptoms that the user is describing "
            "and prescribe some medications and lifestyle advice. Here is the user's last prescription: "
            f"{prescription_content['content'] if prescription_content else ''}"
        )

def get_llm_response(messages, model="llama3-8b-8192"):
    chat_completion = client.chat.completions.create(messages=messages, model=model)
    return chat_completion.choices[0].message.content

def end_current_chat_session(user):
    # Fetch the latest session for the user
    try:
        current_session = ChatSession.objects.filter(user=user).latest('start_time')
        current_session.end_time = timezone.now()
        current_session.save()
    except ChatSession.DoesNotExist:
        pass  # If no session exists, do nothing (should not happen normally)

def generate_and_store_prescription(user):
    try:
        current_session = ChatSession.objects.filter(user=user).latest('start_time')
        prescription_data = generate_prescription_data(user, current_session)
        file_path = create_prescription_pdf_file(user, prescription_data)
        store_prescription_in_db(user, prescription_data)
        store_combined_chat_messages(current_session, prescription_data['Messages'])
        filename = os.path.basename(file_path)
        return FileResponse(open(file_path, 'rb'), as_attachment=True, filename=os.path.basename(file_path)), filename

    except ChatSession.DoesNotExist:
        print("No active chat session found for the user.")
    except Exception as e:
        print(f"An error occurred: {e}")
        # Optionally, handle different types of exceptions separately or log them

def generate_prescription_data(user, current_session):
    chat_messages = ChatMessage.objects.filter(session=current_session).order_by('timestamp')
    messages = [{"role": msg.chat[0]['role'], "content": msg.chat[0]['content']} for msg in chat_messages]
    fallback_prescription_data = {
        'Username': user.username,
        'HealthIssue': 'Unable to parse health issue',
        'Symptoms': [],
        'MedicinesPrescribed': [],
        'LifestyleAdvice': 'Consult with a physician.'
    }

    prescription_prompt = (
        """
        Generate a prescription that identifies the health issue, lists the symptoms, specifies the medicines prescribed, 
        and gives lifestyle advice. Respond only with a well-formed JSON object. Do not include any introductory or 
        explanatory text, just the JSON object. Here is the required format:
        {
        "Username": "%s",
        "HealthIssue": "",
        "Symptoms": [],
        "MedicinesPrescribed": [],
        "LifestyleAdvice": ""
        }
        """ % user.username
    )

    messages.insert(0, {"role": "system", "content": prescription_prompt})

    try:
        chat_completion = client.chat.completions.create(messages=messages, model="llama3-8b-8192")
        prescription_response = chat_completion.choices[0].message.content.strip()
        print(f"Prescription response: {prescription_response}")

        cleaned_response = clean_prescription_response(prescription_response)
        prescription_data = json.loads(cleaned_response)
        prescription_data['Username'] = user.username
        prescription_data['Messages'] = messages  # Store the messages for later use

    except (json.JSONDecodeError, Exception) as e:
        print(f"Error generating or parsing prescription: {e}")
        prescription_data = fallback_prescription_data

    print(f"Final Prescription Data: {prescription_data}")
    return prescription_data

def clean_prescription_response(response):
    if not response.endswith('}'):
        response += '}'
    json_start = response.find('{')
    json_end = response.rfind('}') + 1
    return response[json_start:json_end]

def create_prescription_pdf_file(user, prescription_data):
    try:
        current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = f"{user.username}_prescription_{current_time}.pdf"
        media_dir = 'media/prescription'
        os.makedirs(media_dir, exist_ok=True)
        file_path = os.path.join(media_dir, file_name)
        create_prescription_pdf(prescription_data, file_path)
        print("PDF created successfully!")
        return file_path

    except Exception as e:
        print(f"Error creating PDF: {e}")
        raise

def store_prescription_in_db(user, prescription_data):
    symptoms_str = json.dumps(prescription_data.get('Symptoms', []))
    medicines_str = json.dumps(prescription_data.get('MedicinesPrescribed', []))
    lifestyle_advice_str = json.dumps(prescription_data.get('LifestyleAdvice', []))

    Prescription.objects.update_or_create(
        user=user,
        defaults={
            'health_issue': prescription_data.get('HealthIssue', ''),
            'symptoms': symptoms_str,
            'medicines_prescribed': medicines_str,
            'lifestyle_advice': lifestyle_advice_str
        }
    )

def store_combined_chat_messages(current_session, messages):
    combined_chat = [{"role": msg["role"], "content": msg["content"]} for msg in messages][1:]
    ChatMessage.objects.create(
        session=current_session,
        chat=combined_chat,
        timestamp=timezone.now()
    )
# Function to generate PDF
def create_prescription_pdf(prescription_data, file_path):
    # Create the PDF document
    doc = SimpleDocTemplate(file_path, pagesize=letter)
    story = []
    # Define styles
    styles = getSampleStyleSheet()
    title_style = styles['Title']
    normal_style = styles['BodyText']
    bold_style = styles['Heading2']
    # Title
    title = Paragraph("Prescription Details", title_style)
    story.append(title)
    story.append(Spacer(1, 12))
    # User Information
    user_info = Paragraph(f"<b>Username:</b> {prescription_data.get('Username', '')}", normal_style)
    story.append(user_info)
    story.append(Spacer(1, 12))
    # Health Issue
    health_issue = Paragraph(f"<b>Health Issue:</b> {prescription_data.get('HealthIssue', '')}", normal_style)
    story.append(health_issue)
    story.append(Spacer(1, 12))
    # Symptoms
    symptoms = prescription_data.get('Symptoms', [])
    story.append(Paragraph("<b>Symptoms:</b>", bold_style))
    symptom_items = [ListItem(Paragraph(f"- {symptom}", normal_style)) for symptom in symptoms]
    story.append(ListFlowable(symptom_items, bulletType='bullet'))
    story.append(Spacer(1, 12))
    # Medicines Prescribed
    medicines = prescription_data.get('MedicinesPrescribed', [])
    story.append(Paragraph("<b>Medicines Prescribed:</b>", bold_style))
    medicine_items = [ListItem(Paragraph(f"- {med}", normal_style)) for med in medicines]
    story.append(ListFlowable(medicine_items, bulletType='bullet'))
    story.append(Spacer(1, 12))
    # Lifestyle Advice
    story.append(Paragraph("<b>Lifestyle Advice:</b>", bold_style))
    lifestyle_advice = prescription_data.get('LifestyleAdvice', [])
    # Convert the list of lifestyle advice into a single string if it's a list
    if isinstance(lifestyle_advice, list):
        lifestyle_advice = " ".join(lifestyle_advice)
    # Custom style to prevent text breakage
    advice_style = ParagraphStyle(
        'AdviceStyle',
        parent=normal_style,
        wordWrap='CJK',  # Ensures that words are not split inappropriately
    )

    # Add lifestyle advice paragraph with the custom style
    advice_paragraph = Paragraph(f"- {lifestyle_advice}", advice_style)
    story.append(advice_paragraph)
    story.append(Spacer(1, 12))  # Add a small space between each advice item
    # Add the doctor's name at the end
    doctor_name = Paragraph("<b>Doctor:</b> Healthmate", normal_style)
    story.append(doctor_name)
    # Build the PDF
    doc.build(story)