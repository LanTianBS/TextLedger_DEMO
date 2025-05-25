# TextLedger

TextLedger 是一個基於 Flask 的財務管理應用，旨在幫助用戶輕鬆記錄和分析交易記錄。該應用支持多種輸入方式，包括文字、圖片和語音，並提供直觀的數據分析和管理功能。

## 功能特性

- **交易記錄管理**：支持用戶新增、編輯和刪除交易記錄。
- **多輸入方式**：支持文字輸入、圖片解析和語音辨識來記錄交易。
- **數據分析**：提供支出和收入的分類統計，以及時間範圍內的數據分析。
- **支出目標**：用戶可以設置支出目標並追蹤進度。
- **管理員功能**：支持公告管理、用戶管理和留言回覆。

## 技術棧

- **後端**：Flask, SQLAlchemy
- **前端**：HTML, CSS, JavaScript (Chart.js)
- **數據庫**：PostgreSQL
- **其他**：Google Cloud Speech-to-Text API, LINE Messaging API

## 環境變數

在啟動專案之前，請確保設置以下環境變數：

- `DB_URL`：PostgreSQL 數據庫連接字串
- `LINE_CHANNEL_ACCESS_TOKEN`：LINE Messaging API 的存取金鑰
- `LINE_CHANNEL_SECRET`：LINE Messaging API 的密鑰
- `SECRET_KEY`：Flask 的密鑰
- `GOOGLE_CREDENTIALS_STR`：Google Cloud 的服務帳戶憑證

## 注意事項

- `GOOGLE_CREDENTIALS_STR` 環境變數需要進行預處理，確保其格式正確。例如，`private_key` 中的換行符需要替換為 `\\`。

## 安裝與啟動

1. 克隆此專案：
   ```bash
   git clone <repository-url>
   cd TextLedger
   ```
2. 安裝依賴：
   ```bash
   pip install -r requirements.txt
   ```
3. 設置環境變數。
4. 啟動應用：
   ```bash
   python main.py
   ```

## 文件結構

- `app.py`：主應用邏輯。
- `utils.py`：輔助函數。
- `templates/`：HTML 模板文件。
- `static/`：靜態資源（CSS 和 JavaScript）。

## 貢獻

歡迎提交問題（Issues）或拉取請求（Pull Requests）來改進此專案。

## 授權

此專案採用 MIT 授權條款。您可以自由使用、修改和分發此專案，但需保留原始版權聲明和授權條款。

## Copyright

© 2025 TextLedger 開發團隊。保留所有權利。
