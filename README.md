# THSR Crawler

爬取台灣高鐵班次、停靠時刻與票價，寫入 PostgreSQL 資料庫。
資料來源：[交通部 TDX 平台](https://tdx.transportdata.tw)

## 取得 TDX API 金鑰

1. 前往 https://tdx.transportdata.tw 免費註冊
2. 進入「API 金鑰管理」取得 `client_id` 與 `client_secret`

## 安裝

```bash
pip install -r requirements.txt
cp .env.example .env
# 填入 TDX_CLIENT_ID、TDX_CLIENT_SECRET、DATABASE_URL
```

## 執行

```bash
# 爬今天起 7 天的班次 + 票價（預設）
python main.py

# 爬特定日期
python main.py --date 2026-06-15

# 只更新票價
python main.py --prices-only

# 用 GeneralTimetable（不依日期，適合只需要班次結構時）
python main.py --general --date 2026-06-01
```

## 資料說明

| TDX 來源 | 寫入資料表 |
|----------|-----------|
| `DailyTimetable` | `trains`, `schedules`, `stop_times` |
| `ODFare` | `ticket_prices` |

爬蟲使用 `ON CONFLICT DO UPDATE`，重複執行是安全的（冪等）。
