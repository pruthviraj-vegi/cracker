from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('user', '0004_remove_customuser_role_and_more'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.DeleteModel(name='LoginEvent'),
                migrations.DeleteModel(name='UnauthorizedAccess'),
            ],
        )
    ]
