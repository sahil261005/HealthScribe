from django.db import models
from django.contrib.auth.models import User


class UserProfile(models.Model):
    """extra info about the user that django's built in User model doesnt have.
    right now its just allergies but could add blood type, emergency contact etc later"""

    # one profile per user
    user = models.OneToOneField(User, on_delete=models.CASCADE)

    # storing allergies as comma separated string for now
    # like "Penicillin,Aspirin,Peanuts"
    # ideally this should be a separate model with ManyToMany but this works for mvp
    known_allergies = models.TextField(blank=True, default="")

    def __str__(self):
        return self.user.username


class MedicalRecord(models.Model):
    """represents one medical document or visit.
    this is the parent - each record has multiple HealthEntity children
    (symptoms, medicines, vitals etc)"""

    user = models.ForeignKey(User, on_delete=models.CASCADE)

    # the actual uploaded file (optional since we might just save extracted data)
    file = models.FileField(upload_to='records/', blank=True, null=True)

    upload_date = models.DateTimeField(auto_now_add=True)

    # category helps group things on the dashboard
    # like "Consultation", "Lab Report", "General Checkup"
    category = models.CharField(max_length=100, blank=True)

    def __str__(self):
        return f"{self.user.username} - {self.upload_date.date()}"


class HealthEntity(models.Model):
    """a single piece of health data extracted from a record.
    could be a medicine, symptom, vital sign, or allergy.

    using one model for all types instead of separate models
    becuase they share most fields and it keeps things simpler"""

    ENTITY_TYPES = [
        ('MEDICINE', 'Medicine'),
        ('SYMPTOM', 'Symptom'),
        ('ALLERGY', 'Allergy'),
        ('VITAL', 'Vital'),
    ]

    # for tracking how well a medicine worked (user can set this later)
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

    # the name - like "Paracetamol" or "Headache" or "BP"
    name = models.CharField(max_length=255)

    # extra value field, means different things depending on type:
    # medicine -> dosage ("500mg twice daily")
    # vital -> reading ("120/80")
    # symptom -> could be severity or just empty
    value = models.CharField(max_length=255, blank=True)

    # links a medicine to the symptom its treating
    # so we know "Paracetamol" is for "Headache"
    related_symptom = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.SET_NULL
    )

    # how effective this medicine was (optional, for user feedback)
    effectiveness = models.CharField(
        max_length=10,
        choices=EFFECTIVENESS_CHOICES,
        blank=True,
        null=True
    )

    # any side effects noted (optional)
    side_effects = models.TextField(blank=True)

    def __str__(self):
        return f"{self.type}: {self.name}"
