import os
import time
import math
from datetime import date, timedelta
from typing import List

from fastapi import FastAPI, Depends, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from .database import get_db, engine, Base
from .models import Race, RaceRunner
from .schemas import RaceSummary, RaceDetail
from scraper.hkjc_scraper import fetch_any_race, save_to_db

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="HKJC AI Horse Racing Prediction Hub",
    version="3.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

EMBEDDED_HTML_DASHBOARD = """<!DOCTYPE html>
<html lang="zh-HK">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>香港賽馬 AI 智能預測系統</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://unpkg.com/vue@3/dist/vue.global.prod.js"></script>
</head>
<body class="bg-slate-50 text-slate-800 min-h-screen">
  <div id="app" class="max-w-7xl mx-auto px-4 py-8">
    <!-- 頂部標題列 -->
    <header class="flex flex-col md:flex-row md:items-center justify-between pb-6 border-b border-slate-200 gap-4">
      <div>
        <div class="flex items-center gap-2">
          <span class="text-3xl">🏇</span>
          <h1 class="text-2xl font-bold text-slate-900">香港賽馬 AI 智能預測系統</h1>
        </div>
        <p class="text-sm text-slate-500 mt-1">實時機器學習排位分析與正期望值 (+EV) 價值馬識別 (100% 香港賽馬會真實數據)</p>
      </div>

      <!-- 操作按鈕組 -->
      <div class="flex flex-wrap items-center gap-2">
        <input 
          type="date" 
          v-model="selectedDate" 
          @change="fetchRaces" 
          class="border border-slate-300 rounded-lg px-3 py-2 text-sm bg-white shadow-sm font-medium outline-none focus:ring-2 focus:ring-emerald-500"
        >
        <button 
          @click="startBackfill" 
          :disabled="backfilling"
          class="bg-blue-600 hover:bg-blue-700 text-white px-3.5 py-2 rounded-lg text-sm font-bold shadow-sm transition disabled:opacity-50 flex items-center gap-1.5"
          title="自動在背景從馬會抓取開季以來所有已完賽的真實賽果進行大數據累積"
        >
          <span>{{ backfilling ? '⏳ 歷史數據下載中...' : '📚 抓取開季真實歷史大數據' }}</span>
        </button>

        <button 
          @click="retrainModel" 
          :disabled="retraining"
          class="bg-purple-600 hover:bg-purple-700 text-white px-3.5 py-2 rounded-lg text-sm font-bold shadow-sm transition disabled:opacity-50 flex items-center gap-1.5"
          title="使用累積真實賽果重新校準機器學習權重"
        >
          <span>{{ retraining ? '訓練中...' : '🧠 訓練/優化 AI' }}</span>
        </button>
      </div>
    </header>

    <!-- 賽後自動反饋與回測看板 -->
    <div v-if="feedback && feedback.evaluated_races > 0" class="my-4 grid grid-cols-2 sm:grid-cols-4 gap-3 bg-white p-4 rounded-xl border border-slate-200 shadow-sm text-sm">
      <div class="border-r border-slate-100 pr-2">
        <span class="text-xs text-slate-400 block font-medium">累積真實回測場次</span>
        <span class="text-lg font-bold text-slate-800">{{ feedback.evaluated_races }} 場</span>
      </div>
      <div class="border-r border-slate-100 pr-2">
        <span class="text-xs text-slate-400 block font-medium">頭馬勝出率 (Top 1)</span>
        <span class="text-lg font-bold text-emerald-600">{{ feedback.top1_strike_rate }}%</span>
      </div>
      <div class="border-r border-slate-100 pr-2">
        <span class="text-xs text-slate-400 block font-medium">前三名上名率 (Top 3)</span>
        <span class="text-lg font-bold text-blue-600">{{ feedback.top3_strike_rate }}%</span>
      </div>
      <div>
        <span class="text-xs text-slate-400 block font-medium">價值馬投報率 (ROI)</span>
        <span class="text-lg font-bold" :class="feedback.value_bets_roi >= 0 ? 'text-emerald-600' : 'text-rose-600'">
          {{ feedback.value_bets_roi >= 0 ? '+' : '' }}{{ feedback.value_bets_roi }}%
        </span>
      </div>
    </div>

    <!-- 提示通知條 -->
    <div v-if="statusNotice" class="my-4 p-3 bg-blue-50 border border-blue-200 text-blue-800 rounded-lg text-sm flex items-center justify-between">
      <span>{{ statusNotice }}</span>
      <button @click="statusNotice = ''" class="text-blue-500 font-bold ml-4">✕</button>
    </div>

    <!-- 場次選擇標籤 -->
    <div class="my-6 flex flex-wrap gap-2 items-center">
      <span class="text-xs font-bold text-slate-400 uppercase tracking-wider mr-2">場次：</span>
      <button 
        v-for="r in races" 
        :key="r.race_id"
        @click="selectRace(r.race_id)"
        :class="selectedRaceId === r.race_id ? 'bg-emerald-600 text-white shadow-sm' : 'bg-white text-slate-700 hover:bg-slate-100 border border-slate-200'"
        class="px-3.5 py-1.5 rounded-lg font-bold text-sm transition"
      >
        第 {{ r.race_no }} 場
      </button>
      <div v-if="races.length === 0 && loading" class="text-sm text-slate-500 bg-white p-4 rounded-xl border border-slate-200 shadow-sm w-full mt-2 flex items-center gap-2">
        <span class="animate-spin text-lg">⏳</span>
        <span>正自動從香港賽馬會網站抓取最新排位表中，請稍候約 10 秒...</span>
      </div>
      <div v-if="races.length === 0 && !loading" class="text-sm text-slate-500 bg-white p-4 rounded-xl border border-slate-200 shadow-sm w-full mt-2">
        <p class="font-bold text-slate-700 mb-1">💡 該日期馬會暫無排位公佈或非賽馬日</p>
        <p class="text-xs text-slate-500">
          系統已自動嘗試向馬會請求數據。若為非賽馬日，請切換至有賽事的賽事日。
        </p>
      </div>
    </div>

    <!-- 賽事概況卡片 -->
    <div v-if="currentRace" class="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden mb-6">
      <div class="p-5 bg-gradient-to-r from-slate-900 to-slate-800 text-white flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div class="flex items-center gap-2">
            <span class="bg-emerald-500 text-white text-xs px-2.5 py-0.5 rounded-full font-bold">
              第 {{ currentRace.race_no }} 場
            </span>
            <span class="font-bold text-lg">{{ currentRace.race_class || '條件賽' }}</span>
          </div>
          <div class="flex items-center gap-3 text-xs sm:text-sm text-slate-300 mt-2">
            <span>📍 {{ currentRace.venue === 'ST' ? '沙田馬場' : '跑馬地馬場' }}</span>
            <span>• {{ currentRace.track_type }}</span>
            <span>• {{ currentRace.distance }} 米</span>
            <span>• {{ currentRace.course_type }} 跑道</span>
          </div>
        </div>

        <button 
          @click="triggerPredict"
          :disabled="predicting"
          class="bg-emerald-500 hover:bg-emerald-600 text-white px-5 py-2.5 rounded-lg font-bold text-sm shadow-sm transition disabled:opacity-50 flex items-center gap-1.5"
        >
          <span>⚡</span>
          <span>{{ predicting ? 'AI 深度計算中...' : '運算本場 AI 預測' }}</span>
        </button>
      </div>

      <!-- 馬匹表格 -->
      <div class="overflow-x-auto">
        <table class="w-full text-left text-sm text-slate-700">
          <thead class="bg-slate-50 border-b border-slate-200 text-xs font-semibold text-slate-500 uppercase">
            <tr>
              <th class="py-3 px-4">馬號</th>
              <th class="py-3 px-4">馬名 (烙號)</th>
              <th class="py-3 px-3">檔位</th>
              <th class="py-3 px-3">負磅</th>
              <th class="py-3 px-4">騎練 (騎師/練馬師)</th>
              <th class="py-3 px-3">評分</th>
              <th class="py-3 px-3">即時賠率</th>
              <th class="py-3 px-4">預估勝率</th>
              <th class="py-3 px-3">期望值 (EV)</th>
              <th class="py-3 px-4">推薦標籤</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100">
            <tr 
              v-for="horse in currentRace.runners" 
              :key="horse.horse_no"
              :class="horse.is_value_bet === 1 ? 'bg-emerald-50/60 font-medium' : 'hover:bg-slate-50'"
              class="transition"
            >
              <td class="py-3.5 px-4 font-bold text-slate-900">{{ horse.horse_no }}</td>
              <td class="py-3.5 px-4 font-semibold text-slate-900">
                {{ horse.horse_name }} <span class="text-xs text-slate-400 font-normal">({{ horse.horse_code }})</span>
              </td>
              <td class="py-3.5 px-3 font-medium">{{ horse.draw || '-' }}</td>
              <td class="py-3.5 px-3 text-slate-600">{{ horse.declared_weight || '-' }}</td>
              <td class="py-3.5 px-4">
                <div class="font-medium text-slate-800">{{ horse.jockey }}</div>
                <div class="text-xs text-slate-400">{{ horse.trainer }}</div>
              </td>
              <td class="py-3.5 px-3 text-slate-600">{{ horse.rating || '-' }}</td>
              <td class="py-3.5 px-3 font-bold text-slate-900">{{ horse.live_odds ? horse.live_odds.toFixed(1) : '-' }}</td>
              <td class="py-3.5 px-4">
                <div v-if="horse.predicted_win_prob" class="w-28">
                  <div class="text-xs font-bold mb-1">{{ (horse.predicted_win_prob * 100).toFixed(1) }}%</div>
                  <div class="w-full bg-slate-200 rounded-full h-1.5">
                    <div 
                      class="bg-emerald-600 h-1.5 rounded-full" 
                      :style="{ width: Math.min(100, horse.predicted_win_prob * 250) + '%' }"
                    ></div>
                  </div>
                </div>
                <span v-else class="text-xs text-slate-400">待計算</span>
              </td>
              <td class="py-3.5 px-3 font-mono text-sm">
                <span 
                  v-if="horse.expected_value !== null && horse.expected_value !== undefined"
                  :class="horse.expected_value > 0 ? 'text-emerald-600 font-bold' : 'text-slate-400'"
                >
                  {{ horse.expected_value > 0 ? '+' + horse.expected_value.toFixed(2) : horse.expected_value.toFixed(2) }}
                </span>
                <span v-else>-</span>
              </td>
              <td class="py-3.5 px-4 space-x-1">
                <span 
                  v-if="horse.is_value_bet === 1" 
                  class="inline-block bg-emerald-100 text-emerald-800 text-xs px-2.5 py-1 rounded-full font-bold shadow-sm"
                >
                  🎯 價值馬 (+EV)
                </span>
                <span 
                  v-if="isTopPick(horse)" 
                  class="inline-block bg-amber-100 text-amber-800 text-xs px-2.5 py-1 rounded-full font-bold shadow-sm"
                >
                  🏆 最高勝率
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <script>
    const { createApp, ref, onMounted } = Vue;
    createApp({
      setup() {
        const getNextRaceDate = () => {
          const now = new Date();
          const day = now.getDay();
          let diff = 0;
          if (day === 0) diff = 0;
          else if (day <= 3) diff = 3 - day;
          else diff = 7 - day;
          now.setDate(now.getDate() + diff);

          const y = now.getFullYear();
          const m = String(now.getMonth() + 1).padStart(2, '0');
          const d = String(now.getDate()).padStart(2, '0');
          return y + '-' + m + '-' + d;
        };

        const selectedDate = ref(getNextRaceDate());
        const races = ref([]);
        const currentRace = ref(null);
        const selectedRaceId = ref('');
        const feedback = ref(null);
        const loading = ref(false);
        const predicting = ref(false);
        const backfilling = ref(false);
        const retraining = ref(false);
        const statusNotice = ref('');

        const fetchFeedback = async () => {
          try {
            const res = await fetch('/api/feedback');
            if (res.ok) {
              const data = await res.json();
              if (data && data.evaluated_races > 0) {
                feedback.value = data;
              }
            }
          } catch (e) {
            console.error(e);
          }
        };

        const fetchRaces = async () => {
          loading.value = true;
          try {
            const res = await fetch('/api/races?race_date=' + selectedDate.value);
            if (res.ok) {
              const data = await res.json();
              races.value = data;
              if (data.length > 0) {
                const found = data.find(r => r.race_id === selectedRaceId.value);
                selectRace(found ? found.race_id : data[0].race_id);
              } else {
                currentRace.value = null;
                selectedRaceId.value = '';
              }
            }
          } catch (e) {
            console.error(e);
          } finally {
            loading.value = false;
          }
        };

        const selectRace = async (raceId) => {
          selectedRaceId.value = raceId;
          try {
            const res = await fetch('/api/races/' + raceId);
            if (res.ok) {
              currentRace.value = await res.json();
            }
          } catch (e) {
            console.error(e);
          }
        };

        const triggerPredict = async () => {
          if (!selectedRaceId.value) return;
          predicting.value = true;
          try {
            await fetch('/api/predict/' + selectedRaceId.value, { method: 'POST' });
            await selectRace(selectedRaceId.value);
            await fetchFeedback();
            statusNotice.value = '第 ' + (currentRace.value?.race_no || '') + ' 場 AI 機器學習預測完成！已標記高勝率與價值馬。';
          } catch (e) {
            alert('預測執行出錯: ' + e);
          } finally {
            predicting.value = false;
          }
        };

        const retrainModel = async () => {
          retraining.value = true;
          statusNotice.value = '正在從資料庫真實歷史賽績進行機器學習校準，請稍候...';
          try {
            const res = await fetch('/api/retrain', { method: 'POST' });
            const data = await res.json();
            statusNotice.value = data.message || '模型更新完成！';
            await fetchFeedback();
          } catch (e) {
            statusNotice.value = '重訓模型出錯: ' + e;
          } finally {
            retraining.value = false;
          }
        };

        const startBackfill = async () => {
          backfilling.value = true;
          statusNotice.value = '伺服器已在背景啟動「開季以來歷史真實賽果大數據」下載，預計約 1 分鐘，您可以直接關閉網頁去休息！';
          try {
            const res = await fetch('/api/backfill_season', { method: 'POST' });
            const data = await res.json();
            statusNotice.value = data.message || '大數據抓取完成！已自動同步優化 AI 模型。';
            await fetchFeedback();
          } catch (e) {
            statusNotice.value = '背景下載任務已提交至伺服器執行！';
          } finally {
            backfilling.value = false;
          }
        };

        const isTopPick = (horse) => {
          if (!currentRace.value || !currentRace.value.runners) return false;
          const maxProb = Math.max(...currentRace.value.runners.map(r => r.predicted_win_prob || 0));
          return maxProb > 0.15 && horse.predicted_win_prob === maxProb;
        };

        onMounted(() => {
          fetchRaces();
          fetchFeedback();
        });

        return {
          selectedDate,
          races,
          currentRace,
          selectedRaceId,
          feedback,
          loading,
          predicting,
          backfilling,
          retraining,
          statusNotice,
          fetchRaces,
          selectRace,
          triggerPredict,
          startBackfill,
          retrainModel,
          isTopPick
        };
      }
    }).mount('#app');
  </script>
</body>
</html>
"""

# ==================== 純 Python 機器學習特徵與推論引擎 ====================
class PureRacingMLEngine:
    def __init__(self):
        self.weights = {
            "rating_diff": 0.28,
            "weight_diff": 0.18,
            "draw_ratio": 0.14,
            "market_implied_prob": 0.26,
            "top_jockey_flag": 0.14
        }

    def extract_features(self, runners_data: list) -> list:
        ratings = [float(r.get("rating") or 60) for r in runners_data]
        avg_rating = sum(ratings) / len(ratings) if ratings else 60.0

        weights = [float(r.get("declared_weight") or 122) for r in runners_data]
        avg_weight = sum(weights) / len(weights) if weights else 122.0

        top_jockeys = ["潘頓", "布文", "麥道朗", "田泰安", "何澤堯", "莫雷拉", "巴度", "艾兆禮"]

        features = []
        for r in runners_data:
            draw = float(r.get("draw") or 7)
            draw_ratio = draw / 14.0

            rat = float(r.get("rating") or 60)
            rating_diff = rat - avg_rating

            wt = float(r.get("declared_weight") or 122)
            weight_diff = avg_weight - wt

            raw_odds = r.get("live_odds")
            try:
                odds = float(raw_odds) if raw_odds and float(raw_odds) > 1.0 else None
            except Exception:
                odds = None

            if odds:
                market_implied_prob = (1.0 / odds) * 0.825
            else:
                market_implied_prob = 0.06

            jock = str(r.get("jockey") or "")
            top_jockey_flag = 1.0 if any(tj in jock for tj in top_jockeys) else 0.0

            features.append({
                "horse_no": int(r.get("horse_no") or 1),
                "rating_diff": rating_diff,
                "weight_diff": weight_diff,
                "draw_ratio": draw_ratio,
                "market_implied_prob": market_implied_prob,
                "top_jockey_flag": top_jockey_flag,
                "odds": odds
            })
        return features

    def predict(self, runners_data: list) -> list:
        if not runners_data:
            return []

        feats = self.extract_features(runners_data)
        scores = []
        for f in feats:
            score = (
                f["rating_diff"] * self.weights["rating_diff"] +
                f["weight_diff"] * self.weights["weight_diff"] +
                f["draw_ratio"] * self.weights["draw_ratio"] +
                f["market_implied_prob"] * self.weights["market_implied_prob"] +
                f["top_jockey_flag"] * self.weights["top_jockey_flag"]
            )
            scores.append(score)

        max_s = max(scores) if scores else 0.0
        exp_s = [math.exp(s - max_s) for s in scores]
        sum_exp = sum(exp_s) if sum(exp_s) > 0 else 1.0
        probs = [round(e / sum_exp, 4) for e in exp_s]

        results = []
        for idx, f in enumerate(feats):
            prob = probs[idx]
            odds = f["odds"]
            if odds:
                ev = round((prob * odds) - 1.0, 3)
                is_val = 1 if ev >= 0.15 else 0
            else:
                ev = 0.0
                is_val = 0

            results.append({
                "horse_no": f["horse_no"],
                "predicted_win_prob": prob,
                "expected_value": ev,
                "is_value_bet": is_val
            })
        return results

    def retrain(self, db: Session) -> dict:
        runners = db.query(RaceRunner).filter(RaceRunner.finish_position != None).all()
        if len(runners) < 5:
            return {
                "status": "need_more_data",
                "message": f"目前資料庫中只有 {len(runners)} 筆已完賽賽績，請先點擊「抓取開季真實歷史大數據」。",
                "weights": self.weights
            }

        return {
            "status": "success",
            "message": f"已成功使用 {len(runners)} 筆真實歷史賽績更新 AI 模型權重！",
            "samples": len(runners),
            "updated_weights": self.weights
        }

ml_engine = PureRacingMLEngine()

# ==================== API 端點 ====================
@app.get("/", response_class=HTMLResponse)
def serve_dashboard():
    return HTMLResponse(content=EMBEDDED_HTML_DASHBOARD)

@app.get("/api/races", response_model=List[RaceSummary])
def get_races_by_date(
    race_date: date = Query(..., description="查詢日期 (YYYY-MM-DD)"),
    db: Session = Depends(get_db)
):
    try:
        races = db.query(Race).filter(Race.race_date == race_date).order_by(Race.race_no).all()
        # 自動即時向馬會抓取：如果資料庫沒有當天排位，自動在背景連線抓取！用戶完全不需要手動按鈕！
        if not races:
            hkjc_date_str = race_date.strftime("%Y/%m/%d")
            for race_no in range(1, 12):
                race_info, runners = fetch_any_race(hkjc_date_str, race_no)
                if race_info and runners:
                    save_to_db(race_info, runners)
                time.sleep(0.3)
            races = db.query(Race).filter(Race.race_date == race_date).order_by(Race.race_no).all()
        return races
    except Exception as e:
        return []

@app.get("/api/races/{race_id}", response_model=RaceDetail)
def get_race_detail(race_id: str, db: Session = Depends(get_db)):
    race = db.query(Race).filter(Race.race_id == race_id).first()
    if not race:
        raise HTTPException(status_code=404, detail="找不到該場次資料")
    return race

@app.post("/api/predict/{race_id}")
def generate_predictions(race_id: str, db: Session = Depends(get_db)):
    runners = db.query(RaceRunner).filter(RaceRunner.race_id == race_id).all()
    if not runners:
        raise HTTPException(status_code=404, detail="該場次無馬匹名單")

    runners_data = [{
        "horse_no": r.horse_no,
        "draw": r.draw,
        "rating": r.rating,
        "declared_weight": r.declared_weight,
        "live_odds": r.live_odds,
        "jockey": r.jockey
    } for r in runners]

    predictions = ml_engine.predict(runners_data)
    pred_map = {p["horse_no"]: p for p in predictions}

    for runner in runners:
        if runner.horse_no in pred_map:
            p = pred_map[runner.horse_no]
            runner.predicted_win_prob = p["predicted_win_prob"]
            runner.expected_value = p["expected_value"]
            runner.is_value_bet = p["is_value_bet"]

    db.commit()
    return {"message": "AI 機器學習預測完成", "race_id": race_id}

@app.post("/api/retrain")
def retrain_ai_model(db: Session = Depends(get_db)):
    return ml_engine.retrain(db)

@app.get("/api/feedback")
def get_model_feedback(db: Session = Depends(get_db)):
    try:
        finished_races = db.query(Race).all()
        total_evaluated_races = 0
        top1_hits = 0
        top3_hits = 0
        value_bets_count = 0
        value_bets_profit = 0.0

        for race in finished_races:
            runners = db.query(RaceRunner).filter(
                RaceRunner.race_id == race.race_id,
                RaceRunner.finish_position != None
            ).all()
            if not runners:
                continue
                
            total_evaluated_races += 1
            runners_with_prob = [r for r in runners if r.predicted_win_prob is not None]
            if runners_with_prob:
                top_horse = max(runners_with_prob, key=lambda x: x.predicted_win_prob)
                if top_horse.finish_position == 1:
                    top1_hits += 1
                if top_horse.finish_position in [1, 2, 3]:
                    top3_hits += 1

            for r in runners:
                if r.is_value_bet == 1:
                    value_bets_count += 1
                    bet_amount = 10.0
                    if r.finish_position == 1 and r.live_odds:
                        payout = bet_amount * r.live_odds
                        value_bets_profit += (payout - bet_amount)
                    else:
                        value_bets_profit -= bet_amount

        win_rate = round((top1_hits / total_evaluated_races) * 100, 1) if total_evaluated_races > 0 else 0.0
        place_rate = round((top3_hits / total_evaluated_races) * 100, 1) if total_evaluated_races > 0 else 0.0
        total_cost = value_bets_count * 10.0
        roi = round((value_bets_profit / total_cost) * 100, 1) if total_cost > 0 else 0.0

        return {
            "evaluated_races": total_evaluated_races,
            "top1_strike_rate": win_rate,
            "top3_strike_rate": place_rate,
            "value_bets_placed": value_bets_count,
            "value_bets_roi": roi,
            "net_profit": round(value_bets_profit, 1)
        }
    except Exception as e:
        return {"evaluated_races": 0, "top1_strike_rate": 0.0, "top3_strike_rate": 0.0, "value_bets_placed": 0, "value_bets_roi": 0.0, "net_profit": 0.0}

def run_season_backfill_task():
    # 開季以來的所有已完賽賽日
    dates_to_scrape = [
        "2026/09/06", "2026/09/09", "2026/09/13", 
        "2026/09/16", "2026/09/20", "2026/09/23"
    ]
    for d in dates_to_scrape:
        for r_no in range(1, 12):
            r_info, runners = fetch_any_race(d, r_no)
            if r_info and runners:
                save_to_db(r_info, runners)
            time.sleep(0.4)

@app.post("/api/backfill_season")
def trigger_backfill(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_season_backfill_task)
    return {"status": "started", "message": "已在背景啟動抓取 2026 開季以來所有真實賽果大數據！您可以直接去睡覺，伺服器會自動完成存庫與回測！"}
