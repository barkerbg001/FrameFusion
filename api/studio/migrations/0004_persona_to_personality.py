"""Map the old model-route names stored on messages and events to personalities.

Messages written by the old planner persona (Framey) read like the Creative
Partner; the old production persona (Reel) read like the Director.
"""

from django.db import migrations

MAPPING = {"planner": "creative_partner", "production": "director"}


def forwards(apps, schema_editor):
    for model_name in ("Message", "JobEvent"):
        model = apps.get_model("studio", model_name)
        for old, new in MAPPING.items():
            model.objects.filter(persona=old).update(persona=new)


def backwards(apps, schema_editor):
    for model_name in ("Message", "JobEvent"):
        model = apps.get_model("studio", model_name)
        for old, new in MAPPING.items():
            model.objects.filter(persona=new).update(persona=old)


class Migration(migrations.Migration):
    dependencies = [("studio", "0003_orchestrator_tasks_assets")]

    operations = [migrations.RunPython(forwards, backwards)]
