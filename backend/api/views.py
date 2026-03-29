import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework_simplejwt.tokens import RefreshToken
from .models import MedicalRecord, HealthEntity, UserProfile
from .serializers import UserRegistrationSerializer, UserProfileSerializer
import requests
import os

# using logging instead of print so we get timestamps and stuff
logger = logging.getLogger("api")


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
            user_profile, was_created = UserProfile.objects.get_or_create(
                user=request.user
            )
            serializer = UserProfileSerializer(user_profile)
            return Response(serializer.data)

        except Exception as error:
            logger.exception("Failed to fetch profile for user %s: %s", request.user.username, error)
            return Response(
                {"error": "profile_fetch_failed", "message": str(error)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class SaveRecordView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """returns all medical records for the logged in user
        groups them with their symptoms, medicines, vitals etc"""
        try:
            current_user = request.user
            all_records = MedicalRecord.objects.filter(user=current_user).prefetch_related('entities')
            response_data = []

            for single_record in all_records:
                all_entities = single_record.entities.all()
                symptoms_list = []
                medicines_list = []
                vitals_list = []
                allergies_list = []

                # sort each entity into the right list based on its type
                for entity in all_entities:
                    if entity.type == 'SYMPTOM':
                        symptoms_list.append(entity.name)
                    elif entity.type == 'MEDICINE':
                        medicine_info = {
                            "name": entity.name,
                            "dosage": entity.value,
                            "effectiveness": entity.effectiveness
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

                record_data = {
                    "id": single_record.id,
                    "date": single_record.upload_date,
                    "category": single_record.category,
                    "symptoms": symptoms_list,
                    "medicines": medicines_list,
                    "vitals": vitals_list,
                    "allergies": allergies_list,
                }
                response_data.append(record_data)

            return Response(response_data)

        except Exception as error:
            logger.exception("Failed to fetch records for user %s: %s", request.user.username, error)
            return Response(
                {"error": "records_fetch_failed", "message": str(error)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def post(self, request):
        """saves the verified medical data after user reviews what the AI extracted.
        also checks if any new medicines conflict with known allergies
        and syncs everything to the vector database for the chatbot"""
        try:
            incoming_data = request.data
            current_user = request.user

            # make sure the client actually sent the data
            verified_data = incoming_data.get('verified_data')
            if verified_data is None:
                return Response(
                    {"error": "missing_data", "message": "'verified_data' field is required."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            record_id = incoming_data.get('record_id')
            medical_record = None

            if record_id:
                # updating an existing record
                try:
                    medical_record = MedicalRecord.objects.get(id=record_id, user=current_user)
                except MedicalRecord.DoesNotExist:
                    return Response(
                        {"error": "record_not_found", "message": f"Record {record_id} not found for this user."},
                        status=status.HTTP_404_NOT_FOUND,
                    )
            else:
                # creating a new record
                symptoms_from_ai = verified_data.get('symptoms', [])

                # decide the category based on whether there are symptoms
                record_category = 'General Checkup'
                if len(symptoms_from_ai) > 0:
                    record_category = 'Consultation'

                medical_record = MedicalRecord.objects.create(
                    user=current_user,
                    category=record_category
                )

            medicines_list = verified_data.get('medicines', [])
            symptoms_list = verified_data.get('symptoms', [])
            vitals_dict = verified_data.get('vitals', {})
            allergies_list = verified_data.get('allergies', [])

            # get the users known allergies so we can check for conflicts
            user_profile, was_created = UserProfile.objects.get_or_create(user=current_user)
            known_allergies_list = []
            if user_profile.known_allergies:
                known_allergies_list = user_profile.known_allergies.split(',')

            warning_messages = []
            symptom_name_to_object = {}

            # save symptoms first so we can link medicines to them
            for symptom_name in symptoms_list:
                new_symptom = HealthEntity.objects.create(
                    record=medical_record,
                    type='SYMPTOM',
                    name=symptom_name
                )
                symptom_name_to_object[symptom_name] = new_symptom

            # save medicines and check for allergy conflicts
            for medicine_item in medicines_list:
                medicine_name = medicine_item.get('name', '')
                medicine_dosage = medicine_item.get('dosage', '')
                medicine_reason = medicine_item.get('reason', '')

                # skip medicines with no name (sometimes the AI returns empty ones)
                if not medicine_name.strip():
                    logger.warning("Skipping medicine with empty name in record %d", medical_record.id)
                    continue

                # try to link this medicine to a symptom if the reason matches
                linked_symptom = None
                if medicine_reason in symptom_name_to_object:
                    linked_symptom = symptom_name_to_object[medicine_reason]

                HealthEntity.objects.create(
                    record=medical_record,
                    type='MEDICINE',
                    name=medicine_name,
                    value=medicine_dosage,
                    related_symptom=linked_symptom
                )

                # check if this medicine matches any known allergies
                for allergy in known_allergies_list:
                    if allergy.strip() == '':
                        continue
                    if allergy.strip().lower() in medicine_name.lower():
                        warning_text = f"Warning: Patient is allergic to {medicine_name}"
                        warning_messages.append(warning_text)
                        break

            # save vitals
            for vital_name, vital_value in vitals_dict.items():
                HealthEntity.objects.create(
                    record=medical_record,
                    type='VITAL',
                    name=vital_name,
                    value=vital_value
                )

            # save allergies as health entities too
            for allergy_name in allergies_list:
                HealthEntity.objects.create(
                    record=medical_record,
                    type='ALLERGY',
                    name=allergy_name
                )

            # check if the AI found any new allergies we didnt know about
            # if so, add them to the users profile automaticaly
            found_new_allergy = False
            for allergy_name in allergies_list:
                is_already_known = False
                for existing_allergy in known_allergies_list:
                    if existing_allergy.strip().lower() == allergy_name.strip().lower():
                        is_already_known = True
                        break

                if not is_already_known:
                    if user_profile.known_allergies:
                        user_profile.known_allergies = user_profile.known_allergies + ',' + allergy_name
                    else:
                        user_profile.known_allergies = allergy_name
                    found_new_allergy = True

            if found_new_allergy:
                user_profile.save()
                logger.info("Updated allergies for user %s: %s", current_user.username, user_profile.known_allergies)

            # try to sync this record to the vector store for the chatbot
            # if this fails its not a big deal, the record is still saved in the db
            try:
                ai_service_url = os.getenv("AI_SERVICE_URL", "http://localhost:8001")

                medicines_for_embedding = []
                for medicine_item in medicines_list:
                    medicines_for_embedding.append({
                        "name": medicine_item.get("name", ""),
                        "dosage": medicine_item.get("dosage", ""),
                        "reason": medicine_item.get("reason", "")
                    })

                embed_payload = {
                    "record_id": medical_record.id,
                    "user_id": current_user.id,
                    "category": medical_record.category,
                    "upload_date": str(medical_record.upload_date),
                    "symptoms": symptoms_list,
                    "medicines": medicines_for_embedding,
                    "vitals": vitals_dict,
                    "allergies": allergies_list
                }

                embed_response = requests.post(
                    f"{ai_service_url}/embed_record",
                    json=embed_payload,
                    timeout=10
                )

                if embed_response.status_code == 200:
                    logger.info("Embedded record %d into vector store.", medical_record.id)
                else:
                    logger.warning("Failed to embed record %d: HTTP %d", medical_record.id, embed_response.status_code)

            except requests.exceptions.RequestException as embed_error:
                logger.warning("Could not reach AI service for embedding: %s", embed_error)

            return Response(
                {"message": "Data saved successfully", "warnings": warning_messages},
                status=status.HTTP_201_CREATED
            )

        except Exception as error:
            logger.exception("save_record failed for user %s: %s", request.user.username, error)
            return Response(
                {"error": "save_failed", "message": str(error)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
