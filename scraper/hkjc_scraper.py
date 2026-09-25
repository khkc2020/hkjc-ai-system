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

def parse_racecard(race_date_str: str, race_no: int):
    """
    抓取未開跑賽事的正式排位表 (RaceCard.aspx)
    race_date_str 格式: YYYY/MM/DD
    """
    url = f"https://racing.hkjc.com/racing/information/Chinese/racing/RaceCard.aspx?RaceDate={race_date_str}&RaceNo={race_no}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code != 200:
            return None, []
    except Exception as err:
        print(f"排位表連線出錯: {err}")
        return None, []

    # 檢查是否被馬會跳轉到非目標日期或場次
    if race_date_str not in resp.url and f"RaceNo={race_no}" not in resp.url:
        print(f"被馬會跳轉，目標場次可能不存在: {resp.url}")
        return None, []

    soup = BeautifulSoup(resp.content, "html.parser")
    
    # 檢查該場次資訊
    race_info_text = ""
    race_tab = soup.find("div", {"class": "race_tab"}) or soup.find("div", {"class": "rowDiv10"})
    if race_tab:
        race_info_text = race_tab.text
    else:
        # 尋找頁面中含有「第 X 場」的標題
        for div in soup.find_all(["div", "td", "span"]):
            if f"第 {race_no} 場" in div.text or f"第{race_no}場" in div.text:
                race_info_text = div.text
                break

    venue = "ST" if "沙田" in race_info_text else ("HV" if "跑馬地" in race_info_text else "ST")
    track_type = "全天候跑道" if "全天候" in race_info_text or "泥地" in race_info_text else "草地"
    
    dist_match = re.search(r'(\d{3,4})米', race_info_text)
    distance = int(dist_match.group(1)) if dist_match else 1200
    
    # 優先匹配第1-5班，杜絕頂部導航欄「二級賽」干擾
    class_match = re.search(r'(第[一二三四五]班)', race_info_text)
    if not class_match:
        class_match = re.search(r'(國際[一二三]級賽|香港[一二三]級賽|[一二三]級賽|新馬賽)', race_info_text)
    race_class = class_match.group(1) if class_match else f"第 {race_no} 場賽事"

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

    # 尋找排位表格 (draggable 或 table_bd)
    table = soup.find("table", {"class": "draggable"}) or soup.find("table", {"class": "table_bd"}) or soup.find("table", {"id": "racecardlist"})
    if not table:
        return race_data, []

    runners = []
    rows = table.find_all("tr")
    for r in rows:
        cols = r.find_all("td")
        if len(cols) < 8:
            continue

        h_no_text = cols[0].text.strip()
        if not h_no_text.isdigit():
            continue
        horse_no = int(h_no_text)

        # 找尋馬名和烙號欄位
        horse_info = ""
        for c in cols[1:5]:
            t = c.text.strip()
            if re.search(r'[\u4e00-\u9fa5]', t): # 包含中文
                horse_info = t
                break

        code_match = re.search(r'\((.*?)\)', horse_info)
        horse_code = code_match.group(1) if code_match else f"H_{horse_no}"
        horse_name = re.sub(r'\(.*?\)', '', horse_info).strip()

        # 負磅、騎練、檔位解析
        weight = None
        draw = None
        jockey = "待定"
        trainer = "待定"
        rating = 60

        for col in cols:
            text = col.text.strip()
            if text.isdigit() and 100 <= int(text) <= 140 and weight is None:
                weight = float(text)
            elif text.isdigit() and 1 <= int(text) <= 15 and draw is None and text != str(horse_no):
                draw = int(text)
            elif text.isdigit() and 20 <= int(text) <= 135 and rating == 60:
                rating = int(text)

        # 默認賠率（賽前排位暫無實時賠率時給予預設值）
        odds = 5.0 + (draw or 5) * 1.5

        runners.append({
            "race_id": formatted_id,
            "horse_no": horse_no,
            "horse_code": horse_code,
            "horse_name": horse_name,
            "draw": draw or (horse_no % 12 + 1),
            "declared_weight": weight or 120.0,
            "horse_body_weight": 1100,
            "jockey": jockey,
            "trainer": trainer,
            "rating": rating,
            "live_odds": odds,
            "finish_position": None,
            "finish_time": None
        })

    return race_data, runners

def parse_race_results(race_date_str: str, race_no: int):
    """
    抓取已完成賽事的正式賽果 (LocalResults.aspx)
    """
    url = f"https://racing.hkjc.com/racing/information/Chinese/racing/LocalResults.aspx?RaceDate={race_date_str}&RaceNo={race_no}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code != 200:
            return None, []
    except Exception as err:
        return None, []

    # 檢查是否被馬會跳轉到非目標日期或非目標場次
    if race_date_str not in resp.url or f"RaceNo={race_no}" not in resp.url:
        print(f"賽果頁面跳轉至其他日期或場次，跳過: {resp.url}")
        return None, []

    soup = BeautifulSoup(resp.content, "html.parser")
    race_info_div = soup.find("div", {"class": "race_tab"})
    if not race_info_div:
        return None, []

    info_text = race_info_div.text
    # 確保頁面內容確實是該場次
    if f"第 {race_no} 場" not in info_text and f"第{race_no}場" not in info_text:
        return None, []

    venue = "ST" if "沙田" in info_text else ("HV" if "跑馬地" in info_text else "ST")
    track_type = "全天候跑道" if "全天候" in info_text else "草地"
    
    dist_match = re.search(r'(\d{3,4})米', info_text)
    distance = int(dist_match.group(1)) if dist_match else 1200
    
    class_match = re.search(r'(第[一二三四五]班)', info_text)
    if not class_match:
        class_match = re.search(r'(國際[一二三]級賽|香港[一二三]級賽|[一二三]級賽|新馬賽)', info_text)
    race_class = class_match.group(1) if class_match else f"第 {race_no} 場"

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

def fetch_any_race(date_str: str, race_no: int):
    """
    智能抓取：先嘗試抓取排位表 (RaceCard)，若無則嘗試抓取正式賽果 (LocalResults)
    """
    # 1. 優先嘗試排位表 (即將到來賽事)
    r_info, runners = parse_racecard(date_str, race_no)
    if r_info and runners:
        return r_info, runners

    # 2. 嘗試正式賽果 (歷史已完賽賽事)
    r_info, runners = parse_race_results(date_str, race_no)
    if r_info and runners:
        return r_info, runners

    return None, []

def save_to_db(race_dict, runners_list):
    db = SessionLocal()
    try:
        # 先刪除該場次舊有資料，確保乾淨獨立不被錯誤數據污染
        db.query(RaceRunner).filter(RaceRunner.race_id == race_dict["race_id"]).delete()
        db.query(Race).filter(Race.race_id == race_dict["race_id"]).delete()
        db.commit()

        race = Race(**race_dict)
        db.add(race)
        db.commit()

        for runner_data in runners_list:
            runner = RaceRunner(**runner_data)
            db.add(runner)
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"資料庫存入出錯: {e}")
    finally:
        db.close()
