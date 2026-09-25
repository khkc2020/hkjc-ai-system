import time
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from backend.database import SessionLocal, engine, Base
from backend.models import Race, RaceRunner

Base.metadata.create_all(bind=engine)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def parse_race_results(race_date_str: str, race_no: int):
    url = f"https://racing.hkjc.com/racing/information/Chinese/racing/LocalResults.aspx?RaceDate={race_date_str}&RaceNo={race_no}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code != 200:
            return None, []
    except Exception as err:
        print(f"網絡請求出錯: {err}")
        return None, []

    soup = BeautifulSoup(resp.content, "html.parser")
    
    race_info_div = soup.find("div", {"class": "race_tab"})
    if not race_info_div:
        return None, []

    info_text = race_info_div.text
    venue = "ST" if "沙田" in info_text else ("HV" if "跑馬地" in info_text else "ST")
    track_type = "全天候跑道" if "全天候" in info_text else "草地"
    
    dist_match = re.search(r'(\d{3,4})米', info_text)
    distance = int(dist_match.group(1)) if dist_match else 1200
    
    class_match = re.search(r'(第[一二三四五]班|新馬賽|國際一級賽|一級賽|二級賽|三級賽)', info_text)
    race_class = class_match.group(1) if class_match else "條件賽"

    date_obj = datetime.strptime(race_date_str, "%Y/%m/%d").date()
    formatted_id = f"{date_obj.strftime('%Y%m%d')}_{venue}_{race_no:02d}"

    race_data = {
        "race_id": formatted_id,
        "race_date": date_obj,
        "venue": venue,
        "race_no": race_no,
        "race_class": race_class,
        "distance": distance,
        "track_type": track_type,
        "course_type": "A",
        "going": "好地"
    }

    result_table = soup.find("table", {"class": "table_bd"}) or soup.find("table", {"class": "f_tac"})
    if not result_table:
        return race_data, []

    runners = []
    rows = result_table.find_all("tr")
    for r in rows:
        cols = r.find_all("td")
        if len(cols) < 10:
            continue

        pos_str = cols[0].text.strip()
        finish_pos = int(pos_str) if pos_str.isdigit() else None
        
        horse_no_str = cols[1].text.strip()
        if not horse_no_str.isdigit():
            continue
        horse_no = int(horse_no_str)

        horse_info = cols[2].text.strip()
        code_match = re.search(r'\((.*?)\)', horse_info)
        horse_code = code_match.group(1) if code_match else f"H_{horse_no}"
        horse_name = re.sub(r'\(.*?\)', '', horse_info).strip()

        jockey = cols[3].text.strip()
        trainer = cols[4].text.strip()
        
        actual_weight = float(cols[5].text.strip()) if cols[5].text.strip().replace('.','',1).isdigit() else None
        body_weight = int(cols[6].text.strip()) if cols[6].text.strip().isdigit() else None
        draw = int(cols[7].text.strip()) if cols[7].text.strip().isdigit() else None
        
        finish_time = cols[10].text.strip() if len(cols) > 10 else None
        odds_str = cols[11].text.strip() if len(cols) > 11 else None
        odds = float(odds_str) if odds_str and odds_str.replace('.','',1).isdigit() else None

        runners.append({
            "race_id": formatted_id,
            "horse_no": horse_no,
            "horse_code": horse_code,
            "horse_name": horse_name,
            "draw": draw,
            "declared_weight": actual_weight,
            "horse_body_weight": body_weight,
            "jockey": jockey,
            "trainer": trainer,
            "live_odds": odds,
            "finish_position": finish_pos,
            "finish_time": finish_time
        })

    return race_data, runners

def save_to_db(race_dict, runners_list):
    db = SessionLocal()
    try:
        race = db.query(Race).filter(Race.race_id == race_dict["race_id"]).first()
        if not race:
            race = Race(**race_dict)
            db.add(race)
            db.commit()

        for runner_data in runners_list:
            existing_runner = db.query(RaceRunner).filter(
                RaceRunner.race_id == runner_data["race_id"],
                RaceRunner.horse_no == runner_data["horse_no"]
            ).first()

            if not existing_runner:
                runner = RaceRunner(**runner_data)
                db.add(runner)
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"資料庫寫入異常: {e}")
    finally:
        db.close()

def batch_scrape(date_list):
    for date_str in date_list:
        print(f"開始抓取賽日: {date_str}")
        for race_no in range(1, 12):
            race_info, runners = parse_race_results(date_str, race_no)
            if not race_info or not runners:
                break
            save_to_db(race_info, runners)
            print(f"已存入第 {race_no} 場，共 {len(runners)} 匹馬")
            time.sleep(1.2)

if __name__ == "__main__":
    sample_dates = ["2024/06/19", "2024/06/23"]
    batch_scrape(sample_dates)
