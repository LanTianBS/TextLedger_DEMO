from Crypto.Cipher import AES
import base64
import os


# 取得 AES 金鑰，優先使用環境變數，否則 fallback 為預設值
key = os.environ.get('SECRET_KEY', 'thisisaverysecret')

def fix_key(key):
    # 只允許 16、24、32 bytes，超過則截斷，不足則補 0
    if len(key) < 16:
        key = key.ljust(16, '0')
    elif 16 < len(key) < 24:
        key = key.ljust(24, '0')
    elif 24 < len(key) < 32:
        key = key.ljust(32, '0')
    elif len(key) > 32:
        key = key[:32]
    return key.encode('utf-8')

#功能：對資料進行填充，使其長度符合 AES 加密的要求（16 的倍數）。
#原理：根據資料長度不足的部分，填充相應的字元。
def pad(data):
    # 保證 data 是 str
    if not isinstance(data, str):
        data = str(data)
    pad_len = 16 - (len(data.encode('utf-8')) % 16)
    return data + chr(pad_len) * pad_len
#功能：移除加密後資料的填充部分，還原原始資料。
#原理：根據填充的字元數量進行裁剪。
def unpad(data):
    pad_len = ord(data[-1])
    return data[:-pad_len]
#功能：使用 AES 加密資料。
#原理：採用 ECB 模式，將資料加密後轉為 Base64 編碼以便儲存。
def encrypt_aes(data):
    # 保證 data 是 str
    if not isinstance(data, str):
        data = str(data)
    cipher = AES.new(fix_key(key), AES.MODE_ECB)
    padded = pad(data)
    encrypted = cipher.encrypt(padded.encode('utf-8'))
    return base64.b64encode(encrypted).decode('utf-8')
#功能：解密 AES 加密的資料。
#原理：將 Base64 編碼的加密資料解碼後，使用 AES 解密並去除填充。
def decrypt_aes(encrypted_data):
    cipher = AES.new(fix_key(key), AES.MODE_ECB)
    decrypted = cipher.decrypt(base64.b64decode(encrypted_data))
    return unpad(decrypted.decode('utf-8'))

















import json
from linebot.v3.messaging import QuickReply, QuickReplyItem, URIAction
from flask import request


def create_transaction_flex_message(transaction):
    # 根據交易類型設定標題和顏色
    if transaction.tx_type == "收入":
        header_text = "收入記錄"
        header_color = "#01B468"  # 綠色
    else:  # 預設為支出
        header_text = "支出記錄"
        header_color = "#FF5274"  # 紅色

    # 檢查是否有細項
    has_items = transaction.items and json.loads(transaction.items)

    flex_message = {
        "type": "bubble",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": header_text,
                    "weight": "bold",
                    "size": "xl",
                    "color": "#ffffff"
                }
            ],
            "height": "60px",
            "backgroundColor": header_color,
            "paddingTop": "lg"
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "box",
                    "layout": "horizontal",
                    "contents": [
                        {
                            "type": "text",
                            "text": "描述",
                            "size": "sm",
                            "color": "#555555"
                        },
                        {
                            "type": "text",
                            "text": transaction.description,
                            "size": "sm",
                            "wrap": True,
                            "align": "end"
                        }
                    ]
                },
                {
                    "type": "box",
                    "layout": "horizontal",
                    "contents": [
                        {
                            "type": "text",
                            "text": "金額",
                            "size": "sm",
                            "color": "#555555"
                        },
                        {
                            "type": "text",
                            "text": f"NT$ {transaction.amount}",
                            "size": "sm",
                            "wrap": True,
                            "align": "end",
                            "weight": "bold"
                        }
                    ],
                    "margin": "md"
                },
                {
                    "type": "box",
                    "layout": "horizontal",
                    "contents": [
                        {
                            "type": "text",
                            "text": "類別",
                            "size": "sm",
                            "color": "#555555"
                        },
                        {
                            "type": "text",
                            "text": transaction.category.name,
                            "size": "sm",
                            "wrap": True,
                            "align": "end"
                        }
                    ],
                    "margin": "md"
                },
                {
                    "type": "box",
                    "layout": "horizontal",
                    "contents": [
                        {
                            "type": "text",
                            "text": "類型",
                            "size": "sm",
                            "color": "#555555"
                        },
                        {
                            "type": "text",
                            "text": transaction.tx_type,
                            "size": "sm",
                            "wrap": True,
                            "align": "end"
                        }
                    ],
                    "margin": "md"
                },
                {
                    "type": "box",
                    "layout": "horizontal",
                    "contents": [
                        {
                            "type": "text",
                            "text": "日期",
                            "size": "sm",
                            "color": "#555555"
                        },
                        {
                            "type": "text",
                            "text": transaction.date.strftime('%Y-%m-%d %H:%M'),
                            "size": "sm",
                            "wrap": True,
                            "align": "end"
                        }
                    ],
                    "margin": "md"
                }
            ],
            "spacing": "md",
            "paddingAll": "12px"
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "button",
                    "action": {
                        "type": "uri",
                        "label": "編輯",
                        "uri": f"https://{request.host}/edit_transaction?transaction_id={transaction.id}&source=line"
                    },
                    "style": "primary",
                    "color": "#8A8A8A",
                    "height": "sm",
                    "offsetBottom": "sm"
                }
            ]
        }
    }

    # 如果有細項，新增顯示明細按鈕
    if has_items:
        flex_message["footer"]["contents"].append({
            "type": "button",
            "action": {
                "type": "postback",
                "label": "查看明細",
                "data": f"show_details_{transaction.id}"
            },
            "style": "primary",
            "color": "#8A8A8A",
            "height": "sm"
        })

    return flex_message

def create_transaction_details_flex_message(transaction):
    items = json.loads(transaction.items)
    flex_message = {
        "type": "bubble",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "交易明細",
                    "weight": "bold",
                    "size": "xl",
                    "color": "#ffffff"
                }
            ],
            "height": "60px",
            "backgroundColor": "#969696",
            "paddingTop": "lg"
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "以下是交易的細項：",
                    "size": "sm",
                    "color": "#555555",
                    "wrap": True
                }
            ] + [
                {
                    "type": "box",
                    "layout": "horizontal",
                    "contents": [
                        {
                            "type": "text",
                            "text": item.get("sub_description", "無描述"),
                            "size": "sm",
                            "color": "#555555",
                            "wrap": True
                        },
                        {
                            "type": "text",
                            "text": f"NT$ {item.get('sub_amount', 0)}",
                            "size": "sm",
                            "wrap": True,
                            "align": "end",
                            "weight": "bold"
                        }
                    ],
                    "margin": "md"
                } for item in items
            ],
            "spacing": "md",
            "paddingAll": "12px"
        }
    }
    return flex_message


def create_quick_reply(user_id):
    return QuickReply(items=[
        QuickReplyItem(
            action=URIAction(
                label="設置", 
                uri=f"https://{request.host}/settings?user_id={user_id}"
            )
        ),
        QuickReplyItem(
            action=URIAction(
                label="公告", 
                uri=f"https://{request.host}/"
            )
        ),
        QuickReplyItem(
            action=URIAction(
                label="查看明細", 
                uri=f"https://{request.host}/history?user_id={user_id}"
            )
        ),
        QuickReplyItem(
            action=URIAction(
                label="查看分析", 
                uri=f"https://{request.host}/analysis?user_id={user_id}"
            )
        ),
        QuickReplyItem(
            action=URIAction(
                label="提供意見", 
                uri=f"https://{request.host}/feedback"
            )
        )
    ])

def create_transaction_tip_list(flex_message, data):
    flex_message['body']['contents'].append({
        "type": "box",
        "layout": "vertical",
        "contents": [
            {
                "type": "separator"
            },
            {
                "type": "text",
                "text": "消費分析" if data.get('type') == '支出' else "收入分析",
                "size": "md",
                "color": "#555555",
                "weight": "bold"
            },
            {
                "type": "text",
                "text": data['tip'],
                "size": "sm",
                "wrap": True,
                "color": "#000000",
                "margin": "md"
            }
        ],
        "margin": "md"
    })