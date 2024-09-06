from django.db import models
from django.contrib.auth.models import User

class ChatSession(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    start_time = models.DateTimeField(auto_now_add=True)
    end_time = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Session {self.pk} for {self.user.username}"

class ChatMessage(models.Model):
    session = models.ForeignKey(ChatSession, related_name='messages', on_delete=models.CASCADE)
    chat = models.JSONField(default=list)  # Using the standard JSONField from Django
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        if self.chat:
            last_entry = self.chat[-1]  # Access the last chat entry for display
            return f"{self.session.user.username}: {last_entry.get('text', '')[:20]}"
        return f"{self.session.user.username}: No messages"

class Prescription(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    health_issue = models.TextField(blank=True)
    symptoms = models.JSONField(default=list)
    medicines_prescribed = models.JSONField(default=list)
    lifestyle_advice = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Prescription for {self.user.username}"
