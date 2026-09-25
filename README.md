# 香港賽馬 AI 預測模型系統 (HKJC AI System)

本專案包含香港賽馬會賽果爬蟲與 FastAPI 後端預測介面骨架。

## 快速使用指引

1. **安裝 Python 環境**
   請確保已安裝 Python 3.9 或以上版本。
   在終端機執行：
   ```bash
   pip install -r requirements.txt
   ```

2. **設定資料庫**
   若尚未設定雲端 PostgreSQL (如 Supabase)，系統預設會自動在本地生成 SQLite 資料庫 (`sqlite:///./hkjc_local.db`)。

3. **執行賽果爬蟲**
   抓取近期歷史賽事並寫入資料庫：
   ```bash
   python -m scraper.hkjc_scraper
   ```

4. **啟動 FastAPI 後端**
   ```bash
   uvicorn backend.main:app --reload --port 8000
   ```
   啟動後，打開瀏覽器訪問：
   http://localhost:8000/docs
   即可查看並測試所有 API。
