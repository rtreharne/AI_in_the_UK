from django.contrib import admin
from django.urls import path

from workshop import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.display_page, name='display_page'),
    path('join', views.join_page, name='join_page'),
    path('vote', views.vote_page, name='vote_page'),
    path('api/state', views.api_state, name='api_state'),
    path('api/sounds/gong.mp3', views.api_sound_gong, name='api_sound_gong'),
    path('api/sounds/edith.mp3', views.api_sound_edith, name='api_sound_edith'),
    path('api/pin/unlock', views.api_pin_unlock, name='api_pin_unlock'),
    path('api/control/start', views.api_control_start, name='api_control_start'),
    path('api/control/pause', views.api_control_pause, name='api_control_pause'),
    path('api/control/back', views.api_control_back, name='api_control_back'),
    path('api/control/next', views.api_control_next, name='api_control_next'),
    path('api/join/open', views.api_join_open, name='api_join_open'),
    path('api/join/close', views.api_join_close, name='api_join_close'),
    path('api/run/reset', views.api_run_reset, name='api_run_reset'),
    path('api/assignment/claim', views.api_assignment_claim, name='api_assignment_claim'),
    path('api/vote/submit', views.api_vote_submit, name='api_vote_submit'),
    path('api/assignments.csv', views.api_assignments_csv, name='api_assignments_csv'),
    path('api/beep/toggle', views.api_beep_toggle, name='api_beep_toggle'),
    path('api/test/populate-asimov', views.api_test_populate_asimov, name='api_test_populate_asimov'),
]
