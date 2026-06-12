import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework_simplejwt.tokens import RefreshToken
from .models import MedicalRecord, HealthEntity, UserProfile, ShareableLink
from .serializers import UserRegistrationSerializer, UserProfileSerializer
import requests
import os

logger = logging.getLogger("api")


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
            medicine_info = {
                "name": entity.name,
                "dosage": entity.value,
                "effectiveness": entity.effectiveness,
                "reason": entity.related_symptom.name if entity.related_symptom else ""
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

    return {
        "id": record.id,
        "date": record.upload_date,
        "category": record.category,
        "doctor_name": record.doctor_name,
        "symptoms": symptoms_list,
        "medicines": medicines_list,
        "vitals": vitals_list,
        "allergies": allergies_list,
    }



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
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class SaveRecordView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # fetch all records for this user
        try:
            records = MedicalRecord.objects.filter(user=request.user).prefetch_related('entities')
            result = []
            for rec in records:
                result.append(serialize_record(rec))
            return Response(result)

        except Exception as e:
            logger.exception("records fetch failed for %s: %s", request.user.username, e)
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def post(self, request):
        # save a new record or update existing one
        try:
            data = request.data
            user = request.user

            verified_data = data.get('verified_data')
            if verified_data is None:
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
                except MedicalRecord.DoesNotExist:
                    return Response(
                        {"error": "record_not_found", "message": f"Record {record_id} not found."},
                        status=status.HTTP_404_NOT_FOUND,
                    )
            else:
                # new record
                symptoms_list = verified_data.get('symptoms', [])

                category = 'General Checkup'
                if len(symptoms_list) > 0:
                    category = 'Consultation'

                record = MedicalRecord.objects.create(
                    user=user,
                    category=category,
                    doctor_name=verified_data.get('doctor_name', '')
                )

            medicines = verified_data.get('medicines', [])
            symptoms = verified_data.get('symptoms', [])
            vitals = verified_data.get('vitals', {})
            allergies = verified_data.get('allergies', [])

            # check against known allergies
            profile, _ = UserProfile.objects.get_or_create(user=user)
            known_allergies = []
            if profile.known_allergies:
                known_allergies = profile.known_allergies.split(',')

            warnings = []
            symptom_map = {}

            for s in symptoms:
                entity = HealthEntity.objects.create(
                    record=record,
                    type='SYMPTOM',
                    name=s
                )
                symptom_map[s] = entity

            # save medicines and check against allergies
            for med in medicines:
                name = med.get('name', '')
                dosage = med.get('dosage', '')
                reason = med.get('reason', '')

                if not name.strip():
                    logger.warning("skipping medicine with empty name in record %d", record.id)
                    continue

                linked = symptom_map.get(reason)

                HealthEntity.objects.create(
                    record=record,
                    type='MEDICINE',
                    name=name,
                    value=dosage,
                    related_symptom=linked
                )

                for allergy in known_allergies:
                    if allergy.strip() == '':
                        continue
                    if allergy.strip().lower() in name.lower():
                        warnings.append(f"Warning: Patient is allergic to {name}")
                        break

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
            changed = False
            for allergy_name in allergies:
                already_known = any(
                    a.strip().lower() == allergy_name.strip().lower()
                    for a in known_allergies
                )
                if not already_known:
                    if profile.known_allergies:
                        profile.known_allergies += ',' + allergy_name
                    else:
                        profile.known_allergies = allergy_name
                    changed = True

            if changed:
                profile.save()
                logger.info("updated allergies for %s: %s", user.username, profile.known_allergies)

            # send to AI service for vector embedding
            try:
                ai_url = os.getenv("AI_SERVICE_URL", "http://localhost:8001")

                meds_payload = []
                for med in medicines:
                    meds_payload.append({
                        "name": med.get("name", ""),
                        "dosage": med.get("dosage", ""),
                        "reason": med.get("reason", "")
                    })

                embed_payload = {
                    "record_id": record.id,
                    "user_id": user.id,
                    "category": record.category,
                    "upload_date": str(record.upload_date),
                    "symptoms": symptoms,
                    "medicines": meds_payload,
                    "vitals": vitals,
                    "allergies": allergies
                }

                resp = requests.post(
                    f"{ai_url}/embed_record",
                    json=embed_payload,
                    timeout=10
                )

                if resp.status_code == 200:
                    logger.info("embedded record %d", record.id)
                else:
                    logger.warning("embed failed for record %d: %d", record.id, resp.status_code)

            except requests.exceptions.RequestException as e:
                logger.warning("could not reach AI service: %s", e)

            # check drug interactions with past medicines
            try:
                past_meds = HealthEntity.objects.filter(
                    record__user=user,
                    type='MEDICINE'
                ).exclude(record=record)

                past_names = [m.name for m in past_meds]
                new_names = [m.get('name') for m in medicines if m.get('name')]

                if past_names and new_names:
                    ai_url = os.getenv("AI_SERVICE_URL", "http://localhost:8001")
                    resp = requests.post(
                        f"{ai_url}/check_interactions",
                        json={
                            "current_medicines": list(set(past_names)),
                            "new_medicines": new_names
                        },
                        timeout=15
                    )

                    if resp.status_code == 200:
                        interaction_warnings = resp.json().get("warnings", [])
                        if interaction_warnings:
                            warnings.extend(interaction_warnings)
                            logger.warning("drug interactions for %s: %s", user.username, interaction_warnings)
            except Exception as e:
                logger.warning("interaction check failed: %s", e)

            return Response(
                {"message": "Data saved successfully", "warnings": warnings},
                status=status.HTTP_201_CREATED
            )

        except Exception as e:
            logger.exception("save_record failed for %s: %s", request.user.username, e)
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def delete(self, request):
        # deletes a medical record and alerts AI service to clean up vector store
        try:
            record_id = request.query_params.get('id')
            if not record_id:
                return Response(
                    {"error": "Record ID is required."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # verify the record exists and belongs to this user
            record = MedicalRecord.objects.get(id=record_id, user=request.user)
            record.delete()

            # call AI service to drop the high-dimensional embedding
            try:
                ai_url = os.getenv("AI_SERVICE_URL", "http://localhost:8001")
                requests.post(
                    f"{ai_url}/delete_record",
                    json={"record_id": int(record_id)},
                    timeout=5
                )
            except Exception as e:
                logger.warning("failed to notify AI service of record deletion: %s", e)

            return Response({"message": "Record deleted successfully."})

        except MedicalRecord.DoesNotExist:
            return Response(
                {"error": "Record not found."},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.exception("delete failed: %s", e)
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class GenerateShareLinkView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            link, _ = ShareableLink.objects.get_or_create(user=request.user)
            return Response({"token": str(link.token)}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.exception("share link failed for %s: %s", request.user.username, e)
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class SharedReportView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, token):
        try:
            link = ShareableLink.objects.get(token=token)
            owner = link.user

            records = MedicalRecord.objects.filter(user=owner).prefetch_related('entities')
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
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
