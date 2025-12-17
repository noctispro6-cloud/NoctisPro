from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
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

        # If user already exists, ensure it can actually log into Django admin (/admin/)
        # and the main app (role/is_verified).
        if User.objects.filter(username=username).exists():
            user = User.objects.get(username=username)
            self.stdout.write(self.style.WARNING(f'User "{username}" already exists! Ensuring admin privileges...'))

            changed = False
            # Promote for Django admin access
            if not getattr(user, 'is_staff', False):
                user.is_staff = True
                changed = True
            if not getattr(user, 'is_superuser', False):
                user.is_superuser = True
                changed = True

            # Ensure app-level admin role + verification
            if hasattr(user, 'role') and getattr(user, 'role', None) != 'admin':
                user.role = 'admin'
                changed = True
            if hasattr(user, 'is_verified') and not getattr(user, 'is_verified', False):
                user.is_verified = True
                changed = True

            if hasattr(user, 'email') and email and not getattr(user, 'email', ''):
                user.email = email
                changed = True

            if changed:
                user.save()
                self.stdout.write(self.style.SUCCESS(f'Updated "{username}" with admin privileges (staff/superuser/verified).'))
            else:
                self.stdout.write(self.style.SUCCESS(f'User "{username}" already has admin privileges.'))
            return

        # Create admin user (as a proper Django superuser so /admin/ login works too)
        user = User.objects.create_superuser(
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