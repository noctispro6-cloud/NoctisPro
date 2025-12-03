from django.core.management.base import BaseCommand
from accounts.models import User

class Command(BaseCommand):
    help = 'List all users for debugging'

    def handle(self, *args, **options):
        users = User.objects.all()
        self.stdout.write(f'Total users: {users.count()}')
        self.stdout.write('-' * 50)
        
        for user in users:
            self.stdout.write(f'Username: {user.username}')
            self.stdout.write(f'Role: {user.role}')
            self.stdout.write(f'Active: {user.is_active}')
            self.stdout.write(f'Verified: {user.is_verified}')
            self.stdout.write(f'Facility: {user.facility}')
            self.stdout.write(f'Created: {user.date_joined}')
            self.stdout.write('-' * 50)