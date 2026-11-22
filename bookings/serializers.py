from rest_framework import serializers

from .models import Booking, Room


class RoomSerializer(serializers.ModelSerializer):
    capacity = serializers.IntegerField(min_value=1, max_value=1000)

    class Meta:
        model = Room
        fields = ["id", "name", "capacity", "location", "description", "is_active", "is_vip"]


class BookingSerializer(serializers.ModelSerializer):
    room_name = serializers.CharField(source="room.name", read_only=True)
    user = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = Booking
        fields = [
            "id",
            "room",
            "room_name",
            "user",
            "start",
            "end",
            "status",
            "created_at",
            "cancelled_at",
        ]
        read_only_fields = fields


class BookingCreateSerializer(serializers.Serializer):
    room = serializers.PrimaryKeyRelatedField(queryset=Room.objects.all())
    start = serializers.DateTimeField()
    end = serializers.DateTimeField()
