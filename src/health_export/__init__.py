"""Health-export package.

A self-contained, import-light package that turns raw Garmin Connect responses
into a normalized, timezone-aware JSON bundle for the ``GET /api/health-export``
endpoint. It deliberately avoids importing ``garminconnect``/``mcp`` so the pure
logic (time formatting, normalizers, service, param validation) can be unit
tested without network access or those heavy dependencies installed.
"""
