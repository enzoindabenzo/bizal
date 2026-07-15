from django.urls import path
from . import views

urlpatterns = [
    path('chat/',                views.chat,        name='chatbot-chat'),
    path('handoff/',             views.handoff,     name='chatbot-handoff'),
    path('staff-reply/',         views.staff_reply, name='chatbot-staff-reply'),
    path('poll/<str:session_id>/', views.poll,      name='chatbot-poll'),
]
