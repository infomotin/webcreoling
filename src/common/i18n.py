"""
Bilingual Internationalization (i18n) System for WebCreoling / The Daily AI Alo.
Provides comprehensive English and Bangla translations for UI elements, navigation,
forms, badges, buttons, tables, alerts, and transactional messages.
"""

from typing import Any, Dict, Optional
from flask import session, request, g

# Comprehensive Translation Dictionary
TRANSLATIONS: Dict[str, Dict[str, str]] = {
    # Brand and Meta
    "site_title": {"bn": "দি ডেইলি এআই আলো", "en": "The Daily AI Alo"},
    "tagline": {"bn": "স্বতন্ত্র এআই চালিত বাংলা সংবাদ ও নিউজরুম সিএমএস", "en": "Autonomous AI-Driven Bengali News & Newsroom CMS"},
    "edition": {"bn": "বাংলাদেশ ও গ্লোবাল সংস্করণ", "en": "Bangladesh & Global Edition"},
    
    # Navigation & Sidebar
    "nav_dashboard": {"bn": "মিশন কন্ট্রোল ৩৬০°", "en": "Mission Control 360°"},
    "nav_portal": {"bn": "লাইভ পোর্টাল", "en": "Live Portal"},
    "nav_articles": {"bn": "সংবাদ অনুসন্ধান (FTS5)", "en": "Articles Explorer (FTS5)"},
    "nav_newsroom": {"bn": "সম্পাদকীয় নিউজরুম হাব", "en": "Editorial Newsroom Hub"},
    "nav_reporter_desk": {"bn": "রিপোর্টার ফিল্ড ডেস্ক", "en": "Reporter Field Desk"},
    "nav_subscriber_portal": {"bn": "সাবস্ক্রাইবার পোর্টাল", "en": "Subscriber Portal"},
    "nav_aggregator": {"bn": "মাল্টি-সোর্স কালেক্টর", "en": "Multi-Source Aggregator"},
    "nav_lora_hub": {"bn": "LoRA ট্রেইনিং স্টুডিও", "en": "LoRA Training Studio"},
    "nav_ai_pilot": {"bn": "এআই পাইলট ও ব্রেন রুলস", "en": "AI Pilot & Brain Rules"},
    "nav_chat_rag": {"bn": "নিউরাল চ্যাটবট (RAG)", "en": "Neural Chatbot (RAG)"},
    "nav_datacenter": {"bn": "মাল্টি-ক্লাউড ডাটা সেন্টার", "en": "Multi-Cloud Datacenter"},
    "nav_security": {"bn": "SOC WAF ও ব্লকচেইন", "en": "SOC WAF & Blockchain"},
    "nav_communications": {"bn": "মেইল ও এসএমএস গেটওয়ে", "en": "Mail & SMS Gateways"},
    "nav_payments": {"bn": "বিলিং ও পেমেন্ট গেটওয়ে", "en": "Billing & Payments"},
    "nav_users": {"bn": "ব্যবহারকারী ব্যবস্থাপনা", "en": "User Management"},
    "nav_logout": {"bn": "লগআউট", "en": "Logout"},
    "nav_login": {"bn": "লগইন", "en": "Login"},
    
    # Newspaper Management Tabs
    "tab_portal_feed": {"bn": "লাইভ পোর্টাল ও ড্রাফট", "en": "Live Portal & Drafts"},
    "tab_editor_desk": {"bn": "সম্পাদকীয় ডেস্ক", "en": "Editorial Desk"},
    "tab_ai_pilot": {"bn": "এআই পাইলট ডিসিশন", "en": "AI Pilot Decisions"},
    "tab_scheduled": {"bn": "নির্ধারিত রিলিজ", "en": "Scheduled Releases"},
    "tab_polls": {"bn": "জনমত জরিপ ও পাঠক", "en": "Polls & Subscribers"},
    "tab_settings": {"bn": "পোর্টাল সেটিংস", "en": "Portal Settings"},
    "tab_ads": {"bn": "বিজ্ঞাপন ও স্পন্সর", "en": "Ads & Branding"},
    "tab_security": {"bn": "সিকিউরিটি ও ভল্ট", "en": "Security & Vault"},
    "tab_blockchain": {"bn": "ব্লকচেইন লেজার", "en": "Blockchain Ledger"},
    "tab_heavy_data": {"bn": "হেভি ডাটা ও ব্যাকআপ", "en": "Heavy Data & Backups"},
    "tab_communications": {"bn": "মেইল ও এসএমএস হাব", "en": "Mail & SMS Hub"},
    "tab_payments": {"bn": "পেমেন্ট গেটওয়ে", "en": "Payment Gateways"},
    
    # KPI Metrics
    "kpi_total_articles": {"bn": "মোট সংরক্ষিত সংবাদ", "en": "Total Saved News"},
    "kpi_published": {"bn": "সরাসরি প্রকাশিত", "en": "Live Published"},
    "kpi_pending": {"bn": "অনুমোদন অপেক্ষমাণ", "en": "Pending Approval"},
    "kpi_scheduled": {"bn": "নির্ধারিত রিলিজ", "en": "Scheduled Release"},
    "kpi_archived": {"bn": "সংরক্ষিত আর্কাইভ", "en": "Archived Records"},
    "kpi_my_articles": {"bn": "আমার প্রকাশিত সংবাদ", "en": "My Published Articles"},
    "kpi_my_pending": {"bn": "আমার পেন্ডিং ড্রাফট", "en": "My Pending Drafts"},
    "kpi_total_views": {"bn": "মোট ভিউয়ার্স সংখ্যা", "en": "Total Readership Views"},
    
    # Actions & Buttons
    "btn_save": {"bn": "সংরক্ষণ করুন", "en": "Save Changes"},
    "btn_submit": {"bn": "জমা দিন", "en": "Submit"},
    "btn_publish": {"bn": "প্রকাশ করুন", "en": "Publish Live"},
    "btn_draft": {"bn": "খসড়া রাখুন", "en": "Save Draft"},
    "btn_edit": {"bn": "সম্পাদনা", "en": "Edit"},
    "btn_delete": {"bn": "মুছে ফেলুন", "en": "Delete"},
    "btn_filter": {"bn": "ফিল্টার", "en": "Filter"},
    "btn_search": {"bn": "অনুসন্ধান", "en": "Search"},
    "btn_reset": {"bn": "রিসেট", "en": "Reset"},
    "btn_decrypt": {"bn": "ডিক্রিপ্ট ও রিস্টোর", "en": "Decrypt & Restore"},
    "btn_force_restore": {"bn": "আনলক ও সমস্ত সংবাদ রিস্টোর", "en": "Force Restore & Unlock All"},
    "btn_send_test_mail": {"bn": "টেস্ট মেইল পাঠান (Mailtrap)", "en": "Send Test Mail (Mailtrap)"},
    "btn_send_test_sms": {"bn": "টেস্ট এসএমএস পাঠান", "en": "Send Test SMS"},
    "btn_subscribe": {"bn": "সাবস্ক্রাইব করুন", "en": "Subscribe Now"},
    "btn_pay_now": {"bn": "পেমেন্ট সম্পন্ন করুন", "en": "Complete Payment"},
    "btn_verify_otp": {"bn": "ওটিপি ভেরিফাই করুন", "en": "Verify OTP Code"},
    
    # Categories
    "cat_all": {"bn": "সকল বিভাগ", "en": "All Categories"},
    "cat_politics": {"bn": "রাজনীতি", "en": "Politics"},
    "cat_bangladesh": {"bn": "বাংলাদেশ", "en": "Bangladesh"},
    "cat_international": {"bn": "আন্তর্জাতিক", "en": "International"},
    "cat_business": {"bn": "অর্থনীতি ও বাণিজ্য", "en": "Business & Economy"},
    "cat_sports": {"bn": "খেলাধুলা", "en": "Sports"},
    "cat_technology": {"bn": "বিজ্ঞান ও প্রযুক্তি", "en": "Science & Technology"},
    "cat_entertainment": {"bn": "বিনোদন", "en": "Entertainment"},
    "cat_opinion": {"bn": "মতামত ও সম্পাদকীয়", "en": "Opinion & Editorial"},
    "cat_lifestyle": {"bn": "জীবনযাপন", "en": "Lifestyle"},

    # Roles
    "role_admin": {"bn": "প্রধান প্রশাসক (Super Admin)", "en": "Super Administrator"},
    "role_editor": {"bn": "নিউজ এডিটর (News Editor)", "en": "News Editor"},
    "role_reporter": {"bn": "মাঠ প্রতিবেদক (Reporter)", "en": "Field Reporter"},
    "role_subscriber": {"bn": "পাঠক / সাবস্ক্রাইবার (Subscriber)", "en": "Subscriber Reader"},
    "role_analyst": {"bn": "ডাটা অ্যানালিস্ট (Data Analyst)", "en": "Data Analyst"},

    # Security & Vault
    "vault_title": {"bn": "🚨 এআই ব্রেন সিকিউরিটি ভল্ট ও ইমার্জেন্সি কনসোল", "en": "🚨 AI Brain Security Vault & Emergency Console"},
    "vault_manual_mode": {"bn": "ম্যানুয়াল মোড (নিরাপদ)", "en": "Manual Mode (Safe)"},
    "vault_auto_mode": {"bn": "স্বয়ংক্রিয় ডিফেন্স", "en": "Autonomous Defense"},
    "vault_status_normal": {"bn": "স্বাভাবিক: পোর্টাল ডাটাবেস সম্পূর্ণ নিরাপদ", "en": "Normal: Database Fully Secure & Plaintext"},
    "vault_status_locked": {"bn": "জরুরি লকডাউন ও এনক্রিপশনে রয়েছে", "en": "Emergency Lockdown & Encrypted"},
    "vault_threat_score": {"bn": "সার্ভার থ্রেট লেভেল স্কোর", "en": "Server Threat Level Score"},

    # Payments & Billing
    "pay_bkash": {"bn": "বিকাশ পেমেন্ট", "en": "bKash Checkout"},
    "pay_nagad": {"bn": "নগদ পেমেন্ট", "en": "Nagad Direct"},
    "pay_rocket": {"bn": "রকেট পেমেন্ট", "en": "Rocket DBBL"},
    "pay_card": {"bn": "ভিসা / মাস্টারকার্ড", "en": "Credit / Debit Card"},
    "pay_ssl": {"bn": "SSLCommerz গেটওয়ে", "en": "SSLCommerz Gateway"},
    "pay_invoice": {"bn": "ডিজিটাল ইনভয়েস", "en": "Digital Tax Invoice"},
    "pay_amount": {"bn": "টাকার পরিমাণ", "en": "Amount (BDT)"},
    "pay_status_valid": {"bn": "পরিশোধিত (PAID)", "en": "Payment Verified (PAID)"},
    "pay_status_pending": {"bn": "অপেক্ষমাণ (PENDING)", "en": "Pending Confirmation"},
    "pay_status_failed": {"bn": "ব্যর্থ (FAILED)", "en": "Payment Failed"},
    
    # Mail & SMS
    "mail_server_title": {"bn": "মেইল সার্ভার কনফিগারেশন (Mailtrap Sandbox)", "en": "Mail Server Configuration (Mailtrap Sandbox)"},
    "sms_gateway_title": {"bn": "এসএমএস গেটওয়ে হাব", "en": "SMS Gateway Hub"},
    "otp_system_title": {"bn": "ওটিপি (OTP) ও টু-ফ্যাক্টর অথেনটিকেশন (2FA)", "en": "OTP & Two-Factor Authentication (2FA)"},
    "otp_placeholder": {"bn": "৬-সংখ্যার কোড দিন", "en": "Enter 6-digit OTP code"},
}

# Dynamic Fallback Vocabulary for Direct String Lookups
PHRASE_DICTIONARY: Dict[str, str] = {
    # Headings & Subheadings
    "সম্পাদকীয় নিউজরুম ড্যাশবোর্ড": "Editorial Newsroom Dashboard",
    "প্রথম আলো ডিজিটাল CMS": "The Daily AI Alo Digital CMS",
    "পোর্টাল কনফিগারেশন, লোগো ও লাইভ তথ্য": "Portal Configuration, Logo & Live Info",
    "১. পোর্টাল ব্র্যান্ড আইডেন্টিটি": "1. Portal Brand Identity",
    "পোর্টালের নাম / ব্র্যান্ড শিরোনাম *": "Portal Name / Brand Title *",
    "সংস্করণ ট্যাগ (Edition)": "Edition Tag",
    "ট্যাগলাইন / স্লোগান": "Tagline / Slogan",
    "লোগো টেক্সট (Fallback Text)": "Logo Text (Fallback Text)",
    "কাস্টম লোগো ছবির URL (ঐচ্ছিক)": "Custom Logo Image URL (Optional)",
    "সার্ভার থ্রেট লেভেল": "Server Threat Level",
    "প্রতিহত সাইবার আক্রমণ": "Deflected Cyber Attacks",
    "ব্লকলিস্টেড IP ও কান্ট্রি": "Blacklisted IPs & Countries",
    "ব্লকচেইন লেজার স্ট্যাটাস": "Blockchain Ledger Status",
    "প্রথম আলো ক্রিপ্টোগ্রাফিক আর্টিকেল লেজার": "Cryptographic Article Ledger",
    "ইমার্জেন্সি কিল-সুইচ ও রিকভারি কনসোল": "Emergency Kill-Switch & Recovery Console",
    "মাস্টার কোড দিয়ে ডিক্রিপ্ট ও রিস্টোর": "Decrypt & Restore with Master Code",
    "জরুরি এনক্রিপশন ও লকডাউন সক্রিয় করুন (Kill-Switch)": "Activate Emergency Encryption & Lockdown (Kill-Switch)",
    "লাইভ এআই সাইবার থ্রেট রিস্ক গেজ": "Live AI Cyber Threat Risk Gauge",
    "ম্যানুয়াল মোড": "Manual Mode",
    "ম্যানুয়াল মোড (নিরাপদ)": "Manual Mode (Safe)",
    "হ্যাক বা সাইবার ঝুঁকি সনাক্তে স্বয়ংক্রিয় সেলফ-এনক্রিপশন ও লকডাউন সক্রিয় রাখুন": "Keep Autonomous Self-Encryption on Threat Breach Active",
    "লকডাউন থ্রেশহোল্ড স্কোর (২০-১০০)": "Lockdown Threshold Score (20-100)",
    "মাস্টার কোড প্রেরণের সিকিউরিটি ইমেইল": "Security Email for Master Code",
    "পলিসি সংরক্ষণ": "Save Policy",
    "সিমুলেটেড টেস্ট রান": "Simulated Attack Test Run",
    "অবিন্যস্ত ব্লক মিন্ট": "Mint Pending Blocks",
    "সম্পূর্ণ চেইন অডিট": "Full Chain Audit",
    "ব্লক #": "Block #",
    "আর্টিকেল আইডি": "Article ID",
    "ব্লক হ্যাশ": "Block Hash",
    "মারকেল রুট": "Merkle Root",
    "পূর্ববর্তী ব্লক হ্যাশ": "Previous Block Hash",
    "ডিজিটাল স্বাক্ষর": "Digital Signature",
    "স্ট্যাটাস": "Status",
    "অ্যাকশন": "Action",
    "তারিখ ও সময়": "Date & Time",
    "শিরোনাম": "Title",
    "বিভাগ": "Category",
    "লেখক / সোর্স": "Author / Source",
    "অবস্থা": "Status",
    "ভিউ": "Views",
    "শেয়ার": "Shares",
    "নতুন সংবাদ প্রকাশ করুন": "Publish New Article",
    "সংবাদের শিরোনাম *": "Article Title *",
    "সংবাদের বিভাগ *": "News Category *",
    "লেখক বা রিপোর্টারের নাম": "Author or Reporter Name",
    "সংক্ষিপ্ত সারসংক্ষেপ": "Short Summary",
    "সংবাদের বিস্তারিত বিবরণ *": "Full Article Body *",
    "ফিচার্ড ইমেজ লিঙ্ক": "Featured Image URL",
    "মূল সংবাদের লিঙ্ক (Source URL)": "Original Source URL",
    "সংবাদের অবস্থান (Placement)": "Position Placement",
    "স্ট্যান্ডার্ড নিউজ": "Standard News",
    "প্রধান সংবাদ (Lead)": "Lead Story (Lead)",
    "বিশেষ সংবাদ (Featured)": "Featured Story",
    "ব্রেকিং নিউজ (Ticker)": "Breaking News (Ticker)",
    "তাত্ক্ষণিক প্রকাশ (Published)": "Publish Immediately",
    "খসড়া হিসেবে সংরক্ষণ (Draft)": "Save as Draft",
    "ভবিষ্যতে প্রকাশের সময় (Scheduled)": "Schedule Release Time",
}


def get_current_language() -> str:
    """Retrieve active language from session, query args, or default."""
    try:
        if hasattr(g, "lang") and g.lang:
            return g.lang
        lang = session.get("lang")
        if not lang and request:
            lang = request.args.get("lang")
        return lang if lang in ("bn", "en") else "bn"
    except Exception:
        return "bn"


def t(key: str, default: Optional[str] = None, lang: Optional[str] = None, **kwargs) -> str:
    """
    Look up translation key. If key exists in dictionary, return translated string.
    If not, check phrase dictionary or return default/key with string formatting.
    """
    active_lang = lang or get_current_language()
    
    # 1. Exact Key in TRANSLATIONS
    if key in TRANSLATIONS:
        text = TRANSLATIONS[key].get(active_lang, TRANSLATIONS[key].get("bn", key))
        return text.format(**kwargs) if kwargs else text
    
    # 2. Key match in Phrase Dictionary
    if active_lang == "en" and key in PHRASE_DICTIONARY:
        text = PHRASE_DICTIONARY[key]
        return text.format(**kwargs) if kwargs else text
    
    # 3. If default provided
    if default is not None:
        return default.format(**kwargs) if kwargs else default

    return key.format(**kwargs) if kwargs else key


def tr(bn_text: str, en_text: Optional[str] = None) -> str:
    """Convenient inline bilingual helper."""
    active_lang = get_current_language()
    if active_lang == "en":
        if en_text is not None:
            return en_text
        if bn_text in PHRASE_DICTIONARY:
            return PHRASE_DICTIONARY[bn_text]
        return bn_text
    return bn_text
