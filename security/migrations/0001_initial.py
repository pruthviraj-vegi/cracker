from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('user', '0005_remove_loginevent_unauthorizedaccess'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.CreateModel(
                    name='LoginEvent',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('event_type', models.CharField(choices=[('LOGIN', 'Login'), ('LOGOUT', 'Logout')], max_length=10)),
                        ('occurred_at', models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                        ('ip_address', models.GenericIPAddressField(blank=True, null=True)),
                        ('user_agent', models.CharField(blank=True, max_length=512, null=True)),
                        ('session_key', models.CharField(blank=True, max_length=40, null=True)),
                        ('user', models.ForeignKey(
                            on_delete=django.db.models.deletion.CASCADE,
                            related_name='login_events',
                            to=settings.AUTH_USER_MODEL,
                        )),
                    ],
                    options={
                        'ordering': ('-occurred_at',),
                        'db_table': 'user_loginevent',
                        'indexes': [
                            models.Index(fields=['user', 'occurred_at'], name='user_logine_user_id_fd72dc_idx'),
                            models.Index(fields=['event_type', 'occurred_at'], name='user_logine_event_t_27a79d_idx'),
                        ],
                    },
                ),
                migrations.CreateModel(
                    name='UnauthorizedAccess',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('timestamp', models.DateTimeField(auto_now_add=True)),
                        ('view_name', models.CharField(help_text='Name of the view/function', max_length=255)),
                        ('required_roles', models.CharField(help_text='Roles that were required', max_length=255)),
                        ('ip_address', models.GenericIPAddressField(blank=True, null=True)),
                        ('url_path', models.CharField(blank=True, max_length=500, null=True)),
                        ('user', models.ForeignKey(
                            blank=True,
                            help_text='User who attempted unauthorized access',
                            null=True,
                            on_delete=django.db.models.deletion.SET_NULL,
                            to='user.CustomUser',
                        )),
                    ],
                    options={
                        'verbose_name': 'Unauthorized Access Attempt',
                        'verbose_name_plural': 'Unauthorized Access Attempts',
                        'ordering': ['-timestamp'],
                        'db_table': 'user_unauthorizedaccess',
                    },
                ),
            ],
        )
    ]
