from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('workshop', '0002_workshopvote'),
    ]

    operations = [
        migrations.AddField(
            model_name='workshopvote',
            name='feedback_text',
            field=models.CharField(default='', max_length=200),
        ),
        migrations.AddField(
            model_name='workshopvote',
            name='session_rating',
            field=models.PositiveSmallIntegerField(
                default=3,
                validators=[MinValueValidator(1), MaxValueValidator(5)],
            ),
        ),
    ]
