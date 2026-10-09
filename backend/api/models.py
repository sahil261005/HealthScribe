from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
import uuid

# share links stop working after this many days
SHARE_LINK_DAYS = 7


class UserProfile(models.Model):
    # link to django's built-in User
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    
    # allergies stored as comma-separated string
    known_allergies = models.TextField(blank=True, default="")

    def __str__(self):
        return self.user.username


class MedicalRecord(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    file = models.FileField(upload_to='records/', blank=True, null=True)
    upload_date = models.DateTimeField(auto_now_add=True)
    # date written on the prescription (upload_date is just when it was uploaded)
    visit_date = models.DateField(null=True, blank=True)
    category = models.CharField(max_length=100, blank=True)
    doctor_name = models.CharField(max_length=255, blank=True)

    def __str__(self):
        # show something readable in admin
        from datetime import datetime
        if isinstance(self.upload_date, datetime):
            return f"{self.user.username} - {self.upload_date.date()}"
        return f"{self.user.username} - {self.upload_date}"


class HealthEntity(models.Model):
    # tracks symptoms, medicines, vitals or allergies from a record
    ENTITY_TYPES = [
        ('MEDICINE', 'Medicine'),
        ('SYMPTOM', 'Symptom'),
        ('ALLERGY', 'Allergy'),
        ('VITAL', 'Vital'),
    ]

    EFFECTIVENESS_CHOICES = [
        ('HIGH', 'High'),
        ('MEDIUM', 'Medium'),
        ('LOW', 'Low'),
    ]

    record = models.ForeignKey(
        MedicalRecord,
        related_name='entities',
        on_delete=models.CASCADE
    )

    type = models.CharField(max_length=20, choices=ENTITY_TYPES)
    name = models.CharField(max_length=255)

    # for medicines this is dosage, for vitals this is the reading
    value = models.CharField(max_length=255, blank=True)

    # why the medicine was given, exactly as the AI / user wrote it
    reason = models.CharField(max_length=255, blank=True, default="")

    # which symptom this medicine is treating
    related_symptom = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.SET_NULL
    )

    effectiveness = models.CharField(
        max_length=10,
        choices=EFFECTIVENESS_CHOICES,
        blank=True,
        null=True
    )

    side_effects = models.TextField(blank=True)

    def __str__(self):
        return f"{self.type}: {self.name}"


class ShareableLink(models.Model):
    # shareable link with a secret token for sharing reports
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='shareable_link')
    token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def expires_at(self):
        return self.created_at + timedelta(days=SHARE_LINK_DAYS)

    def is_expired(self):
        return timezone.now() > self.expires_at()

    def __str__(self):
        return f"Share link for {self.user.username}"
