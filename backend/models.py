from sqlalchemy import Column, Integer, String, Float, Date, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .database import Base

class Race(Base):
    __tablename__ = "races"

    race_id = Column(String(25), primary_key=True)
    race_date = Column(Date, nullable=False, index=True)
    venue = Column(String(5), nullable=False)
    race_no = Column(Integer, nullable=False)
    race_class = Column(String(20))
    distance = Column(Integer, nullable=False)
    track_type = Column(String(10), nullable=False)
    course_type = Column(String(10))
    going = Column(String(15))
    created_at = Column(DateTime, server_default=func.now())

    runners = relationship("RaceRunner", back_populates="race", cascade="all, delete-orphan")


class RaceRunner(Base):
    __tablename__ = "race_runners"

    id = Column(Integer, primary_key=True, autoincrement=True)
    race_id = Column(String(25), ForeignKey("races.race_id", ondelete="CASCADE"), nullable=False)
    horse_no = Column(Integer, nullable=False)
    horse_code = Column(String(10), nullable=False, index=True)
    horse_name = Column(String(50), nullable=False)
    draw = Column(Integer)
    declared_weight = Column(Float)
    horse_body_weight = Column(Integer)
    jockey = Column(String(30))
    trainer = Column(String(30))
    rating = Column(Integer)
    live_odds = Column(Float)

    finish_position = Column(Integer)
    finish_time = Column(String(10))
    margin = Column(String(20))

    predicted_win_prob = Column(Float)
    expected_value = Column(Float)
    is_value_bet = Column(Integer, default=0)

    race = relationship("Race", back_populates="runners")

    __table_args__ = (
        UniqueConstraint("race_id", "horse_no", name="uix_race_horse"),
    )
