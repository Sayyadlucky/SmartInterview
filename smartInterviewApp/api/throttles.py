from rest_framework.throttling import ScopedRateThrottle


class OtpRateThrottle(ScopedRateThrottle):
    """Scoped throttle hook for OTP endpoints (request/verify/resend)."""
