import logging

from django.utils import timezone
from django.utils.dateparse import parse_date
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .exceptions import BookingValidationError, PermissionDeniedError
from .models import Booking, Room
from .permissions import IsAdminOrReadOnly
from .reports import csv_response, filter_bookings, parse_filters
from .serializers import BookingCreateSerializer, BookingSerializer, RoomSerializer
from .services import (
    approve_booking,
    cancel_booking,
    create_booking,
    get_availability,
    is_admin,
    reject_booking,
)

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
        status_value = self.request.query_params.get("status")
        if status_value:
            if status_value not in Booking.Status.values:
                raise BookingValidationError("Неизвестный статус бронирования.")
            queryset = queryset.filter(status=status_value)
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

    @extend_schema(request=None, responses=BookingSerializer)
    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        """Подтвердить бронирование VIP-комнаты (только администратор)."""
        booking = approve_booking(request.user, self.get_object())
        return Response(BookingSerializer(booking).data)

    @extend_schema(request=None, responses=BookingSerializer)
    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        """Отклонить бронирование VIP-комнаты (только администратор)."""
        booking = reject_booking(request.user, self.get_object())
        return Response(BookingSerializer(booking).data)

    @extend_schema(
        parameters=[
            OpenApiParameter("date_from", OpenApiTypes.DATE, description="YYYY-MM-DD"),
            OpenApiParameter("date_to", OpenApiTypes.DATE, description="YYYY-MM-DD"),
            OpenApiParameter("room", OpenApiTypes.INT),
            OpenApiParameter("status", OpenApiTypes.STR),
        ],
        responses=OpenApiTypes.BINARY,
    )
    @action(detail=False, methods=["get"])
    def export(self, request):
        """Экспорт бронирований в CSV с фильтрами (только администратор)."""
        if not is_admin(request.user):
            raise PermissionDeniedError("Экспорт доступен только администраторам.")
        filters = parse_filters(request.query_params)
        queryset = filter_bookings(Booking.objects.all(), filters)
        logger.info("Экспорт CSV: by=%s filters=%s", request.user.username, filters)
        return csv_response(queryset)
