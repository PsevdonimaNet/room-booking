from datetime import datetime, time, timedelta

from django import forms
from django.conf import settings
from django.utils import timezone

from bookings.models import Room


class RoomForm(forms.ModelForm):
    class Meta:
        model = Room
        fields = ["name", "capacity", "location", "description", "is_active"]
        labels = {
            "name": "Название",
            "capacity": "Вместимость (человек)",
            "location": "Расположение",
            "description": "Описание",
            "is_active": "Доступна для бронирования",
        }
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def clean_capacity(self):
        capacity = self.cleaned_data["capacity"]
        if capacity < 1:
            raise forms.ValidationError("Вместимость должна быть не меньше 1.")
        return capacity


class BookingForm(forms.Form):
    date = forms.DateField(label="Дата", widget=forms.DateInput(attrs={"type": "date"}))
    start_hour = forms.ChoiceField(label="Начало", choices=[])
    duration = forms.ChoiceField(label="Длительность", choices=[])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        hours = range(settings.BOOKING_OPEN_HOUR, settings.BOOKING_CLOSE_HOUR)
        self.fields["start_hour"].choices = [(str(h), f"{h:02d}:00") for h in hours]
        durations = range(settings.BOOKING_MIN_HOURS, settings.BOOKING_MAX_HOURS + 1)
        self.fields["duration"].choices = [(str(d), f"{d} ч") for d in durations]

    def interval(self):
        """Возвращает (start, end) с учётом часового пояса проекта."""
        day = self.cleaned_data["date"]
        hour = int(self.cleaned_data["start_hour"])
        start = timezone.make_aware(datetime.combine(day, time(hour)))
        end = start + timedelta(hours=int(self.cleaned_data["duration"]))
        return start, end
