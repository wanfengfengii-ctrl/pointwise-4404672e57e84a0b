from dataclasses import dataclass
from datetime import date
import re
from xcollect.errors import BusinessValidationError


def parse_report_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise BusinessValidationError("expected YYYY-MM-DD date")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise BusinessValidationError("invalid report date") from exc
    return value


@dataclass(frozen=True)
class Period:
    kind: str
    start: str
    end: str | None = None

    def __post_init__(self):
        parse_report_date(self.start)
        if self.kind == "instant":
            if self.end is not None:
                raise BusinessValidationError("instant has one endpoint")
        elif self.kind == "duration":
            parse_report_date(self.end)
            if self.start > self.end:
                raise BusinessValidationError("reversed report period")
        else:
            raise BusinessValidationError("unsupported report period")


def make_instant_period(value):
    return Period("instant", parse_report_date(value))


def make_duration_period(start, end):
    return Period("duration", parse_report_date(start), parse_report_date(end))


def period_key(period):
    if not isinstance(period, Period):
        raise BusinessValidationError("expected Period")
    if period.kind == "instant":
        return ("instant", period.start)
    return ("duration", period.start, period.end)
