from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from accounts.models import Facility
from django.conf import settings

User = get_user_model()

class Command(BaseCommand):
    help = 'Create an admin user for the PACS system'

    def add_arguments(self, parser):
        parser.add_argument('--username', type=str, help='Username for the admin user', default='admin')
        parser.add_argument('--email', type=str, help='Email for the admin user (defaults to admin@<DOMAIN_NAME>)', default='')
        parser.add_argument('--password', type=str, help='Password for the admin user', default='admin123')
        parser.add_argument('--first-name', type=str, help='First name', default='System')
        parser.add_argument('--last-name', type=str, help='Last name', default='Administrator')

    def handle(self, *args, **options):
        username = options['username']
        email = options['email'] or f"admin@{getattr(settings, 'DOMAIN_NAME', '') or 'noctis-pro.com'}"
        password = options['password']
        first_name = options['first_name']
        last_name = options['last_name']

        # Check if user already exists
        if User.objects.filter(username=username).exists():
            self.stdout.write(
                self.style.WARNING(f'User "{username}" already exists!')
            )
            user = User.objects.get(username=username)
            if user.role != 'admin':
                user.role = 'admin'
                user.save()
                self.stdout.write(
                    self.style.SUCCESS(f'Updated user "{username}" to admin role!')
                )
            return

        # Create admin user
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            role='admin',
            is_verified=True
        )

        self.stdout.write(
            self.style.SUCCESS(f'Successfully created admin user "{username}"')
        )
        self.stdout.write(f'Username: {username}')
        self.stdout.write(f'Email: {email}')
        self.stdout.write(f'Password: {password}')
        self.stdout.write(
            self.style.WARNING('Please change the default password after first login!')
        )