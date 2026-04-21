from __future__ import annotations

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class WorkshopSection(models.Model):
    order = models.PositiveIntegerField(unique=True)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    duration_seconds = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    enabled = models.BooleanField(default=True)

    class Meta:
        ordering = ['order']

    def __str__(self) -> str:
        return f"{self.order}. {self.title}"


class Sector(models.Model):
    order = models.PositiveIntegerField(unique=True)
    name = models.CharField(max_length=200, unique=True)

    class Meta:
        ordering = ['order']

    def __str__(self) -> str:
        return self.name


class WorkshopSettings(models.Model):
    singleton_key = models.PositiveSmallIntegerField(default=1, unique=True, editable=False)
    predicted_class_size = models.PositiveIntegerField(default=40, validators=[MinValueValidator(1)])
    target_group_size = models.PositiveIntegerField(default=5, validators=[MinValueValidator(1)])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return 'Workshop Settings'

    @classmethod
    def get_solo(cls) -> 'WorkshopSettings':
        obj, _ = cls.objects.get_or_create(singleton_key=1)
        return obj


class WorkshopRun(models.Model):
    TIMER_READY = 'ready'
    TIMER_RUNNING = 'running'
    TIMER_PAUSED = 'paused'
    TIMER_COMPLETED = 'completed'

    TIMER_STATUS_CHOICES = [
        (TIMER_READY, 'Ready'),
        (TIMER_RUNNING, 'Running'),
        (TIMER_PAUSED, 'Paused'),
        (TIMER_COMPLETED, 'Completed'),
    ]

    singleton_key = models.PositiveSmallIntegerField(default=1, unique=True, editable=False)
    join_open = models.BooleanField(default=False)
    timer_status = models.CharField(max_length=16, choices=TIMER_STATUS_CHOICES, default=TIMER_READY)
    current_section = models.ForeignKey(
        WorkshopSection,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='active_runs',
    )
    end_at = models.DateTimeField(null=True, blank=True)
    paused_remaining_seconds = models.PositiveIntegerField(default=0)
    beep_enabled = models.BooleanField(default=False)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return 'Active Workshop Run'

    @classmethod
    def get_solo(cls) -> 'WorkshopRun':
        obj, _ = cls.objects.get_or_create(singleton_key=1)
        return obj

    def reset(self) -> None:
        self.join_open = False
        self.timer_status = self.TIMER_READY
        self.current_section = None
        self.end_at = None
        self.paused_remaining_seconds = 0
        self.started_at = None
        self.completed_at = None
        self.save()


class StudentAssignment(models.Model):
    name = models.CharField(max_length=120)
    normalized_name = models.CharField(max_length=120, unique=True)
    group_number = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    sector_name = models.CharField(max_length=240)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['group_number', 'created_at']

    def __str__(self) -> str:
        return f"{self.name} -> Group {self.group_number} ({self.sector_name})"

    @staticmethod
    def normalize_name(name: str) -> str:
        return ' '.join(name.strip().split()).lower()

    def save(self, *args, **kwargs):
        self.normalized_name = self.normalize_name(self.name)
        super().save(*args, **kwargs)


class WorkshopVote(models.Model):
    sector_name = models.CharField(max_length=200)
    session_rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        default=3,
    )
    feedback_text = models.CharField(max_length=200, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self) -> str:
        return f"Vote: {self.sector_name}"
