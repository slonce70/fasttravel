"""Raw upstream payload → NormalizedOffer / NormalizedHotelContent.

Normalizers are PURE functions over plain Python data — no I/O, no DB
access, no logging side-effects beyond `structlog.get_logger().warn()`
for soft skips. This makes them trivially testable from a JSON file."""
