import requests
from django.core.management.base import BaseCommand

from api.models import MedicalRecord
from api.views import AI_SERVICE_URL, ai_service_headers, build_embed_payload


class Command(BaseCommand):
    # use this if some records are missing from the chatbot
    # (e.g. the AI service was asleep when they were saved)
    help = "Sends medical records to the AI service again so the chatbot can find them"

    def add_arguments(self, parser):
        parser.add_argument("--user", type=str, help="only re-embed records of this username")

    def handle(self, *args, **options):
        records = MedicalRecord.objects.prefetch_related("entities__related_symptom").order_by("id")
        if options.get("user"):
            records = records.filter(user__username=options["user"])

        ok = 0
        failed = 0
        for record in records:
            try:
                resp = requests.post(
                    f"{AI_SERVICE_URL}/embed_record",
                    json=build_embed_payload(record),
                    headers=ai_service_headers(),
                    timeout=60
                )
                if resp.status_code == 200:
                    ok += 1
                else:
                    failed += 1
                    self.stdout.write(f"record {record.id} failed with status {resp.status_code}")
            except requests.exceptions.RequestException as e:
                failed += 1
                self.stdout.write(f"record {record.id} failed: {e}")

        self.stdout.write(f"done - {ok} embedded, {failed} failed")
