from __future__ import annotations

import json
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from smartInterviewApp.api.serializers import (
    ExotelWebhookSerializer,
    Msg91WebhookSerializer,
    NotificationResponseSerializer,
    NotificationSendSerializer,
    OtpRequestSerializer,
    OtpResendSerializer,
    OtpVerifySerializer,
)
from smartInterviewApp.api.throttles import OtpRateThrottle
from smartInterviewApp.models import (
    AptitudeAnswer,
    AptitudeIntegrityEvent,
    AptitudeTestAssignment,
    AptitudeTestQuestion,
    AptitudeTestTemplate,
    Interview,
    Notification,
    Vacancies,
)
from smartInterviewApp.notifications.services import NotificationService
from smartInterviewApp.otp.services import OtpService
from smartInterviewApp.services.aptitude_assignments import (
    AptitudeAssignmentError,
    create_aptitude_assignment,
    get_default_aptitude_template,
    validate_template_readiness,
)
from smartInterviewApp.services.aptitude_scoring import mark_aptitude_assignment_expired_if_needed, score_assignment
from smartInterviewApp.services.interview_calls import InterviewCallService
from smartInterviewApp.webhooks.services import WebhookService


def api_response(success, data=None, error=None, status_code=status.HTTP_200_OK):
    return Response({'success': success, 'data': data, 'error': error}, status=status_code)


def get_user_role(user):
    return getattr(getattr(user, 'profile', None), 'role', '')


def is_aptitude_workspace_user(user):
    if not user or not user.is_authenticated:
        return False
    if user.is_staff or user.is_superuser:
        return True
    return get_user_role(user) in {'admin', 'recruiter'}


def user_can_access_vacancy(user, vacancy):
    if not vacancy:
        return False
    if user.is_staff or user.is_superuser:
        return True
    if getattr(vacancy, 'admin_id', None) == user.id:
        return True
    try:
        if vacancy.recruiter.filter(id=user.id).exists():
            return True
    except Exception:
        pass
    return False


def user_can_access_interview(user, interview):
    if not interview:
        return False
    if user.is_staff or user.is_superuser:
        return True
    return (
        getattr(interview, 'recruiter_id', None) == user.id
        or getattr(interview, 'hr_id', None) == user.id
    )


def user_can_access_assignment(user, assignment):
    if user.is_staff or user.is_superuser:
        return True
    if getattr(assignment, 'created_by_id', None) == user.id:
        return True
    if assignment.vacancy_id and user_can_access_vacancy(user, assignment.vacancy):
        return True
    if assignment.interview_id and user_can_access_interview(user, assignment.interview):
        return True
    return False


def serialize_aptitude_template(template):
    if not template:
        return None
    return {
        'id': template.id,
        'title': template.title,
        'role_type': template.role_type,
        'role_family': template.role_family,
        'duration_minutes': template.duration_minutes,
        'total_questions': template.total_questions,
        'total_marks': float(template.total_marks),
        'passing_score_percent': float(template.passing_score_percent),
    }


def serialize_aptitude_assignment(assignment, questions_created=None):
    payload = {
        'id': assignment.id,
        'title': assignment.title,
        'public_token': assignment.public_token,
        'status': assignment.status,
        'candidate_id': assignment.candidate_id,
        'vacancy_id': assignment.vacancy_id,
        'interview_id': assignment.interview_id,
        'template_id': assignment.template_id,
        'duration_minutes': assignment.duration_minutes,
        'total_questions': assignment.total_questions,
        'total_marks': float(assignment.total_marks),
        'passing_score_percent': float(assignment.passing_score_percent),
        'scheduled_at': assignment.scheduled_at.isoformat() if assignment.scheduled_at else None,
        'started_at': assignment.started_at.isoformat() if assignment.started_at else None,
        'expires_at': assignment.expires_at.isoformat() if assignment.expires_at else None,
    }
    if questions_created is not None:
        payload['questions_created'] = questions_created
    return payload


def serialize_aptitude_result(result):
    if not result:
        return None
    return {
        'id': result.id,
        'assignment_id': result.assignment_id,
        'total_questions': result.total_questions,
        'attempted_questions': result.attempted_questions,
        'correct_answers': result.correct_answers,
        'wrong_answers': result.wrong_answers,
        'skipped_questions': result.skipped_questions,
        'total_marks': float(result.total_marks),
        'marks_obtained': float(result.marks_obtained),
        'score_percent': float(result.score_percent),
        'passed': result.passed,
        'problem_solving_score': float(result.problem_solving_score),
        'communication_score': float(result.communication_score),
        'technical_score': float(result.technical_score),
        'section_breakdown': result.section_breakdown,
        'skill_breakdown': result.skill_breakdown,
        'integrity_summary': result.integrity_summary,
    }


def get_assignment_result(assignment):
    try:
        return assignment.result
    except AptitudeTestAssignment.result.RelatedObjectDoesNotExist:
        return None


def summarize_integrity_events(assignment):
    events_by_type = {}
    for event in assignment.integrity_events.all():
        events_by_type[event.event_type] = events_by_type.get(event.event_type, 0) + 1
    total_events = sum(events_by_type.values())
    if total_events >= 8:
        risk_level = 'high'
    elif total_events >= 3:
        risk_level = 'medium'
    else:
        risk_level = 'low'
    return {'total_events': total_events, 'events_by_type': events_by_type, 'risk_level': risk_level}


def parse_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {'1', 'true', 'yes', 'on'}
    return bool(value)


def resolve_optional_int_model(model, value, *, error_label, queryset=None):
    if value in (None, '', 'null'):
        return None, None
    try:
        lookup_id = int(value)
    except (TypeError, ValueError):
        return None, f'{error_label} is invalid.'
    qs = queryset or model.objects
    obj = qs.filter(id=lookup_id).first()
    if not obj:
        return None, f'{error_label} was not found.'
    return obj, None


def get_assignment_by_token(public_token):
    return (
        AptitudeTestAssignment.objects
        .select_related('candidate', 'vacancy', 'interview', 'template', 'created_by')
        .filter(public_token=public_token)
        .first()
    )


class AptitudeRuntimeAccessError(Exception):
    def __init__(self, code, message, status_code):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def aptitude_runtime_error_response(exc):
    return api_response(
        False,
        data={'code': exc.code},
        error={'code': exc.code, 'message': exc.message},
        status_code=exc.status_code,
    )


def resolve_aptitude_runtime_assignment(request, public_token):
    assignment = get_assignment_by_token(public_token)
    if not assignment:
        raise AptitudeRuntimeAccessError(
            'assignment_not_found',
            'Aptitude assignment not found.',
            status.HTTP_404_NOT_FOUND,
        )

    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        raise AptitudeRuntimeAccessError(
            'authentication_required',
            'Authentication is required to access this aptitude assignment.',
            status.HTTP_401_UNAUTHORIZED,
        )

    assigned_candidate_id = assignment.candidate_id
    if not assigned_candidate_id and assignment.interview_id:
        assigned_candidate_id = getattr(assignment.interview, 'candidate_id', None)

    if not assigned_candidate_id or user.id != assigned_candidate_id:
        raise AptitudeRuntimeAccessError(
            'candidate_not_assigned',
            'This aptitude assignment is not assigned to the authenticated candidate.',
            status.HTTP_403_FORBIDDEN,
        )

    return assignment


def runtime_time_remaining_seconds(assignment, *, now=None):
    if not assignment.expires_at:
        return None
    now = now or timezone.now()
    return max(0, int((assignment.expires_at - now).total_seconds()))


def runtime_answered_count(assignment):
    return assignment.answers.count()


def runtime_question_count(assignment):
    return assignment.questions.count()


def runtime_question_totals(assignment):
    questions = list(assignment.questions.select_related('section'))
    total_marks = sum((question.marks for question in questions), 0)
    return {
        'question_count': len(questions),
        'total_marks': total_marks,
    }


def candidate_display_name(candidate):
    if not candidate:
        return None
    full_name = candidate.get_full_name().strip()
    return full_name or candidate.username or None


def serialize_runtime_section_config(assignment):
    config = {
        code: dict(value)
        for code, value in (assignment.section_config or {}).items()
        if isinstance(value, dict)
    }
    actual_counts = {}
    for question in assignment.questions.select_related('section'):
        section = question.section
        code = section.code if section else 'unassigned'
        actual_counts[code] = actual_counts.get(code, 0) + 1
        if code not in config:
            config[code] = {
                'section_name': section.name if section else 'Unassigned',
                'order_index': section.default_order if section else 0,
                'difficulty_mix': {},
                'marks_per_question': float(question.marks),
            }

    for code, item in config.items():
        item['configured_question_count'] = item.get('question_count', 0)
        item['question_count'] = actual_counts.get(code, 0)
    return config


def serialize_runtime_status(assignment):
    now = timezone.now()
    time_remaining = runtime_time_remaining_seconds(assignment, now=now)
    status_value = assignment.status
    totals = runtime_question_totals(assignment)
    question_count = totals['question_count']
    answered_count = runtime_answered_count(assignment)
    candidate = assignment.candidate
    return {
        'id': assignment.id,
        'title': assignment.title,
        'status': status_value,
        'duration_minutes': assignment.duration_minutes,
        'configured_total_questions': assignment.total_questions,
        'total_questions': question_count,
        'configured_total_marks': float(assignment.total_marks),
        'total_marks': float(totals['total_marks']),
        'passing_score_percent': float(assignment.passing_score_percent),
        'started_at': assignment.started_at.isoformat() if assignment.started_at else None,
        'submitted_at': assignment.submitted_at.isoformat() if assignment.submitted_at else None,
        'expires_at': assignment.expires_at.isoformat() if assignment.expires_at else None,
        'time_remaining_seconds': time_remaining,
        'answered_count': answered_count,
        'question_count': question_count,
        'can_start': status_value == AptitudeTestAssignment.Status.ASSIGNED,
        'can_resume': status_value == AptitudeTestAssignment.Status.IN_PROGRESS and (time_remaining is None or time_remaining > 0),
        'can_submit': status_value == AptitudeTestAssignment.Status.IN_PROGRESS and (time_remaining is None or time_remaining > 0),
        'candidate_name': candidate_display_name(candidate),
        'candidate_email': (candidate.email or None) if candidate else None,
    }


def serialize_runtime_question(question, answer=None):
    section = question.section
    return {
        'id': question.id,
        'order_index': question.order_index,
        'section': {
            'code': section.code if section else '',
            'name': section.name if section else '',
        },
        'question_type': question.question_type,
        'question_text': question.question_text,
        'question_html': question.question_html,
        'question_media': question.question_media,
        'options': question.options,
        'marks': float(question.marks),
        'answer_payload': answer.answer_payload if answer else {},
    }


def serialize_runtime_result(result, assignment):
    if not result:
        return None
    return {
        'score_percent': float(result.score_percent),
        'passed': result.passed,
        'submitted_at': assignment.submitted_at.isoformat() if assignment.submitted_at else None,
        'status': assignment.status,
    }


class RequestOtpApi(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [OtpRateThrottle]
    throttle_scope = 'otp_request'

    def post(self, request):
        serializer = OtpRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        service = OtpService()
        result = service.request_otp(
            phone=serializer.validated_data['phone'],
            purpose=serializer.validated_data['purpose'],
            user=request.user if request.user.is_authenticated else None,
            metadata={'ip': request.META.get('REMOTE_ADDR', '')},
        )
        code = status.HTTP_200_OK if result.get('success') else status.HTTP_429_TOO_MANY_REQUESTS
        return Response({'success': result.get('success', False), 'error': None if result.get('success') else result.get('message'), 'data': result}, status=code)


class VerifyOtpApi(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [OtpRateThrottle]
    throttle_scope = 'otp_verify'

    def post(self, request):
        serializer = OtpVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        service = OtpService()
        result = service.verify_otp(
            phone=serializer.validated_data['phone'],
            otp=serializer.validated_data['otp'],
            purpose=serializer.validated_data['purpose'],
        )
        code = status.HTTP_200_OK if result.get('success') else status.HTTP_400_BAD_REQUEST
        return Response({'success': result.get('success', False), 'error': None if result.get('success') else result.get('message'), 'data': result}, status=code)


class ResendOtpApi(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [OtpRateThrottle]
    throttle_scope = 'otp_resend'

    def post(self, request):
        serializer = OtpResendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        service = OtpService()
        result = service.resend_otp(
            phone=serializer.validated_data['phone'],
            purpose=serializer.validated_data['purpose'],
            user=request.user if request.user.is_authenticated else None,
            metadata={'ip': request.META.get('REMOTE_ADDR', '')},
        )
        code = status.HTTP_200_OK if result.get('success') else status.HTTP_429_TOO_MANY_REQUESTS
        return Response({'success': result.get('success', False), 'error': None if result.get('success') else result.get('message'), 'data': result}, status=code)


class SendNotificationApi(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = NotificationSendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user
        if serializer.validated_data.get('user_id'):
            user = User.objects.filter(id=serializer.validated_data['user_id']).first()

        service = NotificationService()
        notification = service.send_notification(
            event_type=serializer.validated_data['event_type'],
            severity=serializer.validated_data['severity'],
            user=user,
            payload=serializer.validated_data['payload'],
            idempotency_key=serializer.validated_data.get('idempotency_key'),
        )
        return Response(
            {
                'success': True,
                'error': None,
                'data': NotificationResponseSerializer(notification).data,
            },
            status=status.HTTP_201_CREATED,
        )


class NotificationDetailApi(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, notification_id: int):
        notification = (
            request.user.notifications.filter(id=notification_id).first()
            if not request.user.is_superuser
            else None
        )
        if request.user.is_superuser:
            notification = Notification.objects.filter(id=notification_id).first()

        if not notification:
            return Response({'success': False, 'error': 'Notification not found.', 'data': None}, status=status.HTTP_404_NOT_FOUND)

        return Response({'success': True, 'error': None, 'data': NotificationResponseSerializer(notification).data})


class AptitudeTemplateReadinessApi(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, template_id: int):
        if not is_aptitude_workspace_user(request.user):
            return api_response(False, error='Aptitude workspace access is required.', status_code=status.HTTP_403_FORBIDDEN)

        template = AptitudeTestTemplate.objects.filter(id=template_id, is_active=True).first()
        if not template:
            return api_response(False, error='Aptitude template not found.', status_code=status.HTTP_404_NOT_FOUND)

        return api_response(True, data={
            'template': serialize_aptitude_template(template),
            'readiness': validate_template_readiness(template),
        })


class AptitudeTemplateListApi(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not is_aptitude_workspace_user(request.user):
            return api_response(False, error='Aptitude workspace access is required.', status_code=status.HTTP_403_FORBIDDEN)

        templates = AptitudeTestTemplate.objects.filter(is_active=True).order_by('title', 'id')
        return api_response(True, data={
            'templates': [
                {
                    **serialize_aptitude_template(template),
                    'readiness': validate_template_readiness(template),
                }
                for template in templates
            ],
        })


class AptitudeDefaultReadinessApi(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not is_aptitude_workspace_user(request.user):
            return api_response(False, error='Aptitude workspace access is required.', status_code=status.HTTP_403_FORBIDDEN)

        role_type = request.GET.get('role_type') or AptitudeTestTemplate.RoleType.GENERAL
        role_family = request.GET.get('role_family') or ''
        template = get_default_aptitude_template(role_type=role_type, role_family=role_family)

        return api_response(True, data={
            'template': serialize_aptitude_template(template),
            'readiness': validate_template_readiness(template),
        })


class AptitudeAssignmentCreateApi(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if not is_aptitude_workspace_user(request.user):
            return api_response(False, error='Aptitude workspace access is required.', status_code=status.HTTP_403_FORBIDDEN)

        payload = request.data if isinstance(request.data, dict) else {}
        candidate, error = resolve_optional_int_model(
            User,
            payload.get('candidate_id'),
            error_label='candidate_id',
            queryset=User.objects.filter(profile__role='candidate'),
        )
        if error:
            return api_response(False, error=error, status_code=status.HTTP_400_BAD_REQUEST)

        vacancy, error = resolve_optional_int_model(Vacancies, payload.get('vacancy_id'), error_label='vacancy_id')
        if error:
            return api_response(False, error=error, status_code=status.HTTP_400_BAD_REQUEST)
        if vacancy and not user_can_access_vacancy(request.user, vacancy):
            return api_response(False, error='Vacancy is not accessible.', status_code=status.HTTP_403_FORBIDDEN)

        interview, error = resolve_optional_int_model(Interview, payload.get('interview_id'), error_label='interview_id')
        if error:
            return api_response(False, error=error, status_code=status.HTTP_400_BAD_REQUEST)
        if interview and not user_can_access_interview(request.user, interview):
            return api_response(False, error='Interview is not accessible.', status_code=status.HTTP_403_FORBIDDEN)

        template, error = resolve_optional_int_model(AptitudeTestTemplate, payload.get('template_id'), error_label='template_id')
        if error:
            return api_response(False, error=error, status_code=status.HTTP_400_BAD_REQUEST)

        allow_partial = parse_bool(payload.get('allow_partial', False))
        if allow_partial and not (request.user.is_staff or request.user.is_superuser):
            allow_partial = False

        try:
            result = create_aptitude_assignment(
                candidate=candidate,
                vacancy=vacancy,
                interview=interview,
                template=template,
                role_type=payload.get('role_type') or AptitudeTestTemplate.RoleType.GENERAL,
                role_family=payload.get('role_family') or '',
                title=payload.get('title') or None,
                allow_partial=allow_partial,
                created_by=request.user,
            )
        except AptitudeAssignmentError as exc:
            selected_template = template or get_default_aptitude_template(
                role_type=payload.get('role_type') or AptitudeTestTemplate.RoleType.GENERAL,
                role_family=payload.get('role_family') or '',
            )
            readiness = validate_template_readiness(selected_template)
            return api_response(False, data={'readiness': readiness}, error=str(exc), status_code=status.HTTP_400_BAD_REQUEST)

        assignment = result['assignment']
        return api_response(True, data={
            'assignment': serialize_aptitude_assignment(assignment, questions_created=result['questions_created']),
            'readiness': result['readiness'],
        }, status_code=status.HTTP_201_CREATED)


class AptitudeAssignmentDetailApi(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, assignment_id: int):
        assignment = (
            AptitudeTestAssignment.objects
            .select_related('candidate', 'vacancy', 'interview', 'template', 'created_by')
            .filter(id=assignment_id)
            .first()
        )
        if not assignment:
            return api_response(False, error='Aptitude assignment not found.', status_code=status.HTTP_404_NOT_FOUND)
        if not user_can_access_assignment(request.user, assignment):
            return api_response(False, error='Aptitude assignment is not accessible.', status_code=status.HTTP_403_FORBIDDEN)

        result = get_assignment_result(assignment)
        data = {
            'assignment': serialize_aptitude_assignment(assignment),
            'section_config': assignment.section_config,
            'question_count': assignment.questions.count(),
            'answer_count': assignment.answers.count(),
            'result': serialize_aptitude_result(result) if result else None,
            'integrity_summary': result.integrity_summary if result else summarize_integrity_events(assignment),
        }
        return api_response(True, data=data)


class AptitudeAssignmentResultApi(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, assignment_id: int):
        assignment = (
            AptitudeTestAssignment.objects
            .select_related('candidate', 'vacancy', 'interview', 'template', 'created_by')
            .filter(id=assignment_id)
            .first()
        )
        if not assignment:
            return api_response(False, error='Aptitude assignment not found.', status_code=status.HTTP_404_NOT_FOUND)
        if not user_can_access_assignment(request.user, assignment):
            return api_response(False, error='Aptitude assignment is not accessible.', status_code=status.HTTP_403_FORBIDDEN)

        result = get_assignment_result(assignment)
        if not result and assignment.status == AptitudeTestAssignment.Status.SUBMITTED:
            result = score_assignment(assignment)
        if not result:
            return api_response(False, error='Aptitude result is not available yet.', status_code=status.HTTP_404_NOT_FOUND)

        return api_response(True, data={'result': serialize_aptitude_result(result)})


class AptitudeRuntimeStatusApi(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, public_token: str):
        try:
            assignment = resolve_aptitude_runtime_assignment(request, public_token)
        except AptitudeRuntimeAccessError as exc:
            return aptitude_runtime_error_response(exc)
        mark_aptitude_assignment_expired_if_needed(assignment)
        assignment.refresh_from_db()
        return api_response(True, data={'assignment': serialize_runtime_status(assignment)})


class AptitudeRuntimeStartApi(APIView):
    permission_classes = [permissions.AllowAny]

    @transaction.atomic
    def post(self, request, public_token: str):
        try:
            assignment = resolve_aptitude_runtime_assignment(request, public_token)
        except AptitudeRuntimeAccessError as exc:
            return aptitude_runtime_error_response(exc)

        if mark_aptitude_assignment_expired_if_needed(assignment):
            assignment.refresh_from_db()
            return api_response(False, data={'assignment': serialize_runtime_status(assignment)}, error='Aptitude assignment has expired.', status_code=status.HTTP_400_BAD_REQUEST)

        if assignment.status == AptitudeTestAssignment.Status.ASSIGNED:
            now = timezone.now()
            assignment.status = AptitudeTestAssignment.Status.IN_PROGRESS
            assignment.started_at = now
            assignment.expires_at = now + timedelta(minutes=assignment.duration_minutes)
            assignment.save(update_fields=['status', 'started_at', 'expires_at', 'updated_at'])
        elif assignment.status != AptitudeTestAssignment.Status.IN_PROGRESS:
            return api_response(False, data={'assignment': serialize_runtime_status(assignment)}, error='Aptitude assignment cannot be started.', status_code=status.HTTP_400_BAD_REQUEST)

        return api_response(True, data={'assignment': serialize_runtime_status(assignment)})


class AptitudeRuntimeQuestionsApi(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, public_token: str):
        try:
            assignment = resolve_aptitude_runtime_assignment(request, public_token)
        except AptitudeRuntimeAccessError as exc:
            return aptitude_runtime_error_response(exc)
        mark_aptitude_assignment_expired_if_needed(assignment)
        assignment.refresh_from_db()
        if assignment.status == AptitudeTestAssignment.Status.EXPIRED:
            return api_response(False, data={'assignment': serialize_runtime_status(assignment)}, error='Aptitude assignment has expired.', status_code=status.HTTP_400_BAD_REQUEST)
        if assignment.status != AptitudeTestAssignment.Status.IN_PROGRESS:
            return api_response(False, data={'assignment': serialize_runtime_status(assignment)}, error='Aptitude assignment is not in progress.', status_code=status.HTTP_400_BAD_REQUEST)

        answers_by_question_id = {
            answer.question_id: answer
            for answer in assignment.answers.all()
        }
        questions = [
            serialize_runtime_question(question, answers_by_question_id.get(question.id))
            for question in assignment.questions.select_related('section').order_by('order_index', 'id')
        ]
        return api_response(True, data={
            'assignment': serialize_runtime_status(assignment),
            'section_config': serialize_runtime_section_config(assignment),
            'questions': questions,
            'answered_count': runtime_answered_count(assignment),
            'time_remaining_seconds': runtime_time_remaining_seconds(assignment),
        })


class AptitudeRuntimeAnswerApi(APIView):
    permission_classes = [permissions.AllowAny]

    @transaction.atomic
    def post(self, request, public_token: str):
        try:
            assignment = resolve_aptitude_runtime_assignment(request, public_token)
        except AptitudeRuntimeAccessError as exc:
            return aptitude_runtime_error_response(exc)
        mark_aptitude_assignment_expired_if_needed(assignment)
        assignment.refresh_from_db()
        if assignment.status == AptitudeTestAssignment.Status.EXPIRED:
            return api_response(False, data={'assignment': serialize_runtime_status(assignment)}, error='Aptitude assignment has expired.', status_code=status.HTTP_400_BAD_REQUEST)
        if assignment.status != AptitudeTestAssignment.Status.IN_PROGRESS:
            return api_response(False, data={'assignment': serialize_runtime_status(assignment)}, error='Answers can only be saved while the aptitude assignment is in progress.', status_code=status.HTTP_400_BAD_REQUEST)

        payload = request.data if isinstance(request.data, dict) else {}
        try:
            question_id = int(payload.get('question_id'))
        except (TypeError, ValueError):
            return api_response(False, error='question_id is invalid.', status_code=status.HTTP_400_BAD_REQUEST)
        question = AptitudeTestQuestion.objects.filter(id=question_id, assignment=assignment).first()
        if not question:
            return api_response(False, error='Question does not belong to this aptitude assignment.', status_code=status.HTTP_400_BAD_REQUEST)
        answer_payload = payload.get('answer_payload')
        if not isinstance(answer_payload, dict):
            return api_response(False, error='answer_payload must be an object.', status_code=status.HTTP_400_BAD_REQUEST)

        answer, created = AptitudeAnswer.objects.update_or_create(
            assignment=assignment,
            question=question,
            defaults={'answer_payload': answer_payload},
        )
        return api_response(True, data={
            'saved': True,
            'answered_count': runtime_answered_count(assignment),
            'time_remaining_seconds': runtime_time_remaining_seconds(assignment),
            'answer': {
                'id': answer.id,
                'question_id': question.id,
                'saved': True,
                'created': created,
                'answered_at': answer.answered_at.isoformat() if answer.answered_at else None,
            },
        })


class AptitudeRuntimeSubmitApi(APIView):
    permission_classes = [permissions.AllowAny]

    @transaction.atomic
    def post(self, request, public_token: str):
        try:
            assignment = resolve_aptitude_runtime_assignment(request, public_token)
        except AptitudeRuntimeAccessError as exc:
            return aptitude_runtime_error_response(exc)

        mark_aptitude_assignment_expired_if_needed(assignment)
        assignment.refresh_from_db()
        if assignment.status in {AptitudeTestAssignment.Status.SUBMITTED, AptitudeTestAssignment.Status.EXPIRED}:
            result = get_assignment_result(assignment)
            if not result:
                result = score_assignment(assignment)
            return api_response(True, data={
                'assignment': serialize_runtime_status(assignment),
                'result': serialize_runtime_result(result, assignment),
            })
        if assignment.status != AptitudeTestAssignment.Status.IN_PROGRESS:
            return api_response(False, data={'assignment': serialize_runtime_status(assignment)}, error='Only in-progress aptitude assignments can be submitted.', status_code=status.HTTP_400_BAD_REQUEST)

        now = timezone.now()
        assignment.status = AptitudeTestAssignment.Status.SUBMITTED
        assignment.submitted_at = now
        assignment.save(update_fields=['status', 'submitted_at', 'updated_at'])
        result = score_assignment(assignment)
        return api_response(True, data={
            'assignment': serialize_runtime_status(assignment),
            'result': serialize_runtime_result(result, assignment),
        })


class AptitudeRuntimeIntegrityEventApi(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request, public_token: str):
        try:
            assignment = resolve_aptitude_runtime_assignment(request, public_token)
        except AptitudeRuntimeAccessError as exc:
            return aptitude_runtime_error_response(exc)
        mark_aptitude_assignment_expired_if_needed(assignment)
        assignment.refresh_from_db()
        if assignment.status in {
            AptitudeTestAssignment.Status.SUBMITTED,
            AptitudeTestAssignment.Status.EXPIRED,
            AptitudeTestAssignment.Status.CANCELLED,
        }:
            return api_response(False, error='Integrity events cannot be recorded for this assignment status.', status_code=status.HTTP_400_BAD_REQUEST)

        payload = request.data if isinstance(request.data, dict) else {}
        event_type = str(payload.get('event_type') or '').strip()
        allowed_event_types = {choice[0] for choice in AptitudeIntegrityEvent.EventType.choices}
        if event_type not in allowed_event_types:
            return api_response(False, error='event_type is invalid.', status_code=status.HTTP_400_BAD_REQUEST)
        event_payload = payload.get('event_payload') or {}
        if not isinstance(event_payload, dict):
            return api_response(False, error='event_payload must be an object.', status_code=status.HTTP_400_BAD_REQUEST)

        event = AptitudeIntegrityEvent.objects.create(
            assignment=assignment,
            event_type=event_type,
            event_payload=event_payload,
        )
        return api_response(True, data={'event': {'id': event.id, 'event_type': event.event_type}})


class MetaWhatsappWebhookApi(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request):
        mode = request.GET.get('hub.mode')
        verify_token = request.GET.get('hub.verify_token')
        challenge = request.GET.get('hub.challenge')
        if mode == 'subscribe' and verify_token == settings.META_WHATSAPP_VERIFY_TOKEN:
            return HttpResponse(challenge or '', status=200)
        return HttpResponse('Invalid verification token', status=403)

    def post(self, request):
        service = WebhookService()
        signature = request.META.get('HTTP_X_HUB_SIGNATURE_256')
        raw_body = request.body
        if not service.verify_meta_signature(raw_body, signature):
            return Response({'success': False, 'error': 'Invalid signature', 'data': None}, status=status.HTTP_403_FORBIDDEN)

        payload = request.data if isinstance(request.data, dict) else json.loads(raw_body.decode('utf-8') or '{}')
        events = service.extract_meta_status_events(payload)
        for item in events:
            service.update_attempt_status(item['provider_message_id'], item['status'], payload)
        return Response({'success': True, 'error': None, 'data': {'processed': len(events)}})


class Msg91WebhookApi(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = Msg91WebhookSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        service = WebhookService()
        secret = settings.MSG91_WEBHOOK_SECRET
        if secret:
            signature = request.headers.get('X-Webhook-Signature') or request.headers.get('X-Signature')
            if not service.verify_hmac_signature(request.body, signature, secret):
                return Response({'success': False, 'error': 'Invalid webhook signature', 'data': None}, status=status.HTTP_403_FORBIDDEN)
        expected_token = settings.MSG91_WEBHOOK_TOKEN
        if expected_token:
            incoming = request.headers.get('X-Webhook-Token') or serializer.validated_data.get('token')
            if incoming != expected_token:
                return Response({'success': False, 'error': 'Invalid webhook token', 'data': None}, status=status.HTTP_403_FORBIDDEN)
        provider_message_id = serializer.validated_data['provider_message_id']
        event_status = serializer.validated_data['status']
        updated = service.update_attempt_status(provider_message_id, event_status, dict(request.data))
        return Response({'success': True, 'error': None, 'data': {'updated': updated}})


class ExotelWebhookApi(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = ExotelWebhookSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        service = WebhookService()
        secret = settings.EXOTEL_WEBHOOK_SECRET
        if secret:
            signature = request.headers.get('X-Webhook-Signature') or request.headers.get('X-Signature')
            if not service.verify_hmac_signature(request.body, signature, secret):
                return Response({'success': False, 'error': 'Invalid webhook signature', 'data': None}, status=status.HTTP_403_FORBIDDEN)
        expected_token = settings.EXOTEL_WEBHOOK_TOKEN
        if expected_token:
            incoming = request.headers.get('X-Webhook-Token') or serializer.validated_data.get('token') or request.GET.get('token')
            if incoming != expected_token:
                return Response({'success': False, 'error': 'Invalid webhook token', 'data': None}, status=status.HTTP_403_FORBIDDEN)
        provider_message_id = serializer.validated_data['provider_message_id']
        event_status = serializer.validated_data['event_status']
        updated = service.update_attempt_status(provider_message_id, event_status, dict(request.data))
        InterviewCallService().sync_session_from_webhook(provider_message_id, dict(request.data))
        return Response({'success': True, 'error': None, 'data': {'updated': updated}})
