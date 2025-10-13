# 🤖 TranslateNovelAI v1.2.0

Ứng dụng dịch truyện tự động với **2 providers**: **OpenRouter API** và **Google AI** (hỗ trợ multiple keys) 

### **Desktop Modern GUI (CustomTkinter)** 
- Giao diện desktop hiện đại với clean sidebar
- **Stop/Continue functionality** với visual feedback
- Dark/Light theme toggle buttons
- Progress bars và speed monitoring real-time
- Custom dialogs và toast notifications


## 🚀 Quick Start

### 🎮 Launcher tổng hợp
```bash
python run_gui.py
```
### 📥 Download ngay (Classic GUI - Không cần cài đặt)
**[⬇️ Tải TranslateNovelAI.exe](https://github.com/nguyenvinhdat642/TranlateNovelAI/releases/download/v1.1.0/TranslateNovelAI.exe)**

### 🔑 Cần có:
- **OpenRouter API Key** (đăng ký tại [openrouter.ai](https://openrouter.ai/)) HOẶC
- **Google AI API Key(s)** (lấy tại [ai.google.dev](https://ai.google.dev/)) - **Hỗ trợ nhiều keys!**
- File truyện định dạng .txt


### ⚡ Performance & Features  
- 🔑 **Dual API Support**: OpenRouter hoặc Google AI (tùy chọn)
- 🚀 **Multiple Google AI Keys**: Hỗ trợ nhiều keys → tăng tốc độ gấp N lần!
- ⚡ **Smart Rate Limiting**: Tự động giới hạn theo RPM của từng key
- 🔄 **Key Rotation**: Round-robin algorithm phân phối đều requests
- 📊 **Real-time monitoring**: Speed tracking với lines/second
- 🎯 **8 bối cảnh dịch**: Hiện đại, cổ đại, fantasy, học đường, công sở, lãng mạn, hành động, tùy chỉnh
- 📝 **Tự động reformat**: Loại bỏ dòng trống thừa sau khi dịch
- 📚 **Convert sang EPUB**: Chuyển đổi từ TXT sang DOCX sang EPUB
- 💾 **Lưu cài đặt**: Tự động lưu API keys và preferences
- 📁 **Smart file management**: Auto-generate tên output, prevent overwrites

## 📋 Yêu cầu

### 🔧 Cơ bản
- Python 3.8 trở lên
- **OpenRouter API Key** (đăng ký tại [OpenRouter](https://openrouter.ai/)) HOẶC
- **Google AI API Key(s)** (lấy tại [Google AI Studio](https://ai.google.dev/))
- Internet connection

### 📦 Dependencies (tự động cài với requirements.txt)
- `requests` - HTTP client cho OpenRouter API
- `google-generativeai` - Google AI Gemini API
- `customtkinter>=5.2.0` - Modern desktop UI framework
- `gradio>=4.0.0` - Web UI framework với CSS custom
- `pillow>=9.0.0` - Xử lý hình ảnh cho icons
- `python-docx` - Xử lý file DOCX
- `pyinstaller` - Build exe files

### 🎨 Tùy chọn
- Pandoc (cho tính năng convert EPUB)
- NSIS (cho tạo installer)

## 📦 Cài đặt

### 1. Clone repository
```bash
git clone https://github.com/nguyenvinhdat642/TranlateNovelAI.git
cd TranslateNovelAI
```

### 2. Cài đặt dependencies
```bash
pip install -r requirements.txt
```

### 3. Lấy API Key (Chọn 1 trong 2)

#### Option 1: OpenRouter API Key
1. Truy cập [openrouter.ai](https://openrouter.ai/) và đăng ký tài khoản
2. Xác minh email để nhận $1 credit miễn phí
3. Vào **Keys** để tạo API key mới
4. Copy API key (dạng: `sk-or-v1-...`)

#### Option 2: Google AI API Key(s) ⭐ Khuyến nghị cho tốc độ cao
1. Truy cập [Google AI Studio](https://ai.google.dev/)
2. Đăng nhập với tài khoản Google
3. Click **"Get API Key"** để tạo key mới
4. Copy API key (dạng: `AIzaSy...`)
5. **💡 Tip**: Tạo nhiều tài khoản Google → nhiều keys → tốc độ tăng gấp N lần!

### 4. Cài đặt Pandoc (nếu muốn dùng tính năng EPUB)
- **Windows**: Tải tại https://pandoc.org/installing.html
- **macOS**: `brew install pandoc` 
- **Linux**: `sudo apt install pandoc`
- Cập nhật đường dẫn Pandoc trong file `src/core/ConvertEpub.py`

### 5. Chạy launcher
```bash
python run_gui.py
```

## 💰 API Providers & Models

### 🆓 Google AI (Miễn phí - Khuyến nghị!) ⭐

#### ✅ Ưu điểm:
- **100% MIỄN PHÍ** (không cần thẻ tín dụng)
- **Hỗ trợ nhiều keys** → Tốc độ tăng gấp N lần
- **Chất lượng cao** (Gemini models)

#### ⚠️ Giới hạn:
- **Free Tier RPM** (Requests Per Minute):
  - Gemini 2.0 Flash: 10 RPM/key
  - Gemini 1.5 Flash: 15 RPM/key
  - Gemini 1.5 Pro: 2 RPM/key (thấp)

#### 💡 Giải pháp: Dùng Multiple Keys!
| Số Keys | Tổng RPM | Tốc độ |
|---------|----------|--------|
| 1 key   | ~10 RPM  | 1x     |
| 3 keys  | ~30 RPM  | 3x     |
| 5 keys  | ~50 RPM  | 5x     |
| 10 keys | ~100 RPM | 10x!   |

### 💳 OpenRouter (Trả phí)

#### 🎆 Models Miễn phí
- `google/gemini-2.0-flash-exp:free` - Gemini 2.0 Flash (miễn phí, có giới hạn)
- `meta-llama/llama-3.2-3b-instruct:free` - Llama 3.2 3B (miễn phí)

#### 💲 Models Trả phí (khuyến nghị)
- `anthropic/claude-3.5-sonnet` - Cân bằng tốt nhất (~$3/1M tokens)
- `anthropic/claude-3-haiku` - Nhanh và rẻ (~$0.25/1M tokens)
- `openai/gpt-4o-mini` - OpenAI rẻ nhất (~$0.15/1M tokens)
- `openai/gpt-4o` - Chất lượng cao (~$5/1M tokens)

### 🔑 Cách lấy API Key miễn phí
**Google AI** (Khuyến nghị):
1. Đăng ký tại [ai.google.dev](https://ai.google.dev/)
2. Tạo API key ngay lập tức
3. 100% miễn phí, không cần thẻ

**OpenRouter**:
1. Đăng ký tại [openrouter.ai](https://openrouter.ai/)
2. Xác minh email
3. Nhận $1 credit miễn phí khi đăng ký
4. Sử dụng models miễn phí hoặc models rẻ

## 🚀 Cách sử dụng

### Phương pháp 1: Download file exe (khuyến nghị - không cần cài đặt)
📥 **[Download TranslateNovelAI.exe](https://github.com/nguyenvinhdat642/TranlateNovelAI/releases/download/v1.1.0/TranslateNovelAI.exe)**
- Tải về và chạy trực tiếp
- Không cần cài đặt Python hay dependencies
- Phiên bản portable, chạy được trên Windows

### Phương pháp 2: GUI từ source code
```bash
# Modern Desktop GUI (Khuyến nghị)
python src/gui/gui_modern.py

# Web GUI với Glass Morphism
python src/gui/gui_web.py

# Classic GUI với Tabs
python src/gui/gui_simple.py
```

### Phương pháp 3: Command line
```bash
cd src/core
python translate.py
```

### Phương pháp 4: Build exe từ source
```bash
# Build tất cả phiên bản GUI
python build_all.py

# Build từng phiên bản riêng lẻ
python build.py          # Classic GUI
python build_simple.py   # Alternative classic build

# Chạy các file exe đã build
dist/TranslateNovelAI_Web/TranslateNovelAI_Web.exe       # Web GUI
dist/TranslateNovelAI_Modern/TranslateNovelAI_Modern.exe # Modern GUI  
dist/TranslateNovelAI_Classic/TranslateNovelAI_Classic.exe # Classic GUI
dist/TranslateNovelAI_Launcher/TranslateNovelAI_Launcher.exe # GUI Launcher
```

## 🔑 Cấu hình API Keys

### 🚀 Google AI Multiple Keys (Khuyến nghị)

#### Bước 1: Lấy nhiều API keys
```
Cách 1: Tạo nhiều keys từ 1 tài khoản
- Truy cập: https://ai.google.dev/
- Click "Create API Key" nhiều lần

Cách 2: Tạo nhiều tài khoản Google (khuyến nghị)
- Mỗi tài khoản → 1 API key
- Mỗi tài khoản có quota riêng
- Tốc độ tăng gấp N lần!
```

#### Bước 2: Nhập keys vào GUI
```
1. Chọn Provider: "Google AI"
2. Nhập keys vào textbox (1 key/dòng):
   AIzaSyB1234...  # Key 1 - Account A
   AIzaSyC5678...  # Key 2 - Account B  
   AIzaSyD9012...  # Key 3 - Account C
3. Click "💾 Lưu Cài Đặt"
4. Click "🧪 Test API"
```

### 🔧 OpenRouter Single Key

#### Cách 1: Environment Variable
```bash
# Windows
set OPENROUTER_API_KEY=sk-or-v1-your_api_key_here

# Linux/Mac
export OPENROUTER_API_KEY=sk-or-v1-your_api_key_here
```

#### Cách 2: File config.json
Tạo/chỉnh sửa file `config.json`:
```json
{
  "api_provider": "OpenRouter",
  "openrouter_key": "sk-or-v1-your_api_key_here",
  "google_ai_keys": [],
  "model": "anthropic/claude-3.5-sonnet",
  "auto_reformat": true,
  "threads": "20",
  "chunk_size": "100"
}
```

#### Cách 3: Nhập trực tiếp trong GUI
1. Mở ứng dụng
2. Chọn Provider (OpenRouter hoặc Google AI)
3. Nhập API Key(s) vào ô tương ứng
4. Click "💾 Lưu Cài Đặt" để lưu lại

## 📝 Hướng dẫn sử dụng Modern GUI

### 🔑 API Configuration

#### Chọn Provider
```
OpenRouter: Nhiều models (Claude, GPT, Gemini qua OR)
Google AI:  Gemini trực tiếp (miễn phí, hỗ trợ multiple keys)
```

#### Multiple Google AI Keys
```
💡 Mỗi key 1 dòng trong textbox:
AIzaSyB1234567890...  # Key 1
AIzaSyC0987654321...  # Key 2
AIzaSyD1122334455...  # Key 3

🚀 Hệ thống tự động:
- Xoay vòng giữa các keys (Round-robin)
- Rate limit riêng cho mỗi key
- Tăng tốc độ gấp N lần (N = số keys)
```

### ⚙️ Settings và Controls

#### Performance Settings
- **Threads**: Auto-detect dựa trên CPU cores (CPU x2, max 20)
  - Với Google AI + multiple keys: Tăng threads để tận dụng keys
- **Chunk Size**: Điều chỉnh dựa trên độ phức tạp nội dung

#### Control Buttons Layout
```
[🚀 Bắt Đầu Dịch]    [💾 Lưu Cài Đặt]
[☀️ Light Mode]      [🌙 Dark Mode]
```

#### EPUB Settings (nếu bật Auto Convert)
- **Tiêu đề sách**: Tự động từ tên file hoặc nhập thủ công
- **Tác giả**: Mặc định "Unknown Author"
- **Chapter Pattern**: Regex để nhận diện chương

## 🎨 Screenshots & Demo

### 💎 Modern Desktop GUI v1.1.0
```
🤖 TranslateNovelAI - Modern Edition
┌────────────────────────────────────────────────────────────────┐
│ 🔑 API Configuration           │  📁 File Management            │
│ API Key: [**********]          │  Input: [novel.txt] [Browse]    │
│ Model: [claude-3.5-sonnet ▼]   │  Output: [novel_AI.txt] [Reset] │
│ Context: [Bối cảnh hiện đại ▼] │                                 │
│                                │  📊 Progress                    │
│ ⚡ Performance                 │  ████████░░ 80% (143 lines/s)   │
│ Threads: [20]                  │                                 │
│ Chunk Size: [100]              │  📝 Logs                        │
│                                │  [15:30:25] ✅ Hoàn thành...   │
│ ⚙️ Settings                   │  [15:30:26] 🔄 Auto reformat.. │
│ ☑ Auto reformat               │                                 │
│ ☑ Auto convert EPUB           │                                 │
│                                │                                 │
│ [🚀 Bắt Đầu Dịch] [💾 Lưu]     │                                 │
│ [☀️ Light Mode] [🌙 Dark]      │                                 │
└────────────────────────────────────────────────────────────────┘
```

## 🔧 Performance Tips

### 🚀 Tối ưu tốc độ dịch

#### 1. Dùng Multiple Google AI Keys (Nhanh nhất!) ⚡
```
3 keys  → 3x tốc độ   (~30 RPM)
5 keys  → 5x tốc độ   (~50 RPM)
10 keys → 10x tốc độ  (~100 RPM)

Cấu hình khuyến nghị:
- 3 keys:  15-20 threads
- 5 keys:  20-25 threads
- 10 keys: 25-30 threads
```

#### 2. Auto-detect threads
- App tự động detect CPU cores và setup tối ưu
- Điều chỉnh dựa trên số keys (nếu dùng Google AI)

#### 3. Chunk size
- Nội dung đơn giản: 150-200 dòng
- Nội dung phức tạp: 50-100 dòng

#### 4. Model selection

**Google AI** (Miễn phí):
- `gemini-2.0-flash-exp` - Nhanh, miễn phí (10 RPM/key)
- `gemini-1.5-flash` - Cân bằng (15 RPM/key)
- `gemini-1.5-pro` - Chất lượng cao (2 RPM/key - thấp)

**OpenRouter** (Trả phí):
- Cân bằng tốt nhất: `anthropic/claude-3.5-sonnet`
- Nhanh và rẻ: `anthropic/claude-3-haiku`
- Chất lượng cao nhất: `anthropic/claude-3-opus`
- OpenAI: `openai/gpt-4o`, `openai/gpt-4o-mini`
- Gemini (qua OpenRouter): `google/gemini-2.0-flash-001`

### 💾 Stop/Continue Best Practices
1. **Safe stopping**: Luôn sử dụng button "🛑 Dừng Dịch" thay vì force close
2. **Progress backup**: File `.progress.json` được tạo tự động
3. **Resume smart**: App tự động detect và suggest tiếp tục
4. **Cleanup**: Progress file được xóa khi hoàn thành

## 📄 License

MIT License - Sử dụng tự do cho mục đích cá nhân và thương mại.

---

## 🎭 Features Comparison

| Feature | Modern GUI | Web GUI | Classic GUI |
|---------|------------|---------|-------------|
| **Multiple Google AI Keys** | ✅ | ❌ | ❌ |
| **Key Rotation** | ✅ | ❌ | ❌ |
| **Rate Limiting** | ✅ | ❌ | ❌ |
| Dual API (OpenRouter + Google) | ✅ | ❌ | ❌ |
| Stop/Continue | ✅ | ❌ | ❌ |
| Speed Monitoring | ✅ | ✅ | ✅ |
| Auto-detect CPU | ✅ | ✅ | ✅ |
| Custom Dialogs | ✅ | ❌ | ❌ |
| Light/Dark Toggle | ✅ | ❌ | ❌ |
| Progress Recovery | ✅ | ✅ | ✅ |
| EPUB Convert | ✅ | ✅ | ✅ |
| Multi-threading | ✅ | ✅ | ✅ |

## 🔑 API Providers Comparison

| Feature | Google AI (Multiple Keys) | OpenRouter |
|---------|--------------------------|------------|
| **Giá** | 🆓 Miễn phí 100% | 💳 Trả phí |
| **Tốc độ** | ⚡ Rất nhanh (với multiple keys) | 🐢 Phụ thuộc model |
| **RPM/Key** | 10-15 RPM | Không giới hạn |
| **Multiple Keys** | ✅ Hỗ trợ | ❌ Không cần |
| **Setup** | 🟢 Dễ (không cần thẻ) | 🟡 Trung bình |
| **Models** | Gemini only | Claude, GPT, Gemini, Llama... |
| **Chất lượng** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |

---

## 🎯 Quick Start Guide

### Bước 1: Chọn Provider
```
🆓 Google AI:  Miễn phí, nhanh (với multiple keys)
💳 OpenRouter: Trả phí, nhiều models
```

### Bước 2: Lấy API Key(s)
```
Google AI:  https://ai.google.dev/ → Get API Key
OpenRouter: https://openrouter.ai/ → Create Key
```

### Bước 3: Cấu hình trong App
```
1. Chọn Provider
2. Nhập API Key(s)
3. Chọn Model
4. Click "🚀 Bắt Đầu Dịch"
```

### 💡 Pro Tips
- **Google AI + 5 keys = 5x tốc độ** (khuyến nghị!)
- **Dùng nhiều tài khoản Google** để có nhiều keys
- **Threads = số keys × 2-3** cho hiệu quả tốt nhất

---

**Happy Translating! 🎉**

*v1.2.0 - Powered by Multiple Google AI Keys, Rate Limiting & Key Rotation*

**⭐ Star this repo if you find it useful! ⭐**

📧 **Support**: [GitHub Issues](https://github.com/nguyenvinhdat642/TranlateNovelAI/issues)  
🔄 **Updates**: [Releases](https://github.com/nguyenvinhdat642/TranlateNovelAI/releases)  
📖 **Documentation**: [Wiki](https://github.com/nguyenvinhdat642/TranlateNovelAI/wiki)

## 🆕 What's New in v1.2.0

### 🔑 Multiple Google AI Keys Support
- **Hỗ trợ nhiều Google AI API keys** cùng lúc
- **Round-robin key rotation** tự động
- **Rate limiter riêng** cho mỗi key
- **Tăng tốc độ** gấp N lần (N = số keys)

### 🚀 Performance Improvements
- Smart rate limiting cho Google AI Free Tier
- Auto-adjust threads dựa trên số keys
- Key usage statistics tracking
- Optimized multi-threading

### 🎨 UI Enhancements
- Textbox để nhập nhiều keys (1 key/dòng)
- Test tất cả keys cùng lúc
- Hiển thị số lượng keys đang dùng
- Key usage statistics sau khi dịch

### 📚 Documentation
- Hướng dẫn chi tiết về multiple keys
- Performance benchmarks
- Best practices cho tốc độ tối ưu 