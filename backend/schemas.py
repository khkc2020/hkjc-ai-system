from pydantic import BaseModel
from typing import List, Optional
from datetime import date

class RunnerResponse(BaseModel):
    horse_no: int
    horse_code: str
    horse_name: str
    draw: Optional[int] = None
    declared_weight: Optional[float] = None
    horse_body_weight: Optional[int] = None
    jockey: Optional[str] = None
    trainer: Optional[str] = None
    rating: Optional[int] = None
    live_odds: Optional[float] = None
    predicted_win_prob: Optional[float] = None
    expected_value: Optional[float] = None
    is_value_bet: Optional[int] = None
    finish_position: Optional[int] = None

    class Config:
        from_attributes = True

class RaceSummary(BaseModel):
    race_id: str
    race_date: date
    venue: str
    race_no: int
    race_class: Optional[str] = None
    distance: int
    track_type: str
    course_type: Optional[str] = None

    class Config:
        from_attributes = True

class RaceDetail(RaceSummary):
    runners: List[RunnerResponse] = []
