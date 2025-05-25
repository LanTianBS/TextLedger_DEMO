import os
import logging
import google.generativeai as genai
from typing import Optional, Dict, Any
from dotenv import load_dotenv
import json
import re
import datetime
load_dotenv()

# 使用API密鑰配置Google Generative AI
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)

# 配置日誌記錄
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
# 處裡文字訊息
def process_message(message: str, now: str) -> Optional[Dict[str, Any]]:
    if not GEMINI_API_KEY:
        logger.error("Gemini API密鑰未配置。")
        return None
    
    try:
        # 配置模型
        model = genai.GenerativeModel('gemini-2.0-flash')        
        # 設定生成配置
        generation_config = genai.GenerationConfig(
            temperature=0.1,
        )
        # 準備帶有詳細指示的提示
        prompt = """
        請幫我分析以下訊息中的金融交易資訊，並以 JSON 格式回傳以下欄位：
        1. **amount**: 金額數字（僅數字，無需貨幣符號）
        2. **description**: 交易描述
        3. **category**: 交易類別（只能有以下9大類：食物、交通、娛樂、住宿、購物、教育、醫療、收入、其他）
        4. **type**: 交易類型（支出或收入）
        5. **items（可選）**: 如果交易中包含多個細項，請回傳細項列表，每個細項包含：
        - **sub_description**: 細項描述
        - **sub_amount**: 細項金額
        - **sub_category**: 細項分類
        6. **如果交易描述中含有「總共」等詞彙，請確保細項金額相加等於總金額**
        7. **如果交易訊息中出現「可能的店名」或「品牌名稱」，請保留在 description 欄位**，例如：「全家買了早餐」→ "description": "全家早餐"
        8. **如果訊息包含計算，請提供計算結果**，如「一個蘋果 5 元，買了 3 個，總共 15 元」
        9. **如果訊息中有多筆交易，請將它們分開回傳為多個JSON物件,且請記住多筆JSON之間要用逗號分隔**，例如：{"amount": 5000, "description": "薪水", "category": "收入", "type": "收入"}, {"amount": 2000, "description": "下班吃飯", "category": "食物", "type": "支出"}, {"amount": 1000, "description": "電影票", "category": "娛樂", "type": "支出"}  這樣的格式。請注意，JSON物件之間的逗號是必要的。
        10. **請新增一個欄位 tip，運來儲存對該筆消費的評論，評論應包含消費感受、背景、建議以及對該筆消費的評價，並考慮當前時間與消費行為的關係，給予合理的建議關心使用者的身心健康**。
        11. **請勿回傳多餘的文字，只回傳 JSON 格式的回應**

        範例：

        - 訊息："寶雅買了一堆東西，飲料花了50，泡麵花了150，日用品花了100，總共花了280"
        - 回應：
        [{"amount": 280, "description": "寶雅消費", "category": "購物", "type": "支出", "items": [{"sub_description": "飲料", "sub_amount": 50, "sub_category": "食物"}, {"sub_description": "泡麵", "sub_amount": 150, "sub_category": "食物"}, {"sub_description": "日用品", "sub_amount": 100, "sub_category": "日用品"}], "tip": "寶雅購物很划算，特別是日用品的價格相當實惠，這次購物滿足了日常需求，建議多留意促銷活動，整體來說是一次非常值得的消費。"}]

        - 訊息："全家買了早餐，三明治 50 元，咖啡 70 元，總共 120 元"
        - 回應：
        [{"amount": 120, "description": "全家早餐", "category": "食物", "type": "支出", "items": [{"sub_description": "三明治", "sub_amount": 50, "sub_category": "食物"}, {"sub_description": "咖啡", "sub_amount": 70, "sub_category": "食物"}], "tip": "早餐很美味，咖啡香氣濃郁，搭配三明治是完美的早晨組合，這筆消費讓早晨充滿活力，建議可以嘗試其他口味的咖啡。"}]

        - 訊息："今天領薪水 5000 元，下班吃飯花了 2000 元"
        - 回應：
        [{"amount": 5000, "description": "薪水", "category": "收入", "type": "收入", "items": [], "tip": "辛苦工作值得，這筆薪水可以用來計劃未來的支出與儲蓄，建議分配一部分用於投資或學習，整體來說是一筆重要的收入。"}, {"amount": 2000, "description": "下班吃飯", "category": "食物", "type": "支出", "items": [], "tip": "晚餐很滿足，適合放鬆心情，這次選擇的餐廳氛圍很好，建議偶爾也可以嘗試新的餐廳，這筆消費值得。"}]

        - 訊息："全聯買了3顆70元的蘋果，家樂福買了2顆40元的蘋果"
        - 回應：[{"amount": 210, "description": "全聯蘋果", "category": "食物", "type": "支出", "items": [{"sub_description": "蘋果", "sub_amount": 210, "sub_category": "食物"}], "tip": "蘋果很新鮮，價格合理，適合日常補充維生素，這次購買的數量剛好滿足需求，建議下次可以多買一些以備不時之需。"}, {"amount": 80, "description": "家樂福蘋果", "category": "食物", "type": "支出", "items": [{"sub_description": "蘋果", "sub_amount": 80, "sub_category": "食物"}], "tip": "家樂福的蘋果價格實惠，適合日常購買，建議多留意促銷活動，這次購買的數量剛好滿足需求。"}]

        - 訊息："凌晨3點去便利商店買了泡麵和飲料，花了100元"
        - 回應：[{"amount": 100, "description": "便利商店消費", "category": "食物", "type": "支出", "items": [{"sub_description": "泡麵", "sub_amount": 60, "sub_category": "食物"}, {"sub_description": "飲料", "sub_amount": 40, "sub_category": "食物"}], "tip": "凌晨消費可能是因為加班或宵夜需求，建議注意健康飲食，避免過多宵夜影響睡眠品質。"}]

        - 訊息："半夜4點去711買了泡麵和飲料，花了100元"
        - 回應：[{"amount": 100, "description": "711消費", "category": "食物", "type": "支出", "items": [{"sub_description": "泡麵", "sub_amount": 60, "sub_category": "食物"}, {"sub_description": "飲料", "sub_amount": 40, "sub_category": "食物"}], "tip": "半夜的消費可能是因為工作或學習需要，建議注意飲食健康，避免過多的油炸食品。"}]
        如果無法解析交易資訊，請回傳空的 JSON 物件 []。
        請確保回應的格式正確，並且符合上述要求，且符合正確的 JSON 格式。
        目前的時間是 {now}，根據這個時間來分析交易的背景和建議，但不是每一筆交易都要提及時間，請注意。
        例如，如果現在是凌晨3點，請考慮到這個時間點的消費習慣和建議。
        用戶訊息：{message}
        """
        now_str = now.strftime('%Y-%m-%d %H:%M:%S') if isinstance(now, datetime.datetime) else str(now)
        prompt = prompt.replace("{message}", message).replace("{now}", now_str)
        #logger.debug(f"Gemini提示: {prompt}")

        # 從Gemini生成回應
        response = model.generate_content(prompt, generation_config=generation_config)    
        #logger.debug(f"Gemini回應: {response.text}")    
        
        # 修正 JSON 格式的處理
        response_text = response.text
        if response_text.startswith("```") and "```" in response_text[3:]:
            first_marker = response_text.find("```")
            last_marker = response_text.rfind("```")
            content_start = response_text.find("\n", first_marker) + 1
            content_end = last_marker
            response_text = response_text[content_start:content_end].strip()
            
        # 清除多餘的逗號（例如在 JSON 物件的末尾）
        response_text = re.sub(r',\s*}', '}', response_text)
        #logger.debug(f"清理後的回應: {response_text}")
        # 使用 JSONDecoder 解碼 JSON 字串
        decoder = json.JSONDecoder()
        transactions = []
        pos = 0
        while pos < len(response_text):
            try:
                obj, pos = decoder.raw_decode(response_text, pos)
                transactions.append(obj)
            except json.JSONDecodeError as e:
                logger.error(f"解析 JSON 時出錯: {e}")
                break
        
        if transactions:
            # 如果只有一筆交易，返回單一字典
            if len(transactions) == 1:
                return transactions[0]
            # 如果有多筆交易，返回整個列表
            return transactions
        else:
            logger.warning("未提取到有效的交易數據。")
            return None
    except Exception as e:
        logger.error(f"使用Gemini處理訊息時出錯: {str(e)}")
        return None
    

    
from PIL import Image
from io import BytesIO
# 處理圖片訊息
def process_image(image_data):
    if not GEMINI_API_KEY:
        logger.error("Gemini API密鑰未配置。")
        return None

    try:
        # 配置模型
        model = genai.GenerativeModel('gemini-2.0-flash')
        
        # 設定生成配置
        generation_config = genai.GenerationConfig(
            temperature=0.1,
        )
        image = Image.open(BytesIO(image_data))
        # 準備提示
        prompt = """
        請分析以下圖片，請先確認圖片是否為收據或發票，並敘將述內容轉換為 JSON 格式，並包含以下欄位：
        1. **amount**: 金額數字（僅數字，無需貨幣符號）
        2. **description**: 交易描述
        3. **category**: 交易類別（只能有以下9大類：食物、交通、娛樂、住宿、購物、教育、醫療、收入、其他）
        4. **type**: 交易類型（支出或收入）
        5. **items（可選）**: 如果交易中包含多個細項，請回傳細項列表，每個細項包含：
        - **sub_description**: 細項描述
        - **sub_amount**: 細項金額
        - **sub_category**: 細項分類
        6. **如果交易描述中含有「總共」等詞彙，請確保細項金額相加等於總金額**
        7. **如果交易明細圖片中出現「可能的店名」或「品牌名稱」，請保留在 description 欄位**，例如：「全家買了早餐」→ "description": "全家早餐"
        8. **如果明細圖片包含計算，請提供計算結果**，如「一個蘋果 5 元，買了 3 個，總共 15 元」
        9. **如果明細圖片中有多筆交易的明細貨發票，請將它們分開回傳為多個JSON物件,且請記住多筆JSON之間要用逗號分隔**，例如：{"amount": 5000, "description": "薪水", "category": "收入", "type": "收入"}, {"amount": 2000, "description": "下班吃飯", "category": "食物", "type": "支出"}, {"amount": 1000, "description": "電影票", "category": "娛樂", "type": "支出"}  這樣的格式。請注意，JSON物件之間的逗號是必要的。
        10. **請新增一個欄位 tip，運來儲存對該筆消費的評論，評論應包含消費感受、背景、建議以及對該筆消費的評價，並考慮當前時間與消費行為的關係，給予合理的建議關心使用者的身心健康**。
        11. **請勿回傳多餘的文字，只回傳 JSON 格式的回應**

        範例：

        - 明細圖片："寶雅買了一堆東西，飲料花了50，泡麵花了150，日用品花了100，總共花了280"
        - 回應：
        [{"amount": 280, "description": "寶雅消費", "category": "購物", "type": "支出", "items": [{"sub_description": "飲料", "sub_amount": 50, "sub_category": "食物"}, {"sub_description": "泡麵", "sub_amount": 150, "sub_category": "食物"}, {"sub_description": "日用品", "sub_amount": 100, "sub_category": "日用品"}], "tip": "寶雅購物很划算，特別是日用品的價格相當實惠，這次購物滿足了日常需求，建議多留意促銷活動，整體來說是一次非常值得的消費。"}]

        - 明細圖片："全家買了早餐，三明治 50 元，咖啡 70 元，總共 120 元"
        - 回應：
        [{"amount": 120, "description": "全家早餐", "category": "食物", "type": "支出", "items": [{"sub_description": "三明治", "sub_amount": 50, "sub_category": "食物"}, {"sub_description": "咖啡", "sub_amount": 70, "sub_category": "食物"}], "tip": "早餐很美味，咖啡香氣濃郁，搭配三明治是完美的早晨組合，這筆消費讓早晨充滿活力，建議可以嘗試其他口味的咖啡。"}]

        - 明細圖片："今天領薪水 5000 元，下班吃飯花了 2000 元"
        - 回應：
        [{"amount": 5000, "description": "薪水", "category": "收入", "type": "收入", "items": [], "tip": "辛苦工作值得，這筆薪水可以用來計劃未來的支出與儲蓄，建議分配一部分用於投資或學習，整體來說是一筆重要的收入。"}, {"amount": 2000, "description": "下班吃飯", "category": "食物", "type": "支出", "items": [], "tip": "晚餐很滿足，適合放鬆心情，這次選擇的餐廳氛圍很好，建議偶爾也可以嘗試新的餐廳，這筆消費值得。"}]

        - 明細圖片："全聯買了3顆70元的蘋果，家樂福買了2顆40元的蘋果"
        - 回應：[{"amount": 210, "description": "全聯蘋果", "category": "食物", "type": "支出", "items": [{"sub_description": "蘋果", "sub_amount": 210, "sub_category": "食物"}], "tip": "蘋果很新鮮，價格合理，適合日常補充維生素，這次購買的數量剛好滿足需求，建議下次可以多買一些以備不時之需。"}, {"amount": 80, "description": "家樂福蘋果", "category": "食物", "type": "支出", "items": [{"sub_description": "蘋果", "sub_amount": 80, "sub_category": "食物"}], "tip": "家樂福的蘋果價格實惠，適合日常購買，建議多留意促銷活動，這次購買的數量剛好滿足需求。"}]

        - 明細圖片："凌晨3點去便利商店買了泡麵和飲料，花了100元"
        - 回應：[{"amount": 100, "description": "便利商店消費", "category": "食物", "type": "支出", "items": [{"sub_description": "泡麵", "sub_amount": 60, "sub_category": "食物"}, {"sub_description": "飲料", "sub_amount": 40, "sub_category": "食物"}], "tip": "凌晨消費可能是因為加班或宵夜需求，建議注意健康飲食，避免過多宵夜影響睡眠品質。"}]

        - 明細圖片："半夜4點去711買了泡麵和飲料，花了100元"
        - 回應：[{"amount": 100, "description": "711消費", "category": "食物", "type": "支出", "items": [{"sub_description": "泡麵", "sub_amount": 60, "sub_category": "食物"}, {"sub_description": "飲料", "sub_amount": 40, "sub_category": "食物"}], "tip": "半夜的消費可能是因為工作或學習需要，建議注意飲食健康，避免過多的油炸食品。"}]
        **特別注意圖片中可能會有多張收據或發票，請將它們分開回傳為多個JSON物件,且請記住多筆JSON之間要用逗號分隔，並且請確保 JSON 格式正確。
        **如果無法解析交易資訊或你發現並不是收據或發票，請回傳，請回傳空的 JSON 物件 []。
        **請確保回應的格式正確，並且符合上述要求，且符合正確的 JSON 格式。
        **不准有 markdown 的格式，請直接回傳 JSON 格式的回應。
        **不准有多餘的文字，只回傳 JSON 格式的回應**
        **目前的時間是 {now}，根據這個時間來分析交易的背景和建議，但不是每一筆交易都要提及時間，請注意。
        **例如，如果現在是凌晨3點，請考慮到這個時間點的消費習慣和建議。
        """

        # 從Gemini生成回應
        response = model.generate_content([prompt, image], generation_config=generation_config)


        # 修正 JSON 格式的處理
        response_text = response.text
        if response_text.startswith("```") and "```" in response_text[3:]:
            first_marker = response_text.find("```")
            last_marker = response_text.rfind("```")
            content_start = response_text.find("\n", first_marker) + 1
            content_end = last_marker
            response_text = response_text[content_start:content_end].strip()
            
        # 清除多餘的逗號（例如在 JSON 物件的末尾）
        response_text = re.sub(r',\s*}', '}', response_text)
        #logger.debug(f"清理後的回應: {response_text}")
        # 使用 JSONDecoder 解碼 JSON 字串
        decoder = json.JSONDecoder()
        transactions = []
        pos = 0
        while pos < len(response_text):
            try:
                obj, pos = decoder.raw_decode(response_text, pos)
                transactions.append(obj)
            except json.JSONDecodeError as e:
                logger.error(f"解析 JSON 時出錯: {e}")
                break
        
        if transactions:
            # 如果只有一筆交易，返回單一字典
            if len(transactions) == 1:
                return transactions[0]
            # 如果有多筆交易，返回整個列表
            return transactions
        else:
            logger.warning("未提取到有效的交易數據。")
            return None
    except Exception as e:
        logger.error(f"使用Gemini處理圖片時出錯: {str(e)}")
        return None

# 處裡語音訊息
def process_audio(audio_data):
    if not GEMINI_API_KEY:
        logger.error("Gemini API密鑰未配置。")
        return None

    try:
        # 配置模型
        model = genai.GenerativeModel('gemini-2.0-flash')
        
        # 設定生成配置
        generation_config = genai.GenerationConfig(
            temperature=0.1,
        )
        # 準備提示
        prompt = """
        請分析以下語音訊息，請先確認語音訊息是否為收據或發票，並敘將述內容轉換為 JSON 格式，並包含以下欄位：
        1. **amount**: 金額數字（僅數字，無需貨幣符號）
        2. **description**: 交易描述
        3. **category**: 交易類別（只能有以下9大類：食物、交通、娛樂、住宿、購物、教育、醫療、收入、其他）
        4. **type**: 交易類型（支出或收入）
        5. **items（可選）**: 如果交易中包含多個細項，請回傳細項列表，每個細項包含：
        - **sub_description**: 細項描述
        - **sub_amount**: 細項金額
        - **sub_category**: 細項分類
        6. **如果交易描述中含有「總共」等詞彙，請確保細項金額相加等於總金額**
        7. **如果交易語音訊息中出現「可能的店名」或「品牌名稱」，請保留在 description 欄位**，例如：「全家買了早餐」→ "description": "全家早餐"
        8. **如果語音訊息包含計算，請提供計算結果**，如「一個蘋果 5 元，買了 3 個，總共 15 元」
        9. **如果語音訊息中有多筆交易的明細貨發票，請將它們分開回傳為多個JSON物件,且請記住多筆JSON之間要用逗號分隔**，例如：{"amount": 5000, "description": "薪水", "category": "收入", "type": "收入"}, {"amount": 2000, "description": "下班吃飯", "category": "食物", "type": "支出"}, {"amount": 1000, "description": "電影票", "category": "娛樂", "type": "支出"}  這樣的格式。請注意，JSON物件之間的逗號是必要的。
        10. **請新增一個欄位 tip，運來儲存對該筆消費的評論，評論應包含消費感受、背景、建議以及對該筆消費的評價，並考慮當前時間與消費行為的關係，給予合理的建議關心使用者的身心健康**。
        11. **請勿回傳多餘的文字，只回傳 JSON 格式的回應**

        範例：

        - 語音訊息："寶雅買了一堆東西，飲料花了50，泡麵花了150，日用品花了100，總共花了280"
        - 回應：
        [{"amount": 280, "description": "寶雅消費", "category": "購物", "type": "支出", "items": [{"sub_description": "飲料", "sub_amount": 50, "sub_category": "食物"}, {"sub_description": "泡麵", "sub_amount": 150, "sub_category": "食物"}, {"sub_description": "日用品", "sub_amount": 100, "sub_category": "日用品"}], "tip": "寶雅購物很划算，特別是日用品的價格相當實惠，這次購物滿足了日常需求，建議多留意促銷活動，整體來說是一次非常值得的消費。"}]

        - 語音訊息："全家買了早餐，三明治 50 元，咖啡 70 元，總共 120 元"
        - 回應：
        [{"amount": 120, "description": "全家早餐", "category": "食物", "type": "支出", "items": [{"sub_description": "三明治", "sub_amount": 50, "sub_category": "食物"}, {"sub_description": "咖啡", "sub_amount": 70, "sub_category": "食物"}], "tip": "早餐很美味，咖啡香氣濃郁，搭配三明治是完美的早晨組合，這筆消費讓早晨充滿活力，建議可以嘗試其他口味的咖啡。"}]

        - 語音訊息："今天領薪水 5000 元，下班吃飯花了 2000 元"
        - 回應：
        [{"amount": 5000, "description": "薪水", "category": "收入", "type": "收入", "items": [], "tip": "辛苦工作值得，這筆薪水可以用來計劃未來的支出與儲蓄，建議分配一部分用於投資或學習，整體來說是一筆重要的收入。"}, {"amount": 2000, "description": "下班吃飯", "category": "食物", "type": "支出", "items": [], "tip": "晚餐很滿足，適合放鬆心情，這次選擇的餐廳氛圍很好，建議偶爾也可以嘗試新的餐廳，這筆消費值得。"}]

        - 語音訊息："全聯買了3顆70元的蘋果，家樂福買了2顆40元的蘋果"
        - 回應：[{"amount": 210, "description": "全聯蘋果", "category": "食物", "type": "支出", "items": [{"sub_description": "蘋果", "sub_amount": 210, "sub_category": "食物"}], "tip": "蘋果很新鮮，價格合理，適合日常補充維生素，這次購買的數量剛好滿足需求，建議下次可以多買一些以備不時之需。"}, {"amount": 80, "description": "家樂福蘋果", "category": "食物", "type": "支出", "items": [{"sub_description": "蘋果", "sub_amount": 80, "sub_category": "食物"}], "tip": "家樂福的蘋果價格實惠，適合日常購買，建議多留意促銷活動，這次購買的數量剛好滿足需求。"}]

        - 語音訊息："凌晨3點去便利商店買了泡麵和飲料，花了100元"
        - 回應：[{"amount": 100, "description": "便利商店消費", "category": "食物", "type": "支出", "items": [{"sub_description": "泡麵", "sub_amount": 60, "sub_category": "食物"}, {"sub_description": "飲料", "sub_amount": 40, "sub_category": "食物"}], "tip": "凌晨消費可能是因為加班或宵夜需求，建議注意健康飲食，避免過多宵夜影響睡眠品質。"}]

        - 語音訊息："半夜4點去711買了泡麵和飲料，花了100元"
        - 回應：[{"amount": 100, "description": "711消費", "category": "食物", "type": "支出", "items": [{"sub_description": "泡麵", "sub_amount": 60, "sub_category": "食物"}, {"sub_description": "飲料", "sub_amount": 40, "sub_category": "食物"}], "tip": "半夜的消費可能是因為工作或學習需要，建議注意飲食健康，避免過多的油炸食品。"}]
        **特別注意語音訊息中可能會有多筆交易內容，請將它們分開回傳為多個JSON物件,且請記住多筆JSON之間要用逗號分隔，並且請確保 JSON 格式正確。
        **如果無法解析交易資訊或你發現並不是交易語音訊息，請回傳，請回傳空的 JSON 物件 []。
        **請確保回應的格式正確，並且符合上述要求，且符合正確的 JSON 格式。
        **不准有 markdown 的格式，請直接回傳 JSON 格式的回應。
        **不准有多餘的文字，只回傳 JSON 格式的回應**
        **目前的時間是 {now}，根據這個時間來分析交易的背景和建議，但不是每一筆交易都要提及時間，請注意。
        **例如，如果現在是凌晨3點，請考慮到這個時間點的消費習慣和建議。
        """

        # 從Gemini生成回應
        response = model.generate_content([prompt, audio_data], generation_config=generation_config)
        if response:
            print(response.text)
            return None
        else:
            logger.error("Gemini回應為空。")
            return None

    except Exception as e:
        logger.error(f"使用Gemini處理語音時出錯: {str(e)}")
        return None
    return None
