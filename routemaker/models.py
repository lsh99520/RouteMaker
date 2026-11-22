from datetime import date, datetime, timedelta, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ReqType(str, Enum):
    required = "required"
    preferred = "preferred"


class ReqCategory(str, Enum):
    certificate = "certificate"
    language = "language"
    degree = "degree"
    experience = "experience"
    other = "other"


class ReqOption(BaseModel):
    name: str
    exam_id: Optional[str] = None
    min_score: Optional[float] = None


class Requirement(BaseModel):
    id: str
    type: ReqType
    category: ReqCategory
    text: str
    source_quote: str
    exam_id: Optional[str] = None
    min_score: Optional[float] = None
    user_confirmed: Optional[bool] = None
    quote_verified: bool = True
    track: Optional[str] = None
    options: list[ReqOption] = Field(default_factory=list)

    def choices(self) -> list[ReqOption]:
        if self.options:
            return self.options
        if self.exam_id:
            return [ReqOption(name=self.text, exam_id=self.exam_id, min_score=self.min_score)]
        return []


class JobPosting(BaseModel):
    id: str
    company: str
    title: str
    deadline: datetime
    deadline_quote: str
    requirements: list[Requirement]
    is_synthetic: bool = True
    tracks: list[str] = Field(default_factory=list)
    selected_track: Optional[str] = None


class ExtractedPosting(BaseModel):
    id: str
    company: Optional[str] = None
    title: Optional[str] = None
    deadline: Optional[datetime] = None
    deadline_quote: Optional[str] = None
    deadline_verified: bool = False
    requirements: list[Requirement] = Field(default_factory=list)
    tracks: list[str] = Field(default_factory=list)
    selected_track: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)
    ai_generated: bool = True
    model: str = ""
    source: Optional[str] = None
    source_url: Optional[str] = None

    def to_posting(self) -> "JobPosting":
        if self.deadline is None:
            raise ValueError("마감일이 없어 판정할 수 없습니다. 마감일을 입력해 주세요.")
        return JobPosting(
            id=self.id, company=self.company or "(회사명 미확인)", title=self.title or "(공고명 미확인)",
            deadline=self.deadline, deadline_quote=self.deadline_quote or "",
            requirements=self.requirements, is_synthetic=False,
            tracks=self.tracks, selected_track=self.selected_track,
        )


class Holding(BaseModel):
    exam_id: str
    score: Optional[float] = None
    acquired_date: Optional[date] = None


class FixedEvent(BaseModel):
    title: str
    start: date
    end: date


class Profile(BaseModel):
    id: str
    name: str
    target_job: str
    holdings: list[Holding] = Field(default_factory=list)
    preparing: list[str] = Field(default_factory=list)
    fixed_schedule: list[FixedEvent] = Field(default_factory=list)


class ScheduleStatus(str, Enum):
    confirmed = "confirmed"
    expected = "expected"


class PracticalStage(BaseModel):
    written_result_date: date
    reg_start: Optional[date] = None
    reg_end: date
    exam_date: date
    exam_end: Optional[date] = None


class ExamSession(BaseModel):
    exam_id: str
    exam_name: str
    round: str
    reg_start: Optional[date] = None
    reg_end: date
    late_reg_end: Optional[date] = None
    late_reg_note: Optional[str] = None
    exam_date: date
    result_date: date
    result_date_latest: Optional[date] = None
    score_valid_years: Optional[int] = None
    source: str
    checked_at: date
    status: ScheduleStatus = ScheduleStatus.confirmed
    is_synthetic: bool = False
    practical: Optional[PracticalStage] = None

    @property
    def result_by(self) -> date:
        return self.result_date_latest or self.result_date


class MatchStatus(str, Enum):
    met = "met"
    unmet = "unmet"
    pending = "pending"


class RequirementResult(BaseModel):
    requirement_id: str
    type: ReqType
    text: str
    status: MatchStatus
    reason: str


class Feasibility(str, Enum):
    possible = "possible"
    conditional = "conditional"
    impossible = "impossible"
    no_data = "no_data"


class SessionCheck(BaseModel):
    exam_id: str
    round: str
    exam_date: date
    reg_start: Optional[date] = None
    reg_end: date
    regular_reg_end: Optional[date] = None
    late_reg_end: Optional[date] = None
    late_reg_note: Optional[str] = None
    late: bool = False
    result_date: date
    result_date_latest: Optional[date] = None
    status: ScheduleStatus = ScheduleStatus.confirmed
    stale: bool = False
    practical: Optional[PracticalStage] = None
    usable: bool
    conflicts: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ExamVerdict(BaseModel):
    requirement_id: str
    exam_id: str
    exam_name: str
    feasibility: Feasibility
    chosen: Optional[SessionCheck] = None
    alternatives: list[SessionCheck] = Field(default_factory=list)
    backup: Optional[SessionCheck] = None
    option_names: list[str] = Field(default_factory=list)
    min_score: Optional[float] = None
    current_score: Optional[float] = None
    reasons: list[str]


class Task(BaseModel):
    id: str
    title: str
    due: date
    kind: str
    priority: int
    fixed: bool
    done: bool = False


class Conclusion(BaseModel):
    status: str
    headline: str
    points: list[str] = Field(default_factory=list)


class Analysis(BaseModel):
    posting_id: str
    profile_id: str
    today: date
    summary: dict[str, str]
    requirements: list[RequirementResult]
    exams: list[ExamVerdict]
    tasks: list[Task]
    today_tasks: list[str]
    conclusion: Optional[Conclusion] = None
    today_fixed: bool = False
    track: Optional[str] = None


KST = timezone(timedelta(hours=9))


def kst_today() -> date:
    return datetime.now(KST).date()
