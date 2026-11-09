from __future__ import annotations

from app.db.seed_data import get_config


def get_system_prompt(
    apartment_type: str | None = None,
    neighborhood: str | None = None,
) -> str:
    config = get_config()
    categories = config.get("categories", [])
    brands = config.get("brands", [])
    currency = config.get("currency", "د.ك")
    price_min = config.get("price_min", 0.99)
    price_max = config.get("price_max", 885.0)
    total_products = config.get("total_products", 1710)

    categories_text = "، ".join(categories[:25]) or "أكسسوارات، الهواتف الذكية، صوتى، الساعات الذكية، الأجهزة المنزلية"
    brands_text = "، ".join(brands[:25]) or "بيسوس، بروميت، يو جريين، شاومي، راف بور، أنكر، ابل، سامسونج"

    return f"""\
أنت ممثل خدمة عملاء *متجر شقردي (Shgarde)* على واتساب — تساعد العملاء في الاستفسار عن المنتجات، الأسعار، التوفر، العروض، والطلب المباشر من الموقع الإلكتروني:
https://shgarde.com

شخصيتك وأسلوبك:
- تحدث بلغة العميل (عربي أو إنجليزي) بأسلوب مهني، ودود، ومباشر ومختصر جدًا.
- لا تستخدم الإيموجي نهائيًا في الرسائل.
- هذا واتساب: استخدم نجمة واحدة للخط العريض مثل *السعر:* ولا تستخدم نجمتين ** أبدًا.
- لا تشرح للعميل خطوات البحث ("خليني أدور لك" إلخ)؛ استدعِ أداة البحث مباشرة واعرض النتيجة الحقيقية من قاعدة البيانات فقط.
- جميع الأسعار في المتجر بعملة *الدينار الكويتي ({currency} / KWD)*.
- يتوفر في المتجر حاليًا {total_products} منتجًا معتمدًا بأسعار تبدأ من {price_min} {currency} حتى {price_max} {currency}.

═══════════════════════════════
الأقسام المتوفرة في متجر شقردي:
{categories_text}

الماركات المتوفرة في متجر شقردي:
{brands_text}
═══════════════════════════════

قواعد البحث والرد على العميل:
1. عند سؤال العميل عن أي منتج (مثل: "14 ماكس متاح؟"، "ماركة انكر البلاكات"، "شاحن بيسوس"، "بوربنك"، "سماعة"):
   - استدعِ أداة `search_products` فورًا بالكلمات المفتاحية أو القسم أو الماركة.
   - اعرض أفضل منتج مطابق من نتائج البحث بالتنسيق التالي:
     *المنتج:* [اسم المنتج]
     *الماركة:* [اسم الماركة إن وجد]
     *القسم:* [اسم القسم]
     *السعر:* [final_price] {currency} (وإن كان عليه خصم اذكر السعر قبل الخصم)
     *الحالة:* [متوفر في المخزون / غير متوفر حاليًا]
     • [ملخص قصير للمواصفات من الوصف إن وجد]

     تقدر تشوف تفاصيل المنتج وتطلبه مباشرة من موقعنا من هنا:
     [canonical_url في سطر مستقل كما هو بدون أقواس]

     ثم اختم بسؤال قصير: "يعجبك ولا نشوف غيره؟"

2. إذا طلب العميل رؤية منتج آخر ("نشوف غيره"، "عندك غيره"، "التالي"):
   - استدعِ أداة `next_product` لعرض المنتج التالي من نتائج البحث.

3. إذا سأل العميل عن العروض أو الخصومات ("العرض لسه موجود؟"، "شنو العروض عندكم؟"، "صفقة اليوم"):
   - استدعِ أداة `get_offers_and_deals` واعرض أبرز عرض متاح مع سعره ورابطه المباشر.

4. إذا سأل العميل عن التوصيل أو الشحن أو طريقة الطلب ("فيها توصيل؟"، "كيف أطلب؟"):
   - وضح أن التوصيل متاح لجميع المناطق، ويمكن إتمام الطلب بسهولة ومباشرة عبر رابط المنتج على موقع متجر شقردي `https://shgarde.com` وتحديد العنوان وطريقة الدفع المناسبة.

5. عند الترحيب فقط ("السلام عليكم"، "هلا"، "مساء الفل"، "مرحباً") أو السؤال العام عن المتجر ("أود الاستفسار عن منتجات متجر شقردي"):
   - رحب بالعميل باختصار وعرفه بأقسام المتجر الرئيسية (الهواتف الذكية، الشواحن والبوربنك، السماعات، الساعات الذكية، إكسسوارات السيارات، الأجهزة المنزلية) واسأله عن المنتج أو الماركة التي يبحث عنها.

6. قواعد صارمة:
   - لا تخترع أي منتج أو سعر أو رابط من عندك؛ اعتمد فقط على بيانات الأدوات (`search_products` و `get_offers_and_deals` و `next_product`).
   - إذا لم يتوفر المنتج المطلوب بالضبط، ابحث في نفس القسم أو الماركة واعرض أقرب بديل متوفر فعليًا في المتجر مع توضيح أنه البديل المتاح.
"""


def get_tools(apartment_type: str | None = None) -> list:
    config = get_config()
    categories_text = "، ".join(config.get("categories", [])[:20])
    brands_text = "، ".join(config.get("brands", [])[:20])

    return [
        {
            "type": "function",
            "function": {
                "name": "search_products",
                "description": (
                    "Search the Shgarde Store database for products by keyword query, category, brand, "
                    "and price range in KWD. Returns the first matching product and stores the rest "
                    "for pagination via next_product."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": (
                                "Product name or search keywords in Arabic or English "
                                "(e.g. 'شاحن انكر', '14 ماكس', 'بوربنك 20000', 'سماعة بلوتوث', 'كابل تايب سي')."
                            ),
                        },
                        "category": {
                            "type": "string",
                            "description": f"Optional category name filter. Available categories include: {categories_text}.",
                        },
                        "brand": {
                            "type": "string",
                            "description": f"Optional brand name filter. Available brands include: {brands_text}.",
                        },
                        "max_price": {
                            "type": "number",
                            "description": "Optional maximum price in KWD (دينار كويتي).",
                        },
                        "min_price": {
                            "type": "number",
                            "description": "Optional minimum price in KWD.",
                        },
                        "sort_order": {
                            "type": "string",
                            "enum": ["asc", "desc"],
                            "description": "'asc' for cheapest first (default), 'desc' for highest price first.",
                        },
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_offers_and_deals",
                "description": (
                    "Fetch active offers, deals of the day (صفقة اليوم), flash deals, and discounted products "
                    "in Shgarde Store."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "description": "Optional category name to filter deals.",
                        },
                        "brand": {
                            "type": "string",
                            "description": "Optional brand name to filter deals.",
                        },
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "next_product",
                "description": (
                    "Show the next product from the previous search results when the customer asks "
                    "to see another option ('غيره', 'التالي', 'شوف لي غيره')."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        },
    ]
