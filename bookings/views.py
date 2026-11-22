import logging

from django.utils import timezone
from django.utils.dateparse import parse_date
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .exceptions import BookingValidationError
from .models import Booking, Room
from .permissions import IsAdminOrReadOnly
from .serializers import BookingCreateSerializer, BookingSerializer, RoomSerializer
from .services import cancel_booking, create_booking, get_availability, is_admin

logger = logging.getLogger("bookings")


class RoomViewSet(viewsets.ModelViewSet):
    """Список комнат для всех, CRUD - только для администратора."""

    serializer_class = RoomSerializer
    permission_classes = [IsAdminOrReadOnly]

    def get_queryset(self):
        queryset = Room.objects.all()
        if not is_admin(self.request.user):
            queryset = queryset.filter(is_active=True)
        return queryset

    def perform_create(self, serializer):
        room = serializer.save()
        logger.info("Комната создана: id=%s name=%s by=%s", room.id, room.name, self.request.user)

    def perform_update(self, serializer):
        room = serializer.save()
        logger.info("Комната изменена: id=%s name=%s by=%s", room.id, room.name, self.request.user)

    def perform_destroy(self, instance):
        # Мягкое удаление: история бронирований сохраняется.
        instance.is_active = False
        instance.save(update_fields=["is_active"])
        logger.info("Комната отключена: id=%s by=%s", instance.id, self.request.user)

    @extend_schema(
        parameters=[OpenApiParameter("date", OpenApiTypes.DATE, description="YYYY-MM-DD")],
        responses=OpenApiTypes.OBJECT,
    )
    @action(detail=True, methods=["get"])
    def availability(self, request, pk=None):
        """Занятость комнаты по часам на дату (по умолчанию - сегодня)."""
        room = self.get_object()
        raw_date = request.query_params.get("date")
        day = parse_date(raw_date) if raw_date else timezone.localdate()
        if day is None:
            raise BookingValidationError("Неверная дата. Формат: YYYY-MM-DD.")
        slots = get_availability(room, day)
        return Response({"room": room.id, "date": day.isoformat(), "slots": slots})


class BookingViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """История бронирований (свои; администратор видит все), создание и отмена."""

    def get_serializer_class(self):
        return BookingCreateSerializer if self.action == "create" else BookingSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Booking.objects.none()
        queryset = Booking.objects.select_related("room", "user")
        if not is_admin(self.request.user):
            queryset = queryset.filter(user=self.request.user)
        room = self.request.query_params.get("room")
        if room:
            if not room.isdigit():
                raise BookingValidationError("Параметр room должен быть числом.")
            queryset = queryset.filter(room_id=int(room))
        return queryset

    @extend_schema(request=BookingCreateSerializer, responses={201: BookingSerializer})
    def create(self, request, *args, **kwargs):
        serializer = BookingCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        booking = create_booking(request.user, **serializer.validated_data)
        return Response(BookingSerializer(booking).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses=BookingSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        booking = cancel_booking(request.user, self.get_object())
        return Response(BookingSerializer(booking).data)
