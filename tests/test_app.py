import unittest
from unittest.mock import patch

from app.api.schemas import ChatRequest
from app.db.database import _format_phone
from app.services.apartment_types import base_neighborhood_name, detect_type
from app.services.chat_service import (
    CRITERIA,
    SESSIONS,
    _prepare_customer_reply,
    _strip_emojis,
    _update_criteria,
    get_session,
    is_greeting,
    process_message,
    reset_session,
)
from app.services.prompts import WELCOME_MESSAGE


MOCK_CONFIG = {
    "city": "الرياض",
    "neighborhoods": ["النرجس 1", "النرجس 3", "العارض 2", "الملز"],
    "neighborhood_groups": ["النرجس", "العارض", "الملز"],
    "neighborhoods_by_type": {
        "studio": ["النرجس 1", "الملز"],
        "one_bedroom": ["النرجس 3", "العارض 2"],
        "two_bedroom": ["النرجس 3"],
    },
    "neighborhood_groups_by_type": {
        "studio": ["النرجس", "الملز"],
        "one_bedroom": ["النرجس", "العارض"],
        "two_bedroom": ["النرجس"],
        "any": ["النرجس", "العارض", "الملز"],
    },
    "available_types_by_neighborhood": {
        "النرجس": ["studio", "one_bedroom", "two_bedroom"],
        "العارض": ["one_bedroom"],
        "الملز": ["studio"],
    },
    "available_types": ["studio", "one_bedroom", "two_bedroom"],
    "price_min": 1800,
    "price_max": 4500,
}


class RealEstateBotTests(unittest.TestCase):
    def setUp(self):
        reset_session("test_phone")

    def test_phone_formatting_strips_bidi_and_normalises(self):
        self.assertEqual(_format_phone("\u202d0501234567\u202c"), "+966501234567")
        self.assertEqual(_format_phone("966 55-111-2222"), "+966551112222")
        self.assertEqual(_format_phone("00966509998888"), "+966509998888")
        self.assertIsNone(_format_phone(""))
        self.assertIsNone(_format_phone(None))

    def test_detect_apartment_type(self):
        self.assertEqual(detect_type("شقة استوديو مفروش", "", 1), "studio")
        self.assertEqual(detect_type("شقة غرفة وصالة فاخرة", "", 1), "one_bedroom")
        self.assertEqual(detect_type("شقة غرفتين وصالة", "", 2), "two_bedroom")

    def test_base_neighborhood_name(self):
        self.assertEqual(base_neighborhood_name("النرجس 3"), "النرجس")
        self.assertEqual(base_neighborhood_name("الملز"), "الملز")

    @patch("app.services.chat_service.get_config", return_value=MOCK_CONFIG)
    def test_criteria_extraction_handles_commas_and_subnumbers(self, _mock_cfg):
        c = _update_criteria("test_phone", "أبغى غرفة وصالة في النرجس 3 بحدود 2,800 ريال")
        self.assertEqual(c["apartment_type"], "one_bedroom")
        self.assertEqual(c["neighborhood"], "النرجس")
        self.assertEqual(c["max_budget"], 2800)
        self.assertEqual(c["min_budget"], 0)

    def test_prepare_customer_reply_formats_whatsapp_and_injects_link(self):
        raw = "🏠 **الاسم**: شقة النرجس 3\nشوف [الرابط](https://mashimarketing.com/p/1)"
        prop = {
            "title": "شقة النرجس 3",
            "building_name": "النرجس 3",
            "canonical_url": "https://mashimarketing.com/property/narjis-3",
        }
        cleaned = _prepare_customer_reply(raw, prop)
        self.assertNotIn("**", cleaned)
        self.assertIn("*الاسم*", cleaned)
        self.assertNotIn("🏠", _strip_emojis(cleaned))
        self.assertIn("https://mashimarketing.com/property/narjis-3", cleaned)

    @patch("app.services.prompts.get_config", return_value=MOCK_CONFIG)
    def test_get_session_removes_stale_internal_state_messages(self, _mock_cfg):
        msgs = get_session("test_phone")
        msgs.append({"role": "system", "content": "INTERNAL CONFIRMED SEARCH STATE: old"})
        msgs.append({"role": "user", "content": "مرحبا"})
        updated = get_session("test_phone")
        internal_msgs = [
            m for m in updated
            if m.get("role") == "system" and "INTERNAL CONFIRMED SEARCH STATE" in m.get("content", "")
        ]
        self.assertEqual(len(internal_msgs), 0)

    def test_chat_request_validation(self):
        req = ChatRequest(phone="  +966500000000  ", message="  السلام عليكم ")
        self.assertEqual(req.phone, "+966500000000")
        self.assertEqual(req.message, "السلام عليكم")
        with self.assertRaises(ValueError):
            ChatRequest(phone="   ", message="مرحبا")

    def test_welcome_message_content(self):
        self.assertIn("🌟 حياكم الله في شقردي! 🌟", WELCOME_MESSAGE)
        self.assertIn("https://www.shgarde.com", WELCOME_MESSAGE)
        self.assertIn("https://shgarde.com/category/mesheal", WELCOME_MESSAGE)
        self.assertIn("66907790", WELCOME_MESSAGE)
        self.assertIn("https://wa.me/96566907790", WELCOME_MESSAGE)
        self.assertIn("شقردي.. تسوّق أكثر، واستمتع أكثر!", WELCOME_MESSAGE)

    def test_is_greeting(self):
        self.assertTrue(is_greeting("مرحبا"))
        self.assertTrue(is_greeting("السلام عليكم"))
        self.assertTrue(is_greeting("السلام عليكم ورحمة الله وبركاته"))
        self.assertTrue(is_greeting("هلا والله"))
        self.assertTrue(is_greeting("صباح الخير"))
        self.assertTrue(is_greeting("مساء الفل"))
        self.assertTrue(is_greeting("hello"))
        self.assertTrue(is_greeting("hi"))
        self.assertTrue(is_greeting("/start"))
        self.assertTrue(is_greeting("أود الاستفسار عن منتجات متجر شقردي"))
        self.assertTrue(is_greeting(""))
        self.assertFalse(is_greeting("السلام عليكم ابي شاحن"))
        self.assertFalse(is_greeting("كم سعر ايفون 15"))
        self.assertFalse(is_greeting("شكرا جزيلا"))

    def test_prepare_customer_reply_preserves_welcome_message(self):
        cleaned = _prepare_customer_reply(WELCOME_MESSAGE)
        self.assertEqual(cleaned, WELCOME_MESSAGE)
        self.assertIn("🌟", cleaned)
        self.assertIn("❤️", cleaned)

    @patch("app.services.chat_service.log_chat_turn")
    def test_process_message_returns_welcome_message_on_greeting(self, _mock_log):
        reply, images = process_message("+96566907790", "السلام عليكم")
        self.assertEqual(reply, WELCOME_MESSAGE)
        self.assertEqual(images, [])


if __name__ == "__main__":
    unittest.main()

