<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/brand/robo-lockup-dark.svg">
  <img src="assets/brand/robo-lockup-light.svg" alt="Robo by Ignitee Now" width="420">
</picture>

<h1 dir="rtl">آپ کا AI جو واقعی کام کر کے دیتا ہے۔</h1>

<p dir="rtl">اپنی میز پر روبو کو کام دیں، اور فون سے اس کی پیش رفت دیکھیں۔<br>
یہ آپ کے اپنے کمپیوٹر پر چلتا ہے، اصل ٹولز استعمال کرتا ہے، اور کسی بھی خطرناک قدم سے پہلے آپ سے پوچھتا ہے۔</p>

![Windows · macOS · Linux](https://img.shields.io/badge/Windows%20%C2%B7%20macOS%20%C2%B7%20Linux-0E1437?style=for-the-badge)
![Terminal · Desktop · Browser · Voice · API](https://img.shields.io/badge/Terminal%20%C2%B7%20Desktop%20%C2%B7%20Browser%20%C2%B7%20Voice%20%C2%B7%20API-3F3E98?style=for-the-badge)

[English](README.md) · [Español](README.es.md) · [中文](README.zh-CN.md) · **اردو**

</div>

---

<div dir="rtl">

## اسے کوئی بھی کام دیں

| روزمرہ | تکنیکی |
|---|---|
| "میرے Downloads فولڈر کو فائل کی قسم کے حساب سے ترتیب دو۔" | "ہماری build فیل ہو رہی ہے۔ وجہ ڈھونڈو اور ٹھیک کرو۔" |
| "ان میٹنگ نوٹس کو ذمہ داروں اور تاریخوں کے ساتھ کاموں کی فہرست بنا دو۔" | "اس 2 GB سرور لاگ کو دیکھو اور بتاؤ کل رات کیا خراب ہوا۔" |
| "ہر صبح 8 بجے مجھے Telegram پر ٹیک کی خبریں بھیجو۔" | "یہ .exe کھولو اور بتاؤ یہ کن سرورز سے بات کرتی ہے۔" |
| "ان دو اسپریڈشیٹس کا موازنہ کرو اور بتاؤ نئی میں کون غائب ہے۔" | "X کے تین بہترین آپشنز پر تحقیق کرو، موازنہ کرو اور ذرائع دو۔" |

روبو کام کی منصوبہ بندی کرتا ہے، اسے اصل ٹولز (ٹرمینل، فائلیں، براؤزر، کوڈ) سے مکمل کرتا ہے، اپنا کام خود چیک کرتا ہے،
اور کسی بھی خطرناک قدم سے پہلے پوچھتا ہے: **Allow once / Allow for this session / Deny**۔
یہ آپ کے منتخب کردہ ماڈل کے ساتھ کام کرتا ہے: OpenAI، Anthropic، Gemini، DeepSeek، Kimi، OpenRouter،
یا Ollama یا کسی بھی OpenAI-compatible سرور کے ذریعے مقامی (local) ماڈل۔

## انسٹال کریں

**Windows (PowerShell)**

</div>

```powershell
git clone https://github.com/igniteenow/robo
cd robo
Set-ExecutionPolicy -Scope Process Bypass
.\install-robo.ps1
```

<div dir="rtl">

**macOS · Linux · WSL**

</div>

```bash
git clone https://github.com/igniteenow/robo
cd robo
bash install-robo.sh
```

<div dir="rtl">

پھر **نیا ٹرمینل کھولیں** (انسٹالر `robo` کو آپ کے PATH میں شامل کرتا ہے) اور اپنا ماڈل منتخب کریں:

</div>

```bash
robo model        # choose a provider and paste its API key
robo              # start chatting
```

<div dir="rtl">

صرف `git` پہلے سے ہونا ضروری ہے۔ انسٹالر Python اور Node خود سیٹ اپ کرتا ہے اور آپ کی کنفیگریشن، میموری یا اسکلز کو کبھی اوور رائٹ نہیں کرتا۔
Debian/Ubuntu پر آواز کے لیے یہ بھی چاہیے: `sudo apt install libportaudio2`۔
اگر کچھ ٹھیک نہ لگے تو `robo doctor` چلائیں۔

## چلائیں

روبو کو چلانے کے تمام طریقے ایک ہی سیشنز، میموری اور سیٹنگز استعمال کرتے ہیں۔

| آپ کو چاہیے | چلائیں | آپ کو ملے گا |
|---|---|---|
| **ٹرمینل** | `robo` | آواز کے ساتھ فل اسکرین ٹرمینل ایپ (کلاسک پرامپٹ کے لیے `robo --cli`) |
| **ڈیسک ٹاپ ایپ** | `robo desktop` | Windows، macOS، Linux کے لیے ایپ۔ پہلی بار build ہوتی ہے، پھر فوراً کھلتی ہے |
| **براؤزر** | `robo dashboard` | `http://localhost:9119` پر روبو: چیٹ، سیٹنگز، سیشنز، اسکلز، MCP |
| **ایک فوری جواب** | `robo chat -q "Summarize README.md"` | ایک سوال، ایک جواب، بغیر UI |
| **آپ کی اپنی ایپس** | `robo gateway` | `http://localhost:8642/v1` پر OpenAI-compatible API |

### آواز

ٹرمینل اور ڈیسک ٹاپ ایپ دونوں میں روبو سے بات کریں۔ آواز سے ٹیکسٹ آپ کے اپنے کمپیوٹر پر بنتا ہے۔

| کمانڈ | کیا کرتی ہے |
|---|---|
| `/voice on` | ہینڈز فری وائس چیٹ۔ جواب سنائی بھی دیتے ہیں اور اسکرین پر مکمل لنکس اور تفصیل کے ساتھ نظر بھی آتے ہیں |
| `/wake on` | کی بورڈ چھوئے بغیر بات شروع کرنے کے لیے **"Hey Roh Boh"** کہیں |

### ڈیسک ٹاپ ایپ

- **MCP سرورز: Settings → MCP۔** فائلیں ایڈٹ کیے بغیر Model Context Protocol سرورز شامل کریں، تلاش کریں اور بدلیں۔
- **خود اپڈیٹ ہوتی ہے۔** نیا ورژن آنے پر **Update now** دبائیں۔ روبو بند ہو کر پیش رفت دکھاتا ہے اور مکمل ہونے پر خود دوبارہ کھل جاتا ہے۔
- **کسی دوسری مشین پر چلنے والے روبو سے جڑیں:** Settings → Gateway → Remote gateway۔

## کہیں سے بھی استعمال کریں

روبو کو اپنے PC یا سرور پر چلائیں، پھر کسی بھی براؤزر (فون، ٹیبلٹ یا لیپ ٹاپ) سے **وہی روبو ٹرمینل** استعمال کریں۔

</div>

```bash
robo dashboard --host 0.0.0.0 --no-open
```

<div dir="rtl">

پہلی بار روبو آپ سے **یوزر نیم اور پاس ورڈ** بنانے کو کہے گا۔ لاگ اِن کے بغیر یہ کبھی نیٹ ورک ایڈریس پر نہیں چلتا۔
پھر اپنے دوسرے ڈیوائس پر `http://<this-computer's-IP>:9119` کھولیں۔

- **Windows:** ایک بار پورٹ کی اجازت دیں، PowerShell میں *Administrator کے طور پر*:
  `New-NetFirewallRule -DisplayName "Robo 9119" -Direction Inbound -Protocol TCP -LocalPort 9119 -Action Allow -Profile Private`
- **گھر کے نیٹ ورک سے باہر:** Tailscale جیسا VPN استعمال کریں۔ اپنے راؤٹر پر پورٹ فارورڈ نہ کریں۔
- **بند کرنے کے لیے:** `robo dashboard --stop`

آپ روبو کو **Telegram، WhatsApp، Discord، Slack** وغیرہ سے بھی پیغام بھیج سکتے ہیں: `robo gateway setup` چلائیں۔

## یہ کیا کر سکتا ہے

- **آپ کے دستاویزات سے کام کرتا ہے۔** کسی بھی سائز کی لاگز، نوٹس، کوڈ، CSV، JSON، HTML یا PowerPoint فائلیں لگائیں (`/attach <file>`)۔ روبو انہیں آپ کے کمپیوٹر پر انڈیکس کرتا ہے اور اصل عبارت کے ساتھ جواب دیتا ہے۔
- **اصل کام کرتا ہے۔** کوڈنگ، ڈیبگنگ، تحقیق، لکھائی، ڈیٹا کا کام، فائلوں کی صفائی اور سسٹم ایڈمن — اصل ٹرمینل، فائل ایڈیٹنگ، اصل براؤزر اور کوڈ چلانے کے ساتھ۔
- **سافٹ ویئر کے اندر محفوظ طریقے سے دیکھتا ہے۔** Ghidra، radare2 یا rizin انسٹال ہوں تو ان سے، ورنہ بلٹ اِن پارسر سے اسٹیٹک تجزیہ۔ فائل کبھی چلائی نہیں جاتی۔
- **استعمال کے ساتھ بہتر ہوتا ہے۔** جو طریقہ کام کرے اسے دوبارہ استعمال کے قابل اسکل بنا لیتا ہے، طویل مدتی میموری رکھتا ہے، پرانی گفتگو تلاش کرتا ہے، اور سیکھتا ہے کہ آپ کام کیسے پسند کرتے ہیں۔
- **آپ کی غیر موجودگی میں کام کرتا ہے۔** شیڈول کیے گئے کام ("ہر صبح 8 بجے…") اور ایک ساتھ چلنے والے سب ایجنٹس۔
- **آپ کی مشین صاف رکھتا ہے۔** بھاری یا خطرناک کام Docker، SSH یا کلاؤڈ سینڈ باکس (Modal، Daytona) میں چل سکتے ہیں۔

## روزمرہ کی کمانڈز

| کمانڈ | کیا کرتی ہے |
|---|---|
| `robo model` | ماڈل یا پرووائیڈر بدلیں |
| `robo update` | روبو اپڈیٹ کریں (یا ڈیسک ٹاپ ایپ میں **Update now**) |
| `robo doctor` | اپنا سیٹ اپ چیک کریں |
| `/help` | چیٹ کے اندر تمام کمانڈز |
| `/edit` | اپنا آخری پیغام واپس لے کر دوبارہ لکھیں |

جب روبو کام کر رہا ہو تو بس لکھیں: آپ کا پیغام جاری کام کا رخ بدل دیتا ہے۔

## اسے اپنا بنائیں

سب کچھ `~/.robo` (Windows: `%USERPROFILE%\.robo`) میں سادہ فائلوں کی صورت میں ہے، جنہیں ایڈٹ، بیک اپ یا منتقل کرنا آسان ہے:

| فائل | اس میں کیا ہے |
|---|---|
| `SOUL.md` | روبو کی شخصیت اور اصول: لہجہ، احتیاط کی سطح، انداز |
| `memories/USER.md` | آپ کے بارے میں معلومات، تاکہ آپ کو بار بار نہ بتانا پڑے |
| `memories/MEMORY.md` | جو روبو نے سیکھا۔ خود اپڈیٹ ہوتی ہے؛ آپ "یاد رکھو کہ…" بھی کہہ سکتے ہیں |
| `skills/` | دوبارہ استعمال ہونے والے طریقے۔ کہیں "اسے اسکل کے طور پر محفوظ کرو" |
| `.env` | آپ کی API keys |

HTTP API اور Docker کی تفصیل کے لیے [انگریزی README](README.md#http-api) دیکھیں۔

## ابتدائی رسائی (Early access)

روبو 3.0.1 ابتدائی رسائی میں ہے۔ اسے آزمائیں اور ہمیں اپنی رائے دیں:
[issue کھولیں](https://github.com/igniteenow/robo/issues) یا
[support@igniteenow.com](mailto:support@igniteenow.com) پر ای میل کریں۔ آواز اور GPU کا کام آپ کے ہارڈ ویئر پر منحصر ہے؛
`robo doctor` بتاتا ہے کہ کیا دستیاب ہے۔

## لائسنس

[MIT](LICENSE) · [Ignitee Now](https://igniteenow.com) کی تیار کردہ۔

<sub>Nous Research کے MIT لائسنس یافتہ [Hermes Agent](https://github.com/NousResearch/hermes-agent) پر مبنی۔ دیکھیں [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)۔</sub>

</div>
