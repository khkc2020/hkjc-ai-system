from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from datetime import date
from typing import List

from .database import get_db, engine, Base
from .models import Race, RaceRunner
from .schemas import RaceSummary, RaceDetail

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="HKJC AI Horse Racing Prediction API",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"status": "online", "message": "HKJC AI Prediction API 正常運行中"}

@app.get("/api/races", response_model=List[RaceSummary])
def get_races_by_date(
    race_date: date = Query(..., description="查詢日期 (YYYY-MM-DD)"),
    db: Session = Depends(get_db)
):
    races = db.query(Race).filter(Race.race_date == race_date).order_by(Race.race_no).all()
    return races

@app.get("/api/races/{race_id}", response_model=RaceDetail)
def get_race_detail(race_id: str, db: Session = Depends(get_db)):
    race = db.query(Race).filter(Race.race_id == race_id).first()
    if not race:
        raise HTTPException(status_code=404, detail="找不到該場次資料")
    return race

@app.post("/api/mock_predict/{race_id}")
def generate_mock_predictions(race_id: str, db: Session = Depends(get_db)):
    runners = db.query(RaceRunner).filter(RaceRunner.race_id == race_id).all()
    if not runners:
        raise HTTPException(status_code=404, detail="該場次無馬匹名單")

    num_runners = len(runners)
    base_prob = 1.0 / num_runners

    for runner in runners:
        simulated_prob = round(base_prob * (1.0 + (runner.rating or 60) / 200), 4)
        runner.predicted_win_prob = simulated_prob
        
        if runner.live_odds and runner.live_odds > 0:
            ev = round((simulated_prob * runner.live_odds) - 1.0, 3)
            runner.expected_value = ev
            runner.is_value_bet = 1 if ev > 0.15 else 0
        else:
            runner.expected_value = 0.0
            runner.is_value_bet = 0

    db.commit()
    return {"message": "預測與 EV 計算完成", "race_id": race_id}
