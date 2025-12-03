from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError
from django.contrib.auth.password_validation import validate_password
from accounts.models import User, Facility
import re


class CustomUserCreationForm(UserCreationForm):
    """Enhanced user creation form with role-based validation"""
    
    email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={
            'class': 'form-control form-control-medical',
            'placeholder': 'user@example.com'
        })
    )
    first_name = forms.CharField(
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-medical',
            'placeholder': 'First name'
        })
    )
    last_name = forms.CharField(
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-medical',
            'placeholder': 'Last name'
        })
    )
    role = forms.ChoiceField(
        choices=User.USER_ROLES,
        initial='facility',
        widget=forms.Select(attrs={
            'class': 'form-select form-control-medical',
            'required': True
        })
    )
    facility = forms.ModelChoiceField(
        queryset=Facility.objects.filter(is_active=True),
        required=False,
        empty_label="-- No Facility Assignment --",
        widget=forms.Select(attrs={
            'class': 'form-select form-control-medical'
        })
    )
    phone = forms.CharField(
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-medical',
            'placeholder': '+1 (555) 123-4567'
        })
    )
    license_number = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-medical',
            'placeholder': 'Professional license number'
        })
    )
    specialization = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-medical',
            'placeholder': 'e.g., Neuroradiology, Cardiac Imaging'
        })
    )

    class Meta:
        model = User
        fields = ('username', 'email', 'first_name', 'last_name', 'password1', 'password2')
        widgets = {
            'username': forms.TextInput(attrs={
                'class': 'form-control form-control-medical',
                'placeholder': 'Enter unique username'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Update password field widgets
        self.fields['password1'].widget.attrs.update({
            'class': 'form-control form-control-medical',
            'placeholder': 'Minimum 8 characters'
        })
        self.fields['password2'].widget.attrs.update({
            'class': 'form-control form-control-medical',
            'placeholder': 'Re-enter password'
        })
        
        # Update facility queryset to ensure we have latest active facilities
        self.fields['facility'].queryset = Facility.objects.filter(is_active=True).order_by('name')

    def clean_username(self):
        username = self.cleaned_data.get('username')
        if not username:
            raise ValidationError("Username is required.")
        
        # Check if username already exists
        if User.objects.filter(username=username).exists():
            raise ValidationError("A user with this username already exists.")
        
        # Validate username format
        if not re.match(r'^[a-zA-Z0-9._-]+$', username):
            raise ValidationError("Username can only contain letters, numbers, dots, underscores, and hyphens.")
        
        if len(username) < 3:
            raise ValidationError("Username must be at least 3 characters long.")
        
        return username

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if email:
            # Check if email already exists
            if User.objects.filter(email=email).exists():
                raise ValidationError("A user with this email address already exists.")
        return email

    def clean_phone(self):
        phone = self.cleaned_data.get('phone')
        if phone:
            # Remove common phone formatting
            cleaned_phone = re.sub(r'[^\d+\-\(\)\s]', '', phone)
            if len(cleaned_phone.replace(' ', '').replace('-', '').replace('(', '').replace(')', '').replace('+', '')) < 10:
                raise ValidationError("Please enter a valid phone number.")
        return phone

    def clean(self):
        cleaned_data = super().clean()
        role = cleaned_data.get('role')
        facility = cleaned_data.get('facility')
        
        # Facility users must have a facility assigned
        if role == 'facility' and not facility:
            raise ValidationError({
                'facility': 'Facility assignment is required for Facility Users.'
            })
        
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data.get('email', '')
        user.first_name = self.cleaned_data.get('first_name', '')
        user.last_name = self.cleaned_data.get('last_name', '')
        user.role = self.cleaned_data.get('role', 'facility')
        user.phone = self.cleaned_data.get('phone', '')
        user.license_number = self.cleaned_data.get('license_number', '')
        user.specialization = self.cleaned_data.get('specialization', '')
        user.is_verified = True  # New users are verified by default
        user.is_active = True   # New users are active by default
        
        if commit:
            user.save()
            # Set facility after user is saved
            facility = self.cleaned_data.get('facility')
            if facility:
                user.facility = facility
                user.save()
        
        return user


class CustomUserUpdateForm(forms.ModelForm):
    """Form for updating existing users"""
    
    password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control form-control-medical',
            'placeholder': 'Leave blank to keep current password'
        }),
        help_text="Leave blank to keep the current password"
    )
    confirm_password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control form-control-medical',
            'placeholder': 'Confirm new password'
        })
    )

    class Meta:
        model = User
        fields = [
            'username', 'email', 'first_name', 'last_name', 'role', 'facility',
            'phone', 'license_number', 'specialization', 'is_active', 'is_verified'
        ]
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control form-control-medical'}),
            'email': forms.EmailInput(attrs={'class': 'form-control form-control-medical'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control form-control-medical'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control form-control-medical'}),
            'role': forms.Select(attrs={'class': 'form-select form-control-medical'}),
            'facility': forms.Select(attrs={'class': 'form-select form-control-medical'}),
            'phone': forms.TextInput(attrs={'class': 'form-control form-control-medical'}),
            'license_number': forms.TextInput(attrs={'class': 'form-control form-control-medical'}),
            'specialization': forms.TextInput(attrs={'class': 'form-control form-control-medical'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_verified': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['facility'].queryset = Facility.objects.filter(is_active=True).order_by('name')
        self.fields['facility'].required = False

    def clean(self):
        cleaned_data = super().clean()
        role = cleaned_data.get('role')
        facility = cleaned_data.get('facility')
        password = cleaned_data.get('password')
        confirm_password = cleaned_data.get('confirm_password')
        
        # Facility users must have a facility assigned
        if role == 'facility' and not facility:
            raise ValidationError({
                'facility': 'Facility assignment is required for Facility Users.'
            })
        
        # Password validation if provided
        if password:
            if password != confirm_password:
                raise ValidationError({
                    'confirm_password': 'Passwords do not match.'
                })
            
            # Validate password strength
            try:
                validate_password(password)
            except ValidationError as e:
                raise ValidationError({
                    'password': e.messages
                })
        
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        
        # Update password if provided
        password = self.cleaned_data.get('password')
        if password:
            user.set_password(password)
        
        if commit:
            user.save()
        
        return user


class FacilityForm(forms.ModelForm):
    """Enhanced facility creation/update form"""
    
    create_facility_user = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        help_text="Create a facility user account for this facility"
    )
    facility_username = forms.CharField(
        required=False,
        max_length=150,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-medical',
            'placeholder': 'Defaults to AE Title if blank'
        }),
        help_text="Username for the facility user account"
    )
    facility_email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={
            'class': 'form-control form-control-medical',
            'placeholder': 'facility@example.com'
        }),
        help_text="Email for the facility user account"
    )
    facility_password = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-medical',
            'placeholder': 'Auto-generates if left blank'
        }),
        help_text="Password for the facility user account (auto-generated if blank)"
    )

    class Meta:
        model = Facility
        fields = ['name', 'address', 'phone', 'email', 'license_number', 'ae_title', 'letterhead', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control form-control-medical',
                'placeholder': 'Facility name'
            }),
            'address': forms.Textarea(attrs={
                'class': 'form-control form-control-medical',
                'rows': 3,
                'placeholder': 'Full facility address'
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-control form-control-medical',
                'placeholder': '+1 (555) 123-4567'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-control form-control-medical',
                'placeholder': 'facility@example.com'
            }),
            'license_number': forms.TextInput(attrs={
                'class': 'form-control form-control-medical',
                'placeholder': 'Facility license number'
            }),
            'ae_title': forms.TextInput(attrs={
                'class': 'form-control form-control-medical',
                'placeholder': 'Auto-generated from name if blank',
                'maxlength': 16
            }),
            'letterhead': forms.FileInput(attrs={
                'class': 'form-control form-control-medical',
                'accept': 'image/*'
            }),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def clean_name(self):
        name = self.cleaned_data.get('name')
        if not name or not name.strip():
            raise ValidationError("Facility name is required.")
        return name.strip()

    def clean_license_number(self):
        license_number = self.cleaned_data.get('license_number')
        if not license_number or not license_number.strip():
            raise ValidationError("License number is required.")
        
        # Check if license number already exists (excluding current instance in edit mode)
        existing = Facility.objects.filter(license_number=license_number.strip())
        if self.instance.pk:
            existing = existing.exclude(pk=self.instance.pk)
        
        if existing.exists():
            raise ValidationError("A facility with this license number already exists.")
        
        return license_number.strip()

    def clean_address(self):
        address = self.cleaned_data.get('address')
        if not address or not address.strip():
            raise ValidationError("Address is required.")
        return address.strip()

    def clean_ae_title(self):
        ae_title = self.cleaned_data.get('ae_title', '').strip()
        name = self.cleaned_data.get('name', '')
        
        if not ae_title and name:
            # Auto-generate from name
            ae_title = self._standardize_aetitle(name)
        elif ae_title:
            # Validate provided AE title
            ae_title = self._standardize_aetitle(ae_title)
        
        if ae_title:
            # Check if AE title already exists (excluding current instance)
            existing = Facility.objects.filter(ae_title__iexact=ae_title)
            if self.instance.pk:
                existing = existing.exclude(pk=self.instance.pk)
            
            if existing.exists():
                # Generate unique AE title
                base = ae_title
                suffix = 1
                while existing.exists():
                    tail = f"_{suffix}"
                    ae_title = (base[:16-len(tail)] + tail)[:16]
                    existing = Facility.objects.filter(ae_title__iexact=ae_title)
                    if self.instance.pk:
                        existing = existing.exclude(pk=self.instance.pk)
                    suffix += 1
                    if suffix > 99:
                        break
        
        return ae_title

    def clean_facility_username(self):
        username = self.cleaned_data.get('facility_username', '').strip()
        create_user = self.cleaned_data.get('create_facility_user', False)
        
        if create_user and username:
            # Check if username already exists
            if User.objects.filter(username=username).exists():
                raise ValidationError("A user with this username already exists.")
            
            # Validate username format
            if not re.match(r'^[a-zA-Z0-9._-]+$', username):
                raise ValidationError("Username can only contain letters, numbers, dots, underscores, and hyphens.")
        
        return username

    def clean_facility_email(self):
        email = self.cleaned_data.get('facility_email', '').strip()
        create_user = self.cleaned_data.get('create_facility_user', False)
        
        if create_user and email:
            # Check if email already exists
            if User.objects.filter(email=email).exists():
                raise ValidationError("A user with this email address already exists.")
        
        return email

    def _standardize_aetitle(self, source):
        """Generate a DICOM-compliant AE Title"""
        base = re.sub(r"[^A-Z0-9 ]+", "", (source or "").upper()).strip().replace(" ", "_") or "FACILITY"
        return base[:16]

    def save(self, commit=True):
        facility = super().save(commit=commit)
        return facility


class BulkUserActionForm(forms.Form):
    """Form for bulk user actions"""
    ACTION_CHOICES = [
        ('activate', 'Activate'),
        ('deactivate', 'Deactivate'),
        ('verify', 'Verify'),
        ('unverify', 'Unverify'),
        ('delete', 'Delete'),
    ]
    
    action = forms.ChoiceField(choices=ACTION_CHOICES)
    user_ids = forms.CharField(widget=forms.HiddenInput())
    
    def clean_user_ids(self):
        user_ids = self.cleaned_data.get('user_ids', '')
        try:
            ids = [int(id.strip()) for id in user_ids.split(',') if id.strip()]
            if not ids:
                raise ValidationError("No users selected.")
            return ids
        except ValueError:
            raise ValidationError("Invalid user IDs.")


class BulkFacilityActionForm(forms.Form):
    """Form for bulk facility actions"""
    ACTION_CHOICES = [
        ('activate', 'Activate'),
        ('deactivate', 'Deactivate'),
        ('delete', 'Delete'),
    ]
    
    action = forms.ChoiceField(choices=ACTION_CHOICES)
    facility_ids = forms.CharField(widget=forms.HiddenInput())
    
    def clean_facility_ids(self):
        facility_ids = self.cleaned_data.get('facility_ids', '')
        try:
            ids = [int(id.strip()) for id in facility_ids.split(',') if id.strip()]
            if not ids:
                raise ValidationError("No facilities selected.")
            return ids
        except ValueError:
            raise ValidationError("Invalid facility IDs.")