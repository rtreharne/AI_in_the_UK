from django.contrib import admin

from .models import Sector, StudentAssignment, WorkshopRun, WorkshopSection, WorkshopSettings, WorkshopVote


@admin.register(WorkshopSection)
class WorkshopSectionAdmin(admin.ModelAdmin):
    list_display = ('order', 'title', 'duration_seconds', 'enabled')
    list_editable = ('duration_seconds', 'enabled')
    ordering = ('order',)


@admin.register(Sector)
class SectorAdmin(admin.ModelAdmin):
    list_display = ('order', 'name')
    list_editable = ('name',)
    ordering = ('order',)


@admin.register(WorkshopSettings)
class WorkshopSettingsAdmin(admin.ModelAdmin):
    list_display = ('predicted_class_size', 'target_group_size', 'updated_at')


@admin.register(WorkshopRun)
class WorkshopRunAdmin(admin.ModelAdmin):
    list_display = ('join_open', 'timer_status', 'current_section', 'end_at', 'beep_enabled', 'updated_at')
    readonly_fields = ('created_at', 'updated_at', 'started_at', 'completed_at')


@admin.register(StudentAssignment)
class StudentAssignmentAdmin(admin.ModelAdmin):
    list_display = ('name', 'group_number', 'sector_name', 'created_at')
    search_fields = ('name', 'sector_name')
    ordering = ('group_number', 'created_at')


@admin.register(WorkshopVote)
class WorkshopVoteAdmin(admin.ModelAdmin):
    list_display = ('sector_name', 'session_rating', 'feedback_text', 'created_at')
    search_fields = ('sector_name', 'feedback_text')
    ordering = ('-created_at',)
