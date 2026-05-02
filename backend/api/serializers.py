from rest_framework import serializers
from django.contrib.auth.models import User
from .models import UserProfile


class UserRegistrationSerializer(serializers.ModelSerializer):
    """handles user registration - needs username, email and password.
    password is write_only so it never shows up in api responses"""

    password = serializers.CharField(write_only=True, min_length=6)
    email = serializers.EmailField(required=True)

    class Meta:
        model = User
        fields = ['username', 'email', 'password']

    def validate_email(self, value):
        # make sure nobody else has this email
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("This email is already registered.")
        return value

    def validate_username(self, value):
        # check if username is taken
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("This username is already taken.")
        return value

    def create(self, validated_data):
        # create_user hashes the password for us
        new_user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            password=validated_data['password']
        )

        # also create their profile for storing allergies etc
        UserProfile.objects.create(user=new_user)

        return new_user


class UserProfileSerializer(serializers.ModelSerializer):
    """serializer for the user profile - returns their info and allergies"""
    id = serializers.IntegerField(source='user.id', read_only=True)
    username = serializers.CharField(source='user.username', read_only=True)
    email = serializers.CharField(source='user.email', read_only=True)

    class Meta:
        model = UserProfile
        fields = ['id', 'username', 'email', 'known_allergies']
