from __future__ import annotations

import base64
import io
import json
import mimetypes
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from django.conf import settings
from django.contrib.auth.models import User
from django.utils import timezone

from smartInterviewApp.models import CandidateIdentityVerification, UserProfile


class IdentityVerificationError(Exception):
    pass


class CandidateIdentityVerificationService:
    endpoint = 'https://api.openai.com/v1/responses'

    def get_record(self, user: User) -> CandidateIdentityVerification:
        record, _ = CandidateIdentityVerification.objects.get_or_create(candidate=user)
        return record

    def process_offline_xml(self, user: User, profile: UserProfile, xml_file) -> CandidateIdentityVerification:
        record = self.get_record(user)
        record.verification_method = CandidateIdentityVerification.Method.OFFLINE_XML
        record.status = CandidateIdentityVerification.Status.PROCESSING
        record.error_message = ''
        record.uploaded_xml = xml_file
        record.save()

        try:
            record.uploaded_xml.open('rb')
            xml_text = record.uploaded_xml.read().decode('utf-8', errors='ignore')
            record.uploaded_xml.close()
            extracted = self._parse_offline_xml(xml_text)
            comparison = self._compare_with_profile(user, profile, extracted)
            record.aadhaar_name = extracted.get('name', '')
            record.aadhaar_gender = extracted.get('gender', '')
            record.aadhaar_dob = extracted.get('dob', '') or extracted.get('yob', '')
            record.aadhaar_reference = extracted.get('reference', '')
            record.raw_text = xml_text[:5000]
            record.extracted_data = extracted
            record.comparison = comparison
            record.status = (
                CandidateIdentityVerification.Status.XML_VERIFIED
                if comparison.get('matched')
                else CandidateIdentityVerification.Status.DOCUMENT_MISMATCH
            )
            record.processed_at = timezone.now()
            record.error_message = '' if comparison.get('matched') else 'Uploaded Aadhaar XML does not match the current profile details.'
            record.save()
            return record
        except Exception as exc:
            record.status = CandidateIdentityVerification.Status.FAILED
            record.error_message = str(exc)
            record.processed_at = timezone.now()
            record.save(update_fields=['status', 'error_message', 'processed_at', 'updated_at'])
            return record

    def process_document_upload(self, user: User, profile: UserProfile, pdf_file=None, front_image=None, back_image=None) -> CandidateIdentityVerification:
        record = self.get_record(user)
        record.verification_method = CandidateIdentityVerification.Method.DOCUMENT_UPLOAD
        record.status = CandidateIdentityVerification.Status.PROCESSING
        record.error_message = ''
        if pdf_file:
            record.uploaded_pdf = pdf_file
        if front_image:
            record.uploaded_front_image = front_image
        if back_image:
            record.uploaded_back_image = back_image
        record.save()

        try:
            extracted = self._extract_document_data(record)
            comparison = self._compare_with_profile(user, profile, extracted)
            record.aadhaar_name = extracted.get('name', '')
            record.aadhaar_gender = extracted.get('gender', '')
            record.aadhaar_dob = extracted.get('dob', '') or extracted.get('yob', '')
            record.aadhaar_reference = extracted.get('aadhaar_last4', '')
            record.raw_text = extracted.get('raw_text', '')[:8000]
            record.extracted_data = extracted
            record.comparison = comparison
            record.status = (
                CandidateIdentityVerification.Status.DOCUMENT_MATCHED
                if comparison.get('matched')
                else CandidateIdentityVerification.Status.DOCUMENT_MISMATCH
            )
            record.processed_at = timezone.now()
            record.error_message = '' if comparison.get('matched') else 'Uploaded Aadhaar documents do not match the current profile details.'
            record.save()
            return record
        except Exception as exc:
            record.status = CandidateIdentityVerification.Status.FAILED
            record.error_message = str(exc)
            record.processed_at = timezone.now()
            record.save(update_fields=['status', 'error_message', 'processed_at', 'updated_at'])
            return record

    def _parse_offline_xml(self, xml_text: str) -> dict[str, str]:
        try:
            root = ElementTree.fromstring(xml_text)
        except ElementTree.ParseError as exc:
            raise IdentityVerificationError('Invalid Aadhaar XML file.') from exc

        attrs = {key.lower(): (value or '').strip() for key, value in root.attrib.items()}
        if not attrs:
            for child in root.iter():
                for key, value in child.attrib.items():
                    attrs.setdefault(key.lower(), (value or '').strip())

        name = attrs.get('name') or attrs.get('fullname') or attrs.get('uidname') or ''
        gender = attrs.get('gender') or attrs.get('g') or ''
        dob = attrs.get('dob') or attrs.get('dateofbirth') or ''
        yob = attrs.get('yob') or attrs.get('yearofbirth') or ''
        reference = attrs.get('referenceid') or attrs.get('reference') or attrs.get('uid') or ''

        if not name:
            raise IdentityVerificationError('Aadhaar XML does not contain a readable name.')

        return {
            'name': name,
            'gender': gender,
            'dob': dob,
            'yob': yob,
            'reference': reference,
        }

    def _extract_document_data(self, record: CandidateIdentityVerification) -> dict[str, Any]:
        raw_text_parts: list[str] = []
        if record.uploaded_pdf:
            raw_text_parts.append(self._extract_pdf_text(record.uploaded_pdf.path))
        if not raw_text_parts and (record.uploaded_front_image or record.uploaded_back_image):
            extracted = self._extract_with_openai(record)
            if extracted.get('raw_text'):
                raw_text_parts.append(str(extracted.get('raw_text')))
            return {
                'name': str(extracted.get('name') or '').strip(),
                'gender': str(extracted.get('gender') or '').strip(),
                'dob': str(extracted.get('dob') or '').strip(),
                'yob': str(extracted.get('yob') or '').strip(),
                'aadhaar_last4': str(extracted.get('aadhaar_last4') or '').strip(),
                'address': str(extracted.get('address') or '').strip(),
                'raw_text': str(extracted.get('raw_text') or '').strip(),
            }

        raw_text = '\n'.join(part for part in raw_text_parts if part).strip()
        if not raw_text:
            raise IdentityVerificationError('Unable to extract readable Aadhaar data from the uploaded documents.')

        return self._parse_aadhaar_text(raw_text)

    def _extract_pdf_text(self, file_path: str) -> str:
        path = Path(file_path)
        try:
            from pypdf import PdfReader  # type: ignore
        except Exception:
            try:
                from PyPDF2 import PdfReader  # type: ignore
            except Exception as exc:
                raise IdentityVerificationError('PDF parsing requires pypdf or PyPDF2.') from exc
        reader = PdfReader(str(path))
        return '\n'.join((page.extract_text() or '') for page in reader.pages).strip()

    def _extract_with_openai(self, record: CandidateIdentityVerification) -> dict[str, str]:
        api_key = getattr(settings, 'OPENAI_API_KEY', '').strip()
        model = getattr(settings, 'OPENAI_RESUME_MODEL', 'gpt-4.1-mini').strip()
        if not api_key:
            raise IdentityVerificationError('OpenAI is required for Aadhaar image extraction, but no API key is configured.')

        content: list[dict[str, Any]] = [{
            'type': 'input_text',
            'text': (
                'Extract Aadhaar card details from the provided image(s). '
                'Return JSON with keys: name, gender, dob, yob, aadhaar_last4, address, raw_text.'
            ),
        }]
        for field in ('uploaded_front_image', 'uploaded_back_image'):
            file_field = getattr(record, field)
            if not file_field:
                continue
            mime_type = mimetypes.guess_type(file_field.name)[0] or 'image/jpeg'
            data = base64.b64encode(Path(file_field.path).read_bytes()).decode('utf-8')
            content.append({
                'type': 'input_image',
                'image_url': f'data:{mime_type};base64,{data}',
            })

        body = json.dumps({
            'model': model,
            'input': [{'role': 'user', 'content': content}],
            'text': {
                'format': {
                    'type': 'json_schema',
                    'name': 'aadhaar_extract',
                    'strict': True,
                    'schema': {
                        'type': 'object',
                        'additionalProperties': False,
                        'properties': {
                            'name': {'type': 'string'},
                            'gender': {'type': 'string'},
                            'dob': {'type': 'string'},
                            'yob': {'type': 'string'},
                            'aadhaar_last4': {'type': 'string'},
                            'address': {'type': 'string'},
                            'raw_text': {'type': 'string'},
                        },
                        'required': ['name', 'gender', 'dob', 'yob', 'aadhaar_last4', 'address', 'raw_text'],
                    },
                },
            },
        }).encode('utf-8')

        request = urllib.request.Request(
            self.endpoint,
            data=body,
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            method='POST',
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode('utf-8', errors='ignore')
            raise IdentityVerificationError(f'OpenAI Aadhaar extraction failed: {error_body[:400]}') from exc
        except Exception as exc:
            raise IdentityVerificationError(f'Unable to process Aadhaar image verification: {exc}') from exc

        text = payload.get('output_text', '').strip()
        if not text:
            for item in payload.get('output') or []:
                for part in item.get('content', []):
                    maybe_text = part.get('text')
                    if isinstance(maybe_text, str) and maybe_text.strip():
                        text = maybe_text.strip()
                        break
                if text:
                    break
        if not text:
            raise IdentityVerificationError('OpenAI Aadhaar extraction returned no usable text.')
        parsed = json.loads(text)
        return {
            'name': str(parsed.get('name') or '').strip(),
            'gender': str(parsed.get('gender') or '').strip(),
            'dob': str(parsed.get('dob') or '').strip(),
            'yob': str(parsed.get('yob') or '').strip(),
            'aadhaar_last4': str(parsed.get('aadhaar_last4') or '').strip(),
            'address': str(parsed.get('address') or '').strip(),
            'raw_text': str(parsed.get('raw_text') or '').strip(),
        }

    def _parse_aadhaar_text(self, raw_text: str) -> dict[str, Any]:
        clean_text = raw_text.replace('\r', '\n')
        lines = [line.strip() for line in clean_text.splitlines() if line.strip()]
        name = ''
        for line in lines[:8]:
            if not re.search(r'\d', line) and len(line.split()) >= 2 and 'government' not in line.lower() and 'aadhaar' not in line.lower():
                name = line
                break
        gender_match = re.search(r'\b(male|female|other)\b', clean_text, re.IGNORECASE)
        dob_match = re.search(r'(?:dob|date of birth)[:\s-]*([0-9]{2}[/-][0-9]{2}[/-][0-9]{4})', clean_text, re.IGNORECASE)
        yob_match = re.search(r'(?:yob|year of birth)[:\s-]*([0-9]{4})', clean_text, re.IGNORECASE)
        aadhaar_match = re.search(r'(\d{4}\s\d{4}\s\d{4}|\d{12})', clean_text)
        last4 = ''
        if aadhaar_match:
            digits = re.sub(r'\D', '', aadhaar_match.group(1))
            last4 = digits[-4:]

        address = ''
        address_index = next((idx for idx, line in enumerate(lines) if 'address' in line.lower()), -1)
        if address_index >= 0:
            address = ' '.join(lines[address_index + 1: address_index + 5]).strip()

        return {
            'name': name,
            'gender': gender_match.group(1).title() if gender_match else '',
            'dob': dob_match.group(1) if dob_match else '',
            'yob': yob_match.group(1) if yob_match else '',
            'aadhaar_last4': last4,
            'address': address,
            'raw_text': clean_text,
        }

    def _compare_with_profile(self, user: User, profile: UserProfile, extracted: dict[str, Any]) -> dict[str, Any]:
        candidate_name = f"{user.first_name} {user.last_name}".strip()
        extracted_name = str(extracted.get('name') or '').strip()
        candidate_gender = (profile.gender or '').strip().lower()
        extracted_gender = str(extracted.get('gender') or '').strip().lower()

        name_match = self._normalize_name(candidate_name) == self._normalize_name(extracted_name)
        gender_match = not extracted_gender or candidate_gender == extracted_gender
        matched = bool(name_match and gender_match and extracted_name)
        return {
            'matched': matched,
            'name_match': name_match,
            'gender_match': gender_match,
            'candidate_name': candidate_name,
            'extracted_name': extracted_name,
            'candidate_gender': candidate_gender,
            'extracted_gender': extracted_gender,
        }

    def _normalize_name(self, value: str) -> str:
        return re.sub(r'[^a-z0-9]+', ' ', (value or '').lower()).strip()


class CandidateLiveSelfieVerificationService:
    provider = 'local_face_recognition'

    def verify_local_face_match(self, profile_photo_path_or_file: Any, selfie_file: Any, threshold: float | None = None) -> dict[str, Any]:
        threshold = float(threshold if threshold is not None else getattr(settings, 'LIVE_SELFIE_FACE_MATCH_THRESHOLD', 0.62))

        try:
            import face_recognition  # type: ignore
        except Exception:
            return self._unavailable_result(threshold, 'face_recognition_not_installed')

        try:
            profile_image = face_recognition.load_image_file(self._image_input(profile_photo_path_or_file))
            selfie_image = face_recognition.load_image_file(self._image_input(selfie_file))

            profile_locations = face_recognition.face_locations(profile_image)
            selfie_locations = face_recognition.face_locations(selfie_image)
            profile_count = len(profile_locations)
            selfie_count = len(selfie_locations)

            count_failure = self._count_failure_result(profile_count, selfie_count, threshold)
            if count_failure:
                return count_failure

            profile_encodings = face_recognition.face_encodings(profile_image, known_face_locations=profile_locations)
            selfie_encodings = face_recognition.face_encodings(selfie_image, known_face_locations=selfie_locations)
            if len(profile_encodings) != 1:
                return self._failure_result('profile_face_not_detected', profile_count, selfie_count, threshold)
            if len(selfie_encodings) != 1:
                return self._failure_result('selfie_face_not_detected', profile_count, selfie_count, threshold)

            distance = float(face_recognition.face_distance([profile_encodings[0]], selfie_encodings[0])[0])
            score = round(max(0.0, min(1.0, 1.0 - distance)), 4)
            matched = score >= threshold
            return {
                'available': True,
                'matched': matched,
                'score': score,
                'threshold': threshold,
                'reason': 'face_matched' if matched else 'face_mismatch',
                'provider': self.provider,
                'profile_face_count': profile_count,
                'selfie_face_count': selfie_count,
                'message': 'Face matched successfully.' if matched else 'We could not confidently match your selfie with your profile photo.',
            }
        except Exception:
            return self._unavailable_result(threshold, 'face_matching_unavailable')

    def _image_input(self, source: Any) -> Any:
        if isinstance(source, (bytes, bytearray)):
            return io.BytesIO(source)

        try:
            path = getattr(source, 'path', None)
        except Exception:
            path = None
        if path:
            try:
                if Path(path).exists():
                    return str(path)
            except (OSError, TypeError, ValueError):
                pass

        if hasattr(source, 'open') and hasattr(source, 'read'):
            try:
                source.open('rb')
            except Exception:
                pass
            try:
                source.seek(0)
            except Exception:
                pass
            return io.BytesIO(source.read())

        return source

    def _count_failure_result(self, profile_count: int, selfie_count: int, threshold: float) -> dict[str, Any] | None:
        if profile_count > 1 or selfie_count > 1:
            return self._failure_result('multiple_faces_detected', profile_count, selfie_count, threshold)
        if profile_count < 1:
            return self._failure_result('profile_face_not_detected', profile_count, selfie_count, threshold)
        if selfie_count < 1:
            return self._failure_result('selfie_face_not_detected', profile_count, selfie_count, threshold)
        return None

    def _failure_result(self, reason: str, profile_count: int, selfie_count: int, threshold: float) -> dict[str, Any]:
        messages = {
            'face_mismatch': 'We could not confidently match your selfie with your profile photo.',
            'profile_face_not_detected': 'We could not detect a clear face in your profile photo. Please upload a clearer profile photo.',
            'selfie_face_not_detected': 'We could not detect a clear face in your selfie. Please try again.',
            'multiple_faces_detected': 'Only one face can be visible during identity verification.',
        }
        return {
            'available': True,
            'matched': False,
            'score': 0.0,
            'threshold': threshold,
            'reason': reason,
            'provider': self.provider,
            'profile_face_count': profile_count,
            'selfie_face_count': selfie_count,
            'message': messages.get(reason, messages['face_mismatch']),
        }

    def _unavailable_result(self, threshold: float, reason: str) -> dict[str, Any]:
        return {
            'available': False,
            'matched': False,
            'score': 0,
            'threshold': threshold,
            'reason': reason,
            'provider': self.provider,
            'profile_face_count': 0,
            'selfie_face_count': 0,
            'message': 'Live selfie identity verification is temporarily unavailable.',
        }
