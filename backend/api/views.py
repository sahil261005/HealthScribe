import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView
from django.db import transaction
from django.db.models import Q
from django.utils.dateparse import parse_date
from .models import MedicalRecord, HealthEntity, UserProfile, ShareableLink
from .serializers import UserRegistrationSerializer, UserProfileSerializer, EmailOrUsernameTokenObtainPairSerializer
from datetime import date, datetime, timedelta
import requests
import os
import re
import threading
import time

logger = logging.getLogger("api")

AI_SERVICE_URL = os.getenv("AI_SERVICE_URL", "http://localhost:8001")

# some allergies also cover other medicines from the same family,
# e.g. someone allergic to penicillin should not get amoxicillin either.
# not a complete list, just the common ones we see on prescriptions
PENICILLINS = ["penicillin", "amoxicillin", "amoxycillin", "ampicillin", "cloxacillin",
               "flucloxacillin", "dicloxacillin", "piperacillin", "augmentin", "amoxyclav",
               "novamox", "clavam", "moxikind"]
SULFA_DRUGS = ["sulfamethoxazole", "sulphamethoxazole", "cotrimoxazole", "co-trimoxazole",
               "septran", "bactrim", "sulfasalazine", "sulfadiazine"]
# brand names are added too because indian prescriptions mostly use brands
# (ecosprin is aspirin, brufen/combiflam have ibuprofen, meftal is mefenamic acid etc)
NSAIDS = ["aspirin", "ibuprofen", "diclofenac", "naproxen", "aceclofenac", "ketorolac", "mefenamic",
          "ecosprin", "disprin", "loprin", "brufen", "ibugesic", "combiflam", "voveran", "dynapar",
          "zerodol", "hifenac", "meftal", "naprosyn", "toradol"]

ALLERGY_GROUPS = {
    "penicillin": PENICILLINS,
    "sulfa": SULFA_DRUGS,
    "sulpha": SULFA_DRUGS,
    "aspirin": NSAIDS,
    "nsaid": NSAIDS,
    "ibuprofen": NSAIDS,
    "diclofenac": NSAIDS,
    "mefenamic": NSAIDS,
}


class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = EmailOrUsernameTokenObtainPairSerializer


def serialize_record(record):
    # grab all entities for this record
    all_entities = record.entities.all()
    symptoms_list = []
    medicines_list = []
    vitals_list = []
    allergies_list = []

    # sort by type
    for entity in all_entities:
        if entity.type == 'SYMPTOM':
            symptoms_list.append(entity.name)
        elif entity.type == 'MEDICINE':
            # use the linked symptom name if there is one (so "fever" and "Fever" group
            # together on the charts), otherwise the reason as it was written
            if entity.related_symptom:
                reason = entity.related_symptom.name
            else:
                reason = entity.reason
            medicine_info = {
                "name": entity.name,
                "dosage": entity.value,
                "effectiveness": entity.effectiveness,
                "reason": reason
            }
            medicines_list.append(medicine_info)
        elif entity.type == 'VITAL':
            vital_info = {
                "name": entity.name,
                "value": entity.value
            }
            vitals_list.append(vital_info)
        elif entity.type == 'ALLERGY':
            allergies_list.append(entity.name)

    # use the date written on the prescription if we have it, otherwise the upload date.
    # no timezone on purpose so the browser shows the same day that was on the prescription
    record_date = record.upload_date
    if record.visit_date:
        record_date = datetime.combine(record.visit_date, datetime.min.time())

    return {
        "id": record.id,
        "date": record_date,
        "upload_date": record.upload_date,
        "visit_date": record.visit_date,
        "category": record.category,
        "doctor_name": record.doctor_name,
        "symptoms": symptoms_list,
        "medicines": medicines_list,
        "vitals": vitals_list,
        "allergies": allergies_list,
    }


def build_embed_payload(record):
    # data the AI service needs to put this record into the vector db
    data = serialize_record(record)
    record_date = record.visit_date or record.upload_date

    vitals = {}
    for vital in data["vitals"]:
        vitals[vital["name"]] = vital["value"]

    medicines = []
    for med in data["medicines"]:
        medicines.append({
            "name": med["name"],
            "dosage": med["dosage"],
            "reason": med["reason"]
        })

    return {
        "record_id": record.id,
        "user_id": record.user_id,
        "category": record.category,
        "doctor_name": record.doctor_name,
        "upload_date": record_date.strftime("%B %d, %Y"),
        "symptoms": data["symptoms"],
        "medicines": medicines,
        "vitals": vitals,
        "allergies": data["allergies"]
    }


def ai_service_headers():
    # the AI service only accepts calls from django if this key matches
    return {"X-Internal-Key": os.getenv("INTERNAL_API_KEY", "")}


def send_to_ai_service_in_background(path, payload, description):
    # the AI service is on render free tier and can take ~1 min to wake up,
    # so try a few times instead of giving up after the first timeout
    def worker():
        for attempt in range(1, 4):
            try:
                resp = requests.post(
                    f"{AI_SERVICE_URL}{path}",
                    json=payload,
                    headers=ai_service_headers(),
                    timeout=60
                )
                if resp.status_code == 200:
                    logger.info("%s - done", description)
                    return
                if resp.status_code in (401, 403):
                    logger.error("%s - AI service rejected the call, check INTERNAL_API_KEY", description)
                    return
                logger.warning("%s - failed with status %d (attempt %d)", description, resp.status_code, attempt)
            except requests.exceptions.RequestException as e:
                logger.warning("%s - could not reach AI service (attempt %d): %s", description, attempt, e)

            if attempt < 3:
                time.sleep(10 * attempt)

        logger.error("%s - gave up, run 'python manage.py reembed_records' to fix it", description)

    threading.Thread(target=worker, daemon=True).start()


def check_drug_interactions(user, record, new_names):
    # asks the AI service if the new medicines clash with what the user is taking right now.
    # only medicines from the last 90 days count, an antibiotic from 2 years ago is not "current"
    cutoff = date.today() - timedelta(days=90)
    recent = Q(record__visit_date__gte=cutoff) | Q(record__visit_date__isnull=True, record__upload_date__date__gte=cutoff)
    past_names = HealthEntity.objects.filter(
        recent,
        record__user=user,
        type='MEDICINE'
    ).exclude(record=record).values_list('name', flat=True)
    past_names = list(set(past_names))

    if not past_names or not new_names:
        return []

    try:
        resp = requests.post(
            f"{AI_SERVICE_URL}/check_interactions",
            json={
                "current_medicines": past_names,
                "new_medicines": new_names
            },
            headers=ai_service_headers(),
            timeout=15
        )
    except requests.exceptions.RequestException as e:
        logger.warning("interaction check failed: %s", e)
        return []

    if resp.status_code != 200:
        logger.warning("interaction check returned status %d", resp.status_code)
        return []

    warnings = resp.json().get("warnings", [])
    if not isinstance(warnings, list):
        return []

    warnings = [str(w) for w in warnings if w]
    if warnings:
        logger.warning("drug interactions for %s: %s", user.username, warnings)
    return warnings


def clean_text(value):
    # the AI sometimes sends null instead of "" - also the db columns are 255 chars max
    if value is None:
        return ""
    return str(value).strip()[:255]


def clean_list(values):
    # same thing for lists, it can be null or have null items inside
    if not isinstance(values, list):
        return []
    cleaned = []
    for value in values:
        text = clean_text(value)
        if text:
            cleaned.append(text)
    return cleaned


def parse_visit_date(value):
    # the AI service sends dates as YYYY-MM-DD, anything else we just ignore
    if not value:
        return None
    try:
        parsed = parse_date(str(value).strip())
    except ValueError:
        return None
    # a date in the future means the date was misread.
    # the server runs on UTC and india is 5:30 ahead, so a prescription from "today"
    # can look like tomorrow to the server - allow one extra day for that
    if parsed is None or parsed > date.today() + timedelta(days=1):
        return None
    return parsed


def find_related_symptom(reason, symptom_map):
    # the reason is usually written a bit differently than the symptom
    # (like "for fever" vs "Fever") so exact matching almost never worked
    reason = reason.lower().strip()
    if len(reason) < 3:
        return None
    if reason in symptom_map:
        return symptom_map[reason]
    for symptom_name, entity in symptom_map.items():
        if len(symptom_name) >= 3 and (symptom_name in reason or reason in symptom_name):
            return entity
    return None


def find_allergy_match(medicine_name, allergies):
    # returns the allergy that this medicine clashes with, or None
    med = medicine_name.lower()
    med_words = re.findall(r"[a-z0-9]+", med)
    for allergy in allergies:
        allergy_lower = allergy.strip().lower()
        if len(allergy_lower) < 3:
            continue
        # short names only count as a whole word, otherwise "pan" would match "pantop"
        if allergy_lower in med_words:
            return allergy.strip()
        if len(allergy_lower) >= 5 and allergy_lower in med:
            return allergy.strip()
        for group, drugs in ALLERGY_GROUPS.items():
            in_this_family = group in allergy_lower
            # the allergy can also be written as a brand, like "brufen"
            for drug in drugs:
                if drug in allergy_lower:
                    in_this_family = True
            if in_this_family:
                for drug in drugs:
                    if drug in med:
                        return allergy.strip()
    return None



class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = UserRegistrationSerializer(data=request.data)

        if serializer.is_valid():
            new_user = serializer.save()
            refresh_token = RefreshToken.for_user(new_user)
            access_token = refresh_token.access_token

            logger.info("New user registered: %s", new_user.username)

            return Response({
                "message": "Registration successful!",
                "user": {
                    "id": new_user.id,
                    "username": new_user.username,
                    "email": new_user.email
                },
                "tokens": {
                    "access": str(access_token),
                    "refresh": str(refresh_token)
                }
            }, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            profile, _ = UserProfile.objects.get_or_create(user=request.user)
            serializer = UserProfileSerializer(profile)
            return Response(serializer.data)

        except Exception as e:
            logger.exception("profile fetch failed for %s: %s", request.user.username, e)
            return Response(
                {"error": "Could not load your profile."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class SaveRecordView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # fetch all records for this user
        try:
            records = (
                MedicalRecord.objects.filter(user=request.user)
                .prefetch_related('entities__related_symptom')
                .order_by('upload_date', 'id')
            )
            result = []
            for rec in records:
                result.append(serialize_record(rec))
            return Response(result)

        except Exception as e:
            logger.exception("records fetch failed for %s: %s", request.user.username, e)
            return Response(
                {"error": "Could not load your records."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def post(self, request):
        # save a new record or update existing one
        try:
            data = request.data
            user = request.user

            verified_data = data.get('verified_data')
            if not isinstance(verified_data, dict):
                return Response(
                    {"error": "missing_data", "message": "'verified_data' field is required."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            record_id = data.get('record_id')
            record = None

            if record_id:
                # updating existing record
                try:
                    record = MedicalRecord.objects.get(id=record_id, user=user)
                except (MedicalRecord.DoesNotExist, ValueError):
                    return Response(
                        {"error": "record_not_found", "message": f"Record {record_id} not found."},
                        status=status.HTTP_404_NOT_FOUND,
                    )

            # clean everything first - sarvam / gemini sometimes send null
            # instead of empty values and that used to crash the save
            doctor_name = clean_text(verified_data.get('doctor_name'))
            symptoms = clean_list(verified_data.get('symptoms'))
            allergies = clean_list(verified_data.get('allergies'))
            visit_date = parse_visit_date(verified_data.get('visit_date'))

            medicines = []
            for med in verified_data.get('medicines') or []:
                if not isinstance(med, dict):
                    continue
                name = clean_text(med.get('name'))
                if not name:
                    logger.warning("skipping medicine with empty name")
                    continue
                medicines.append({
                    "name": name,
                    "dosage": clean_text(med.get('dosage')),
                    "reason": clean_text(med.get('reason'))
                })

            vitals = {}
            raw_vitals = verified_data.get('vitals') or {}
            if isinstance(raw_vitals, dict):
                for vital_name, vital_value in raw_vitals.items():
                    value = clean_text(vital_value)
                    if value:
                        vitals[clean_text(vital_name)] = value

            category = 'General Checkup'
            if len(symptoms) > 0:
                category = 'Consultation'

            # everything below is saved together, so if something fails
            # we don't end up with half a record in the db
            with transaction.atomic():
                if record:
                    # remove the old entities first, otherwise every edit adds a second copy
                    record.entities.all().delete()
                    record.category = category
                    record.doctor_name = doctor_name
                    record.visit_date = visit_date
                    record.save()
                else:
                    record = MedicalRecord.objects.create(
                        user=user,
                        category=category,
                        doctor_name=doctor_name,
                        visit_date=visit_date
                    )

                symptom_map = {}
                for s in symptoms:
                    entity = HealthEntity.objects.create(
                        record=record,
                        type='SYMPTOM',
                        name=s
                    )
                    symptom_map[s.lower()] = entity

                for med in medicines:
                    HealthEntity.objects.create(
                        record=record,
                        type='MEDICINE',
                        name=med['name'],
                        value=med['dosage'],
                        reason=med['reason'],
                        related_symptom=find_related_symptom(med['reason'], symptom_map)
                    )

                for vital_name, vital_value in vitals.items():
                    HealthEntity.objects.create(
                        record=record,
                        type='VITAL',
                        name=vital_name,
                        value=vital_value
                    )

                for allergy_name in allergies:
                    HealthEntity.objects.create(
                        record=record,
                        type='ALLERGY',
                        name=allergy_name
                    )

                # add any new allergies to profile
                profile, _ = UserProfile.objects.get_or_create(user=user)
                known_allergies = [a.strip() for a in profile.known_allergies.split(',') if a.strip()]
                known_lower = [a.lower() for a in known_allergies]

                changed = False
                for allergy_name in allergies:
                    # a comma inside the name would break the comma separated list
                    allergy_name = allergy_name.replace(',', ' ').strip()
                    if allergy_name.lower() not in known_lower:
                        known_allergies.append(allergy_name)
                        known_lower.append(allergy_name.lower())
                        changed = True

                if changed:
                    profile.known_allergies = ','.join(known_allergies)
                    profile.save()
                    logger.info("updated allergies for %s: %s", user.username, profile.known_allergies)

            # check medicines against all known allergies
            # (this includes the allergies written on this same prescription)
            warnings = []
            for med in medicines:
                allergy = find_allergy_match(med['name'], known_allergies)
                if allergy:
                    warnings.append(f"Warning: Patient is allergic to {allergy} - {med['name']} may cause a reaction")

            # put the record in the vector db so the chatbot can find it
            send_to_ai_service_in_background(
                "/embed_record",
                build_embed_payload(record),
                f"embedding record {record.id}"
            )

            # check drug interactions with past medicines
            new_names = [med['name'] for med in medicines]
            warnings.extend(check_drug_interactions(user, record, new_names))

            return Response(
                {"message": "Data saved successfully", "warnings": warnings},
                status=status.HTTP_201_CREATED
            )

        except Exception as e:
            logger.exception("save_record failed for %s: %s", request.user.username, e)
            return Response(
                {"error": "Something went wrong while saving the record."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def delete(self, request):
        # deletes a medical record and tells the AI service to remove it from the vector store
        try:
            record_id = request.query_params.get('id')
            if not record_id:
                return Response(
                    {"error": "Record ID is required."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # verify the record exists and belongs to this user
            record = MedicalRecord.objects.get(id=record_id, user=request.user)
            deleted_id = record.id
            record.delete()

            # retried in the background, otherwise the chatbot keeps
            # answering from a record that doesn't exist anymore
            send_to_ai_service_in_background(
                "/delete_record",
                {"record_id": deleted_id},
                f"removing embedding for record {deleted_id}"
            )

            return Response({"message": "Record deleted successfully."})

        except (MedicalRecord.DoesNotExist, ValueError):
            return Response(
                {"error": "Record not found."},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.exception("delete failed: %s", e)
            return Response(
                {"error": "Something went wrong while deleting the record."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class GenerateShareLinkView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            link = ShareableLink.objects.filter(user=request.user).first()

            # expired links get replaced with a new token
            if link and link.is_expired():
                link.delete()
                link = None

            if link is None:
                link = ShareableLink.objects.create(user=request.user)

            return Response({
                "token": str(link.token),
                "expires_at": link.expires_at()
            }, status=status.HTTP_200_OK)
        except Exception as e:
            logger.exception("share link failed for %s: %s", request.user.username, e)
            return Response(
                {"error": "Could not create a share link."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def delete(self, request):
        # lets the user turn off sharing, the old link stops working straight away
        ShareableLink.objects.filter(user=request.user).delete()
        return Response({"message": "Share link disabled."})


class SharedReportView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, token):
        try:
            link = ShareableLink.objects.select_related('user').get(token=token)
            if link.is_expired():
                return Response({"error": "This link has expired. Ask for a new one."}, status=status.HTTP_404_NOT_FOUND)

            owner = link.user

            records = (
                MedicalRecord.objects.filter(user=owner)
                .prefetch_related('entities__related_symptom')
                .order_by('upload_date', 'id')
            )
            result = []
            for rec in records:
                result.append(serialize_record(rec))

            return Response({
                "patient_name": owner.username,
                "records": result
            })

        except ShareableLink.DoesNotExist:
            return Response({"error": "invalid or expired link"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.exception("shared report failed: %s", e)
            return Response(
                {"error": "Could not load this report."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
