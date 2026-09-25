from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from datetime import date, datetime
from typing import List
import time

from .database import get_db, engine, Base
from .models import Race, RaceRunner
from .schemas import RaceSummary, RaceDetail
from scraper.hkjc_scraper import fetch_any_race, save_to_db

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="HKJC AI Horse Racing Prediction Hub",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

HTML_CONTENT = """<!DOCTYPE html>
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
        <p class="text-sm text-slate-500 mt-1">實時機器學習排位分析與正期望值 (+EV) 價值馬識別</p>
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
          @click="scrapeOnlineData" 
          :disabled="scraping"
          class="bg-blue-600 hover:bg-blue-700 text-white px-3.5 py-2 rounded-lg text-sm font-bold shadow-sm transition disabled:opacity-50 flex items-center gap-1.5"
          title="從馬會網站自動抓取當日全日排位表 (最多11場)"
        >
          <span>{{ scraping ? '⏳ 抓取全日排位中...' : '📥 抓取此日賽事' }}</span>
        </button>

        <button 
          @click="seedDemoData" 
          :disabled="seeding"
          class="bg-amber-600 hover:bg-amber-700 text-white px-3.5 py-2 rounded-lg text-sm font-bold shadow-sm transition disabled:opacity-50"
          title="填入沙田全日多場獨立馬匹示範數據"
        >
          <span>{{ seeding ? '載入中...' : '🎲 載入示範數據' }}</span>
        </button>
      </div>
    </header>

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
      <div v-if="races.length === 0 && !loading" class="text-sm text-slate-500 bg-white p-4 rounded-xl border border-slate-200 shadow-sm w-full mt-2">
        <p class="font-bold text-slate-700 mb-1">💡 該日期暫無賽事資料</p>
        <p class="text-xs text-slate-500">
          您可以點擊右上角的 <strong class="text-amber-700">「🎲 載入示範數據」</strong> 查看包含多場不同馬匹的預測；或點擊 <strong class="text-blue-700">「📥 抓取此日賽事」</strong> 線上獲取馬會最新排位表。
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
        const selectedDate = ref('2024-06-23');
        const races = ref([]);
        const currentRace = ref(null);
        const selectedRaceId = ref('');
        const loading = ref(false);
        const predicting = ref(false);
        const scraping = ref(false);
        const seeding = ref(false);
        const statusNotice = ref('');

        const fetchRaces = async () => {
          loading.value = true;
          try {
            const res = await fetch(`/api/races?race_date=${selectedDate.value}`);
            if (res.ok) {
              const data = await res.json();
              races.value = data;
              if (data.length > 0) {
                // 如果先前選中的場次存在，則保持；否則選第一場
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
            const res = await fetch(`/api/races/${raceId}`);
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
            await fetch(`/api/mock_predict/${selectedRaceId.value}`, { method: 'POST' });
            await selectRace(selectedRaceId.value);
            statusNotice.value = '第 ' + (currentRace.value?.race_no || '') + ' 場 AI 預測完成！已標記高勝率與價值馬。';
          } catch (e) {
            alert('預測執行出錯: ' + e);
          } finally {
            predicting.value = false;
          }
        };

        const scrapeOnlineData = async () => {
          scraping.value = true;
          statusNotice.value = '正在連線香港賽馬會抓取全日排位表 (第1場至第11場)，請稍候約 15 秒...';
          try {
            const res = await fetch(`/api/scrape?race_date=${selectedDate.value}`, { method: 'POST' });
            const data = await res.json();
            statusNotice.value = data.message || '抓取完成！';
            await fetchRaces();
          } catch (e) {
            statusNotice.value = '連線超時或出錯，請確認該日期是否有馬會賽事。';
          } finally {
            scraping.value = false;
          }
        };

        const seedDemoData = async () => {
          seeding.value = true;
          try {
            const res = await fetch('/api/seed_demo', { method: 'POST' });
            const data = await res.json();
            selectedDate.value = data.date || '2024-06-23';
            statusNotice.value = '已成功載入沙田多場獨立示範賽事 (第1場至第3場)！各場馬匹完全獨立。';
            await fetchRaces();
          } catch (e) {
            alert('載入示範數據失敗: ' + e);
          } finally {
            seeding.value = false;
          }
        };

        const isTopPick = (horse) => {
          if (!currentRace.value || !currentRace.value.runners) return false;
          const maxProb = Math.max(...currentRace.value.runners.map(r => r.predicted_win_prob || 0));
          return maxProb > 0.15 && horse.predicted_win_prob === maxProb;
        };

        onMounted(() => {
          fetchRaces();
        });

        return {
          selectedDate,
          races,
          currentRace,
          selectedRaceId,
          loading,
          predicting,
          scraping,
          seeding,
          statusNotice,
          fetchRaces,
          selectRace,
          triggerPredict,
          scrapeOnlineData,
          seedDemoData,
          isTopPick
        };
      }
    }).mount('#app');
  </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
def serve_dashboard():
    return HTMLResponse(content=HTML_CONTENT)

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
        # 考慮評分加成與檔位影響
        rating_boost = ((runner.rating or 60) - 50) / 100.0
        draw_boost = (7 - abs((runner.draw or 7) - 4)) / 30.0
        simulated_prob = round(max(0.02, base_prob + (rating_boost * 0.05) + (draw_boost * 0.03)), 4)
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

@app.post("/api/scrape")
def trigger_scrape(
    race_date: str = Query(..., description="日期 (YYYY-MM-DD)"),
    db: Session = Depends(get_db)
):
    """線上從馬會網站自動抓取該日賽事排位 (全日最多 11 場)"""
    hkjc_date_str = race_date.replace("-", "/")
    saved_count = 0
    
    # 遍歷全日 1 至 11 場
    for race_no in range(1, 12):
        race_info, runners = fetch_any_race(hkjc_date_str, race_no)
        if race_info and runners:
            save_to_db(race_info, runners)
            saved_count += 1
        time.sleep(0.4)

    if saved_count > 0:
        return {"status": "success", "message": f"成功從香港賽馬會獲取 {race_date} 共 {saved_count} 場賽事完整排位名單！"}
    else:
        return {"status": "empty", "message": f"馬會網站目前未找到 {race_date} 的賽事或排位，請確認日期是否正確。"}

@app.post("/api/seed_demo")
def seed_demo_data(db: Session = Depends(get_db)):
    """直接填入 3 場完全獨立、包含不同真實名駒的示範數據"""
    demo_date = date(2024, 6, 23)

    # 先清理舊示範數據
    old_races = db.query(Race).filter(Race.race_date == demo_date).all()
    for r in old_races:
        db.query(RaceRunner).filter(RaceRunner.race_id == r.race_id).delete()
        db.delete(r)
    db.commit()

    demo_races_config = [
        {
            "race_id": "20240623_ST_01",
            "race_no": 1,
            "race_class": "第四班 (60-40分)",
            "distance": 1200,
            "horses": [
                (1, "E101", "金鑽貴人", 4, 133, "潘頓", "文家良", 78, 2.6),
                (2, "G234", "加州星球", 1, 131, "布文", "告東尼", 76, 5.8),
                (3, "H345", "浪漫勇士", 6, 128, "麥道朗", "沈集成", 73, 4.2),
                (4, "J123", "福逸", 9, 126, "巴度", "高伯新", 71, 14.0),
                (5, "K456", "遨遊氣泡", 2, 124, "田泰安", "姚本輝", 69, 8.5),
                (6, "L789", "永遠美麗", 7, 122, "何澤堯", "蔡約翰", 67, 11.0),
                (7, "M012", "維港智能", 11, 120, "梁家俊", "沈集成", 65, 22.0),
                (8, "N345", "幸運有您", 3, 118, "艾兆禮", "羅富全", 63, 18.0),
            ]
        },
        {
            "race_id": "20240623_ST_02",
            "race_no": 2,
            "race_class": "第三班 (80-60分)",
            "distance": 1400,
            "horses": [
                (1, "B111", "快步奔騰", 2, 135, "田泰安", "呂健威", 79, 3.5),
                (2, "C222", "包裝旋風", 5, 132, "何澤堯", "方嘉柏", 77, 4.8),
                (3, "D333", "美麗奔馳", 8, 129, "潘頓", "告東尼", 75, 2.9),
                (4, "E444", "連連歡呼", 1, 126, "鍾易禮", "伍鵬志", 73, 16.0),
                (5, "F555", "紅運帝王", 4, 123, "布文", "蔡約翰", 71, 6.2),
                (6, "G666", "電氣騎士", 9, 120, "巴度", "韋達", 69, 25.0),
                (7, "H777", "超超比", 3, 118, "周俊樂", "沈集成", 68, 9.5),
                (8, "J888", "天天得樂", 7, 116, "艾兆禮", "葉楚航", 66, 33.0),
            ]
        },
        {
            "race_id": "20240623_ST_03",
            "race_no": 3,
            "race_class": "第二班 (100-80分)",
            "distance": 1600,
            "horses": [
                (1, "K001", "安騁", 3, 133, "莫雷拉", "蔡約翰", 98, 2.1),
                (2, "K002", "知足常樂", 7, 130, "潘頓", "羅富全", 95, 4.0),
                (3, "K003", "保羅承傳", 1, 127, "布文", "告東尼", 93, 7.5),
                (4, "K004", "新力高升", 4, 124, "何澤堯", "蘇偉賢", 91, 5.5),
                (5, "K005", "喜蓮勇感", 6, 121, "田泰安", "沈集成", 88, 12.0),
                (6, "K006", "越駿歡欣", 2, 118, "巴度", "羅富全", 86, 18.0),
                (7, "K007", "敏捷神駒", 8, 115, "鍾易禮", "黎昭昇", 84, 28.0),
                (8, "K008", "增有", 5, 115, "梁家俊", "賀賢", 82, 35.0),
            ]
        }
    ]

    for cfg in demo_races_config:
        race = Race(
            race_id=cfg["race_id"],
            race_date=demo_date,
            venue="ST",
            race_no=cfg["race_no"],
            race_class=cfg["race_class"],
            distance=cfg["distance"],
            track_type="草地",
            course_type="A",
            going="好地"
        )
        db.add(race)
        db.commit()

        for h_no, code, name, draw, wt, jock, trn, rat, odds in cfg["horses"]:
            runner = RaceRunner(
                race_id=cfg["race_id"],
                horse_no=h_no,
                horse_code=code,
                horse_name=name,
                draw=draw,
                declared_weight=wt,
                jockey=jock,
                trainer=trn,
                rating=rat,
                live_odds=odds
            )
            db.add(runner)
        db.commit()

    return {"status": "success", "message": "示範數據載入成功", "date": "2024-06-23"}
