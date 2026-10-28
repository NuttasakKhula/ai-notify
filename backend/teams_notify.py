from dotenv import load_dotenv
import os
import requests

# ใช้ __file__ เพื่อหา path ของไฟล์นี้เองอัตโนมัติ ไม่ต้อง hardcode path
# วิธีนี้ทำให้ load_dotenv() หาไฟล์เจอเสมอ ไม่ว่าจะรันจาก working
# directory ไหนก็ตาม (เดิม load_dotenv() แบบไม่ระบุ path จะหาไฟล์จาก
# current working directory ซึ่งอาจไม่ตรงกับโฟลเดอร์ของสคริปต์)
#
# หมายเหตุ: ไฟล์ env จริงในโปรเจกต์นี้ชื่อ "Notify.env" (ไม่ใช่ ".env" เฉยๆ)
# ถ้าจะเปลี่ยนชื่อไฟล์เป็น ".env" ในอนาคต ให้แก้ตรงนี้กลับเป็น ".env"
_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Notify.env")
load_dotenv(dotenv_path=_ENV_PATH)

WEBHOOK = os.getenv("TEAMS_WEBHOOK_URL")

if not WEBHOOK:
    raise RuntimeError(
        f"TEAMS_WEBHOOK_URL not found. Checked .env at: {_ENV_PATH}. "
        "ตรวจสอบว่าไฟล์อยู่ตรงนั้นจริง และชื่อ key ตรงกันเป๊ะ"
    )


class TeamsNotifier:

    def __init__(self):
        self.webhook = WEBHOOK

    def send_ai_report(self, report_text):

        payload = {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": {
                        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                        "type": "AdaptiveCard",
                        "version": "1.5",

                        "body": [

                            {
                                "type": "TextBlock",
                                "text": "🚨 AI Network Root Cause Analysis",
                                "size": "Large",
                                "weight": "Bolder",
                                "color": "Attention"
                            },

                            {
                                "type": "Container",
                                "style": "emphasis",
                                "spacing": "Medium",
                                "items": [
                                    {
                                        "type": "TextBlock",
                                        "text": report_text,
                                        "wrap": True,
                                        # ไม่ใส่ fontType: Monospace เพื่อให้ markdown ที่ AI
                                        # ตอบมา (เช่น **หัวข้อ**, bullet ด้วย "- ") render
                                        # เป็นตัวหนา/bullet จริง แทนที่จะโชว์ ** ตรงๆ แบบตัวอักษรดิบ
                                        "size": "Small"
                                    }
                                ]
                            }

                        ]
                    }
                }
            ]
        }

        r = requests.post(
            self.webhook,
            json=payload,
            timeout=30
        )

        if r.status_code != 200:

            print(r.status_code)
            print(r.text)