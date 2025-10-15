import customtkinter as ctk
from tkinter import filedialog
import threading
import os
import sys
import time
from datetime import datetime
import json
import re

# Add the parent directory to the path to make absolute imports work
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

try:
    from .custom_dialogs import show_success, show_error, show_warning, show_question, show_toast_success, show_toast_error
except ImportError:
    try:
        from custom_dialogs import show_success, show_error, show_warning, show_question, show_toast_success, show_toast_error
    except ImportError:
        # Fallback to standard messagebox if custom dialogs not available
        from tkinter import messagebox
        def show_success(msg, details=None, parent=None):
            return messagebox.showinfo("Thành công", msg)
        def show_error(msg, details=None, parent=None):
            return messagebox.showerror("Lỗi", msg)
        def show_warning(msg, details=None, parent=None):
            return messagebox.showwarning("Cảnh báo", msg)
        def show_question(msg, details=None, parent=None):
            return messagebox.askyesno("Xác nhận", msg)
        def show_toast_success(msg, duration=3000):
            return messagebox.showinfo("Thành công", msg)
        def show_toast_error(msg, duration=3000):
            return messagebox.showerror("Lỗi", msg)

try:
    from PIL import Image, ImageTk
except ImportError:
    Image = None
    ImageTk = None

# Set appearance mode and color theme
ctk.set_appearance_mode("dark")  # Modes: "System" (standard), "Dark", "Light"
ctk.set_default_color_theme("blue")  # Themes: "blue" (standard), "green", "dark-blue"

# Import translate functions
TRANSLATE_AVAILABLE = False
EPUB_AVAILABLE = False

# Try relative imports first (when run as module)
try:
    # Import OpenRouter translate functions instead of original translate
    from ..core.translate import translate_file_optimized, generate_output_filename, set_stop_translation, clear_stop_translation, is_translation_stopped, is_quota_exceeded
    from ..core.reformat import fix_text_format
    from ..core.ConvertEpub import txt_to_docx, docx_to_epub
    TRANSLATE_AVAILABLE = True
    EPUB_AVAILABLE = True
except ImportError:
    # Try absolute imports (when run directly)
    try:
        # Import OpenRouter translate functions instead of original translate
        from core.translate import translate_file_optimized, generate_output_filename, set_stop_translation, clear_stop_translation, is_translation_stopped, is_quota_exceeded
        from core.reformat import fix_text_format
        from core.ConvertEpub import txt_to_docx, docx_to_epub
        TRANSLATE_AVAILABLE = True
        EPUB_AVAILABLE = True
    except ImportError as e:
        print(f"⚠️ Lỗi import: {e}")
        print("⚠️ Một số chức năng có thể không hoạt động")
        
        # Define fallback functions
        def translate_file_optimized(*args, **kwargs):
            print("❌ Chức năng dịch không khả dụng")
            return False
            
        def generate_output_filename(input_file):
            """Generate output filename as fallback"""
            base_name = os.path.splitext(input_file)[0]
            return f"{base_name}_translated.txt"
        
        def set_stop_translation():
            print("❌ Chức năng dừng dịch không khả dụng")
            
        def clear_stop_translation():
            print("❌ Chức năng dừng dịch không khả dụng")
            
        def is_translation_stopped():
            return False
            
        def is_quota_exceeded():
            return False
            
        def fix_text_format(*args, **kwargs):
            print("❌ Chức năng reformat không khả dụng")
            return False
            
        def txt_to_docx(*args, **kwargs):
            print("❌ Chức năng convert DOCX không khả dụng")
            return False
            
        def docx_to_epub(*args, **kwargs):
            print("❌ Chức năng convert EPUB không khả dụng")
            return False

class LogCapture:
    """Class để capture print statements và chuyển về GUI"""
    def __init__(self, gui_log_function):
        self.gui_log = gui_log_function
        self.terminal = sys.stdout
        
    def write(self, message):
        if self.terminal is not None:
            try:
                self.terminal.write(message)
                self.terminal.flush()
            except:
                pass
        
        if message.strip() and self.gui_log is not None:
            try:
                self.gui_log(message.strip())
            except:
                pass
    
    def flush(self):
        if self.terminal is not None:
            try:
                self.terminal.flush()
            except:
                pass

class ModernTranslateNovelAI(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        # Configure window
        self.title("🤖 TranslateNovelAI - Modern Edition")
        self.geometry("1100x650")
        self.minsize(1000, 600)
        
        # Variables
        self.input_file_var = ctk.StringVar()
        self.output_file_var = ctk.StringVar()
        self.api_provider_var = ctk.StringVar(value="OpenRouter")  # OpenRouter hoặc Google AI
        self.openrouter_key_var = ctk.StringVar()
        self.google_ai_key_var = ctk.StringVar()
        self.google_ai_paid_key_var = ctk.StringVar()
        self.google_key_usage_var = ctk.StringVar(value="Free Keys")
        self.api_key_var = ctk.StringVar()  # Key hiện tại đang dùng (deprecated, giữ lại để tương thích)
        self.model_var = ctk.StringVar(value="anthropic/claude-3.5-sonnet")
        self.context_var = ctk.StringVar(value="Bối cảnh hiện đại")
        self.auto_reformat_var = ctk.BooleanVar(value=True)
        self.auto_convert_epub_var = ctk.BooleanVar(value=False)
        self.book_title_var = ctk.StringVar()
        self.book_author_var = ctk.StringVar(value="Unknown Author")
        self.chapter_pattern_var = ctk.StringVar(value="Chương XX:")
        self.custom_chapter_pattern_var = ctk.StringVar(value=r"^Chương\s+\d+:\s+.*$")
        self.threads_var = ctk.StringVar()
        self.chunk_size_var = ctk.StringVar(value="100")
        
        # Auto-detect optimal threads on startup
        self.auto_detect_threads(silent=True)
        
        # Translation state
        self.is_translating = False
        self.translation_thread = None
        self.total_chunks = 0
        self.completed_chunks = 0
        self.start_time = 0
        
        # Log capture
        self.original_stdout = sys.stdout
        self.log_capture = None
        
        # Setup GUI
        self.setup_gui()
        
        # Load settings
        self.load_settings()
        
        # Update appearance buttons after loading
        self.after(100, self.update_appearance_buttons)
        
    def setup_gui(self):
        """Thiết lập giao diện chính"""
        # Configure grid layout (3x1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        
        # Create sidebar frame
        self.setup_sidebar()
        
        # Create main content frame
        self.setup_main_content()
        
        # Create right panel (logs)
        self.setup_right_panel()
        
    def setup_sidebar(self):
        """Thiết lập sidebar bên trái với scroll"""
        # Create container for sidebar
        self.sidebar_container = ctk.CTkFrame(self, width=280, corner_radius=0, fg_color="transparent")
        self.sidebar_container.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.sidebar_container.grid_columnconfigure(0, weight=1)
        self.sidebar_container.grid_rowconfigure(0, weight=1)
        
        # Create scrollable sidebar inside container
        self.sidebar_frame = ctk.CTkScrollableFrame(
            self.sidebar_container, 
            width=280, 
            corner_radius=0,
            scrollbar_button_color=("gray70", "gray30"),
            scrollbar_button_hover_color=("gray60", "gray40")
        )
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)
        self.sidebar_frame.grid_columnconfigure(0, weight=1)
        
        # App title
        self.logo_label = ctk.CTkLabel(
            self.sidebar_frame,
            text="🤖 TranslateNovelAI",
            font=ctk.CTkFont(size=24, weight="bold")
        )
        self.logo_label.grid(row=0, column=0, padx=20, pady=(10, 5), sticky="ew")
        
        self.version_label = ctk.CTkLabel(
            self.sidebar_frame,
            text="Modern Edition v1.2.0 By DoLuPhi",
            font=ctk.CTkFont(size=12)
        )
        self.version_label.grid(row=1, column=0, padx=20, pady=(0, 15), sticky="ew")
        
        # API Configuration
        self.api_label = ctk.CTkLabel(
            self.sidebar_frame,
            text="🔑 API Configuration",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        self.api_label.grid(row=2, column=0, padx=20, pady=(10, 5), sticky="ew")
        
        # API Provider Selection
        self.api_provider_combo = ctk.CTkComboBox(
            self.sidebar_frame,
            values=["OpenRouter", "Google AI"],
            variable=self.api_provider_var,
            command=self.on_api_provider_changed,
            width=240
        )
        self.api_provider_combo.grid(row=3, column=0, padx=20, pady=5, sticky="ew")
        
        # OpenRouter API Key Entry
        self.openrouter_key_entry = ctk.CTkEntry(
            self.sidebar_frame,
            placeholder_text="OpenRouter API Key",
            textvariable=self.openrouter_key_var,
            show="*",
            width=240
        )
        self.openrouter_key_entry.grid(row=4, column=0, padx=20, pady=5, sticky="ew")
        
        # Google AI API Keys - Multiple keys support (Textbox instead of Entry)
        self.google_ai_keys_label = ctk.CTkLabel(
            self.sidebar_frame,
            text="Google AI Free Keys (1 key/dòng):",
            font=ctk.CTkFont(size=11),
            text_color="gray"
        )
        self.google_ai_keys_label.grid(row=5, column=0, padx=20, pady=(5, 2), sticky="w")
        
        self.google_ai_keys_textbox = ctk.CTkTextbox(
            self.sidebar_frame,
            height=80,
            width=240,
            font=ctk.CTkFont(family="Consolas", size=10)
        )
        self.google_ai_keys_textbox.grid(row=6, column=0, padx=20, pady=(0, 5), sticky="ew")
        
        # New: Google AI Paid Key Entry
        self.google_ai_paid_key_label = ctk.CTkLabel(
            self.sidebar_frame,
            text="Google AI Paid Key (Billing Enabled):",
            font=ctk.CTkFont(size=11),
            text_color="gray"
        )
        self.google_ai_paid_key_label.grid(row=7, column=0, padx=20, pady=(5, 2), sticky="w")

        self.google_ai_paid_key_entry = ctk.CTkEntry(
            self.sidebar_frame,
            placeholder_text="Enter paid API key",
            textvariable=self.google_ai_paid_key_var,
            show="*",
            width=240
        )
        self.google_ai_paid_key_entry.grid(row=8, column=0, padx=20, pady=(0, 5), sticky="ew")

        # New: Key type selection
        self.google_key_type_segmented_btn = ctk.CTkSegmentedButton(
            self.sidebar_frame,
            values=["Free Keys", "Paid Key"],
            variable=self.google_key_usage_var,
            command=self.on_google_key_type_changed
        )
        self.google_key_type_segmented_btn.grid(row=9, column=0, padx=20, pady=5, sticky="ew")
        
        # Model Selection
        self.model_combo = ctk.CTkComboBox(
            self.sidebar_frame,
            values=[
                "anthropic/claude-3.5-sonnet",
                "anthropic/claude-3-haiku", 
                "anthropic/claude-3-opus",
                "openai/gpt-4o",
                "openai/gpt-4o-mini",
                "google/gemini-2.0-flash-001",
                "🔧 Custom Model..."
            ],
            variable=self.model_var,
            command=self.on_model_changed,
            width=240
        )
        self.model_combo.grid(row=10, column=0, padx=20, pady=5, sticky="ew")
        
        # Custom model entry (initially hidden)
        self.custom_model_frame = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent")
        self.custom_model_entry = ctk.CTkEntry(
            self.custom_model_frame,
            placeholder_text="Nhập model (ví dụ: anthropic/claude-3.5-sonnet)",
            width=240
        )
        self.custom_model_entry.grid(row=0, column=0, sticky="ew")
        self.custom_model_entry.bind("<Return>", lambda e: self.confirm_custom_model())
        
        self.custom_model_confirm_btn = ctk.CTkButton(
            self.custom_model_frame,
            text="✅ OK",
            command=self.confirm_custom_model,
            width=50,
            height=28
        )
        self.custom_model_confirm_btn.grid(row=0, column=1, padx=(5, 0))
        self.custom_model_frame.grid_columnconfigure(0, weight=1)
        
        self.context_combo = ctk.CTkComboBox(
            self.sidebar_frame,
            values=[
                "Bối cảnh hiện đại",
                "Bối cảnh cổ đại",
                "Tùy chỉnh"
            ],
            variable=self.context_var,
            command=self.on_context_changed,
            width=240
        )
        self.context_combo.grid(row=11, column=0, padx=20, pady=5, sticky="ew")
        
        # Test API button
        self.test_api_btn = ctk.CTkButton(
            self.sidebar_frame,
            text="🧪 Test API",
            command=self.test_api_connection,
            width=240,
            height=30
        )
        self.test_api_btn.grid(row=12, column=0, padx=20, pady=5, sticky="ew")
        
        # Performance Settings
        self.performance_label = ctk.CTkLabel(
            self.sidebar_frame,
            text="⚡ Performance",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        self.performance_label.grid(row=13, column=0, padx=20, pady=(20, 5), sticky="ew")
        
        # Threads setting
        self.threads_frame = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent")
        self.threads_frame.grid(row=14, column=0, padx=20, pady=5, sticky="ew")
        self.threads_frame.grid_columnconfigure(1, weight=1)
        
        self.threads_label = ctk.CTkLabel(
            self.threads_frame,
            text="Threads:",
            font=ctk.CTkFont(size=12)
        )
        self.threads_label.grid(row=0, column=0, sticky="w")
        
        self.threads_entry = ctk.CTkEntry(
            self.threads_frame,
            textvariable=self.threads_var,
            width=60,
            height=28
        )
        self.threads_entry.grid(row=0, column=1, padx=(5, 0), sticky="e")
        
        # Chunk size setting
        self.chunk_frame = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent")
        self.chunk_frame.grid(row=15, column=0, padx=20, pady=5, sticky="ew")
        self.chunk_frame.grid_columnconfigure(1, weight=1)
        
        self.chunk_label = ctk.CTkLabel(
            self.chunk_frame,
            text="Chunk Size:",
            font=ctk.CTkFont(size=12)
        )
        self.chunk_label.grid(row=0, column=0, sticky="w")
        
        self.chunk_entry = ctk.CTkEntry(
            self.chunk_frame,
            textvariable=self.chunk_size_var,
            width=60,
            height=28
        )
        self.chunk_entry.grid(row=0, column=1, padx=(5, 0), sticky="e")
        
        # General Settings
        self.settings_label = ctk.CTkLabel(
            self.sidebar_frame,
            text="⚙️ Settings",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        self.settings_label.grid(row=16, column=0, padx=20, pady=(20, 5), sticky="ew")
        
        self.auto_reformat_check = ctk.CTkCheckBox(
            self.sidebar_frame,
            text="Auto reformat",
            variable=self.auto_reformat_var
        )
        self.auto_reformat_check.grid(row=17, column=0, padx=20, pady=5, sticky="w")
        
        self.auto_epub_check = ctk.CTkCheckBox(
            self.sidebar_frame,
            text="Auto convert EPUB",
            variable=self.auto_convert_epub_var,
            command=self.on_epub_setting_changed
        )
        self.auto_epub_check.grid(row=18, column=0, padx=20, pady=5, sticky="w")
        
        # Control buttons - Grid 1x2 Layout
        self.control_grid_frame = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent")
        self.control_grid_frame.grid(row=19, column=0, padx=20, pady=10, sticky="ew")
        
        # Configure grid columns với weight đều nhau
        for i in range(2):
            self.control_grid_frame.grid_columnconfigure(i, weight=1, uniform="buttons")
        
        # Row 1: Main controls
        self.translate_btn = ctk.CTkButton(
            self.control_grid_frame,
            text="🚀 Bắt Đầu Dịch",
            command=self.toggle_translation,
            height=40,
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.translate_btn.grid(row=0, column=0, padx=(0, 5), pady=(0, 5), sticky="ew")
        
        self.save_settings_btn = ctk.CTkButton(
            self.control_grid_frame,
            text="💾 Lưu Cài Đặt",
            command=self.save_settings,
            height=40
        )
        self.save_settings_btn.grid(row=0, column=1, padx=(5, 0), pady=(0, 5), sticky="ew")
        
        # Row 2: Appearance toggle
        # Appearance toggle frame
        self.appearance_frame = ctk.CTkFrame(self.control_grid_frame, fg_color="transparent")
        self.appearance_frame.grid(row=1, column=0, columnspan=2, padx=0, pady=(5, 0), sticky="ew")
        self.appearance_frame.grid_columnconfigure(0, weight=1)
        self.appearance_frame.grid_columnconfigure(1, weight=1)
        
        # Light/Dark toggle buttons
        self.light_mode_btn = ctk.CTkButton(
            self.appearance_frame,
            text="☀️ Light Mode",
            command=self.set_light_mode,
            height=40,
            font=ctk.CTkFont(size=12)
        )
        self.light_mode_btn.grid(row=0, column=0, padx=(0, 2), sticky="ew")
        
        self.dark_mode_btn = ctk.CTkButton(
            self.appearance_frame,
            text="🌙 Dark Mode",
            command=self.set_dark_mode,
            height=40,
            font=ctk.CTkFont(size=12)
        )
        self.dark_mode_btn.grid(row=0, column=1, padx=(2, 0), sticky="ew")
        
        # Initialize appearance button colors
        self.update_appearance_buttons()
        
        # Add bottom spacer for better scrolling
        self.bottom_spacer = ctk.CTkFrame(self.sidebar_frame, height=20, fg_color="transparent")
        self.bottom_spacer.grid(row=20, column=0, padx=20, pady=20, sticky="ew")
        
    def setup_main_content(self):
        """Thiết lập nội dung chính"""
        self.main_frame = ctk.CTkScrollableFrame(self)
        self.main_frame.grid(row=0, column=1, sticky="nsew", padx=10)
        self.main_frame.grid_columnconfigure(0, weight=1)
        
        # Title
        self.main_title = ctk.CTkLabel(
            self.main_frame,
            text="📁 File Management & Processing",
            font=ctk.CTkFont(size=20, weight="bold")
        )
        self.main_title.grid(row=0, column=0, padx=20, pady=20)
        
        # File selection frame
        self.file_frame = ctk.CTkFrame(self.main_frame)
        self.file_frame.grid(row=1, column=0, sticky="ew", padx=20, pady=10)
        self.file_frame.grid_columnconfigure(1, weight=1)
        
        # Input file
        self.input_label = ctk.CTkLabel(
            self.file_frame,
            text="Input File:",
            font=ctk.CTkFont(weight="bold")
        )
        self.input_label.grid(row=0, column=0, padx=20, pady=(20, 5), sticky="w")
        
        self.input_entry = ctk.CTkEntry(
            self.file_frame,
            textvariable=self.input_file_var,
            placeholder_text="Chọn file truyện cần dịch..."
        )
        self.input_entry.grid(row=1, column=0, columnspan=2, padx=20, pady=5, sticky="ew")
        
        self.input_btn = ctk.CTkButton(
            self.file_frame,
            text="📁 Browse",
            command=self.browse_input_file,
            width=100
        )
        self.input_btn.grid(row=2, column=0, padx=20, pady=5, sticky="w")
        
        # Output file
        self.output_label = ctk.CTkLabel(
            self.file_frame,
            text="Output File:",
            font=ctk.CTkFont(weight="bold")
        )
        self.output_label.grid(row=3, column=0, padx=20, pady=(15, 5), sticky="w")
        
        self.output_entry = ctk.CTkEntry(
            self.file_frame,
            textvariable=self.output_file_var,
            placeholder_text="File output sẽ được tự động tạo..."
        )
        self.output_entry.grid(row=4, column=0, columnspan=2, padx=20, pady=5, sticky="ew")
        
        self.output_btn_frame = ctk.CTkFrame(self.file_frame, fg_color="transparent")
        self.output_btn_frame.grid(row=5, column=0, columnspan=2, padx=20, pady=(5, 20), sticky="w")
        
        self.output_btn = ctk.CTkButton(
            self.output_btn_frame,
            text="📁 Browse",
            command=self.browse_output_file,
            width=100
        )
        self.output_btn.grid(row=0, column=0, padx=(0, 10))
        
        self.reset_output_btn = ctk.CTkButton(
            self.output_btn_frame,
            text="🔄 Reset",
            command=self.reset_output_filename,
            width=100
        )
        self.reset_output_btn.grid(row=0, column=1)
        
        # EPUB Settings (initially hidden)
        self.epub_frame = ctk.CTkFrame(self.main_frame)
        self.epub_frame.grid_columnconfigure(0, weight=1)
        
        self.epub_title_label = ctk.CTkLabel(
            self.epub_frame,
            text="📚 EPUB Settings",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        self.epub_title_label.grid(row=0, column=0, padx=20, pady=(20, 10))
        
        self.book_title_entry = ctk.CTkEntry(
            self.epub_frame,
            textvariable=self.book_title_var,
            placeholder_text="Tiêu đề sách"
        )
        self.book_title_entry.grid(row=1, column=0, padx=20, pady=5, sticky="ew")
        
        self.book_author_entry = ctk.CTkEntry(
            self.epub_frame,
            textvariable=self.book_author_var,
            placeholder_text="Tác giả"
        )
        self.book_author_entry.grid(row=2, column=0, padx=20, pady=5, sticky="ew")
        
        # Chapter header pattern selection
        self.chapter_pattern_label = ctk.CTkLabel(
            self.epub_frame,
            text="Định dạng tiêu đề chương:",
            font=ctk.CTkFont(weight="bold")
        )
        self.chapter_pattern_label.grid(row=3, column=0, padx=20, pady=(10, 5), sticky="w")
        
        self.chapter_pattern_combo = ctk.CTkComboBox(
            self.epub_frame,
            values=[
                "Chương XX:",
                "Chương XX",
                "XXX",
                "XXX:",
                "Phần X:",
                "Phần X",
                "Chapter X:",
                "Chapter X",
                "第X章",
                "第X章:",
                "Tùy chỉnh"
            ],
            variable=self.chapter_pattern_var,
            command=self.on_chapter_pattern_changed,
            width=240
        )
        self.chapter_pattern_combo.grid(row=4, column=0, padx=20, pady=5, sticky="ew")
        
        # Custom pattern entry (hidden by default)
        self.custom_pattern_frame = ctk.CTkFrame(self.epub_frame, fg_color="transparent")
        self.custom_pattern_frame.grid_columnconfigure(0, weight=1)
        
        self.custom_pattern_label = ctk.CTkLabel(
            self.custom_pattern_frame,
            text="Regex pattern tùy chỉnh:",
            font=ctk.CTkFont(size=12)
        )
        self.custom_pattern_label.grid(row=0, column=0, padx=20, pady=(5, 2), sticky="w")
        
        self.custom_pattern_entry = ctk.CTkEntry(
            self.custom_pattern_frame,
            textvariable=self.custom_chapter_pattern_var,
            placeholder_text="Nhập regex pattern..."
        )
        self.custom_pattern_entry.grid(row=1, column=0, padx=20, pady=(2, 10), sticky="ew")

        # Progress frame
        self.progress_frame = ctk.CTkFrame(self.main_frame)
        self.progress_frame.grid(row=3, column=0, sticky="ew", padx=20, pady=10)
        self.progress_frame.grid_columnconfigure(0, weight=1)
        
        self.progress_label = ctk.CTkLabel(
            self.progress_frame,
            text="📊 Progress",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        self.progress_label.grid(row=0, column=0, padx=20, pady=(20, 5))
        
        self.progress_text = ctk.CTkLabel(
            self.progress_frame,
            text="Sẵn sàng để bắt đầu...",
            font=ctk.CTkFont(size=12)
        )
        self.progress_text.grid(row=1, column=0, padx=20, pady=5)
        
        self.progress_bar = ctk.CTkProgressBar(self.progress_frame)
        self.progress_bar.grid(row=2, column=0, padx=20, pady=(5, 20), sticky="ew")
        self.progress_bar.set(0)
        
        # Custom prompt frame (hidden by default)
        self.custom_prompt_frame = ctk.CTkFrame(self.main_frame)
        self.custom_prompt_frame.grid_columnconfigure(0, weight=1)
        
        self.custom_prompt_label = ctk.CTkLabel(
            self.custom_prompt_frame,
            text="Custom Prompt:",
            font=ctk.CTkFont(weight="bold")
        )
        self.custom_prompt_label.grid(row=0, column=0, padx=20, pady=(20, 5), sticky="w")
        
        self.custom_prompt_textbox = ctk.CTkTextbox(
            self.custom_prompt_frame,
            height=100
        )
        self.custom_prompt_textbox.grid(row=1, column=0, padx=20, pady=(5, 20), sticky="ew")
        
    def setup_right_panel(self):
        """Thiết lập panel logs bên phải"""
        self.right_panel = ctk.CTkFrame(self, width=350)
        self.right_panel.grid(row=0, column=2, sticky="nsew", padx=(10, 0))
        self.right_panel.grid_rowconfigure(2, weight=1)
        self.right_panel.grid_columnconfigure(0, weight=1)
        
        # Logs title
        self.logs_title = ctk.CTkLabel(
            self.right_panel,
            text="📝 Logs & Information",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        self.logs_title.grid(row=0, column=0, padx=20, pady=(20, 10))
        
        # Log controls
        self.log_controls_frame = ctk.CTkFrame(self.right_panel, fg_color="transparent")
        self.log_controls_frame.grid(row=1, column=0, sticky="ew", padx=20, pady=5)
        
        self.clear_log_btn = ctk.CTkButton(
            self.log_controls_frame,
            text="🗑️ Clear",
            command=self.clear_logs,
            width=80,
            height=30
        )
        self.clear_log_btn.grid(row=0, column=0, padx=(0, 5))
        
        self.save_log_btn = ctk.CTkButton(
            self.log_controls_frame,
            text="💾 Save",
            command=self.save_logs,
            width=80,
            height=30
        )
        self.save_log_btn.grid(row=0, column=1, padx=5)
        
        self.auto_scroll_var = ctk.BooleanVar(value=True)
        self.auto_scroll_check = ctk.CTkCheckBox(
            self.log_controls_frame,
            text="Auto-scroll",
            variable=self.auto_scroll_var
        )
        self.auto_scroll_check.grid(row=0, column=2, padx=(5, 0))
        
        # Log text area
        self.log_textbox = ctk.CTkTextbox(
            self.right_panel,
            font=ctk.CTkFont(family="Consolas", size=10)
        )
        self.log_textbox.grid(row=2, column=0, padx=20, pady=(5, 20), sticky="nsew")
        
    def on_api_provider_changed(self, choice):
        """Xử lý khi thay đổi API provider"""
        if choice == "OpenRouter":
            # Show OpenRouter key, hide Google AI keys
            self.openrouter_key_entry.grid()
            self.google_ai_keys_label.grid_remove()
            self.google_ai_keys_textbox.grid_remove()
            self.google_ai_paid_key_label.grid_remove()
            self.google_ai_paid_key_entry.grid_remove()
            self.google_key_type_segmented_btn.grid_remove()
            
            # Update model list for OpenRouter
            self.model_combo.configure(values=[
                "anthropic/claude-3.5-sonnet",
                "anthropic/claude-3-haiku",
                "anthropic/claude-3-opus",
                "openai/gpt-4o",
                "openai/gpt-4o-mini",
                "google/gemini-2.0-flash-001",
                "google/gemini-1.5-pro",
                "🔧 Custom Model..."
            ])
            # Set default model if current is not compatible
            current_model = self.model_var.get()
            if not any(m in current_model for m in ['/', 'custom']):
                self.model_var.set("anthropic/claude-3.5-sonnet")
            
            self.log("🔄 Chuyển sang OpenRouter API")
            
        elif choice == "Google AI":
            # Hide OpenRouter key, show Google AI keys
            self.openrouter_key_entry.grid_remove()
            self.google_key_type_segmented_btn.grid()
            self.on_google_key_type_changed() # Show correct entry based on selector's current value
            
            # Update model list for Google AI
            self.model_combo.configure(values=[
                "gemini-2.5-pro",
                "gemini-2.5-flash",
                "gemini-2.5-flash-lite",
                "gemini-2.0-flash",
                "gemini-2.0-flash-lite",
                "gemini-1.5-pro",
                "gemini-1.5-flash",
                "🔧 Custom Model..."
            ])
            # Set default model for Google AI
            self.model_var.set("gemini-2.5-flash")
            
            self.log("🔄 Chuyển sang Google AI API")
            
            # Hiển thị cảnh báo về rate limits và mẹo dùng nhiều keys
            self.log("⚠️ Google AI Free Tier có giới hạn RPM (Requests Per Minute) thấp.")
            self.log("   - Các model Pro thường có RPM rất thấp (ví dụ: 2 RPM).")
            self.log("   - Các model Flash thường có RPM cao hơn (ví dụ: 10-15 RPM).")
            self.log("💡 TIP: Nhập NHIỀU keys (1 key/dòng) để tăng tốc độ!")
            self.log("   • Hệ thống sẽ tự động xoay vòng giữa các keys.")
            self.log("   • Mỗi key có rate limit riêng → tổng RPM tăng lên.")
            self.log("   • Luôn kiểm tra giới hạn RPM mới nhất tại trang chủ Google AI.")
            self.log("   • Tham khảo: https://ai.google.dev/gemini-api/docs/rate-limits")
    
    def on_model_changed(self, choice):
        """Xử lý khi thay đổi model"""
        if choice == "🔧 Custom Model...":
            self.custom_model_frame.grid(row=10, column=0, padx=20, pady=5, sticky="ew")
            self.custom_model_entry.focus()
        else:
            self.custom_model_frame.grid_remove()
    
    def confirm_custom_model(self):
        """Xác nhận custom model"""
        custom_model = self.custom_model_entry.get().strip()
        if not custom_model:
            show_error("Vui lòng nhập tên model!", parent=self)
            return
        
        # Validate model format
        if '/' not in custom_model:
            result = show_question(
                f"Model '{custom_model}' không có format chuẩn 'provider/model-name'.\n\n"
                f"Ví dụ format đúng: anthropic/claude-3.5-sonnet\n\n"
                f"Bạn có muốn tiếp tục với model này không?",
                parent=self
            )
            if not result:
                return
        
        # Set the custom model
        self.model_var.set(custom_model)
        self.custom_model_frame.grid_remove()
        self.log(f"🔧 Đã đặt custom model: {custom_model}")
        show_success(f"Đã đặt custom model:\n{custom_model}", parent=self)
    
    def on_google_key_type_changed(self, choice=None):
        """Xử lý khi thay đổi loại key Google AI (Free/Paid)"""
        if choice is None:
            choice = self.google_key_usage_var.get()
        
        if choice == "Free Keys":
            self.google_ai_keys_label.grid()
            self.google_ai_keys_textbox.grid()
            self.google_ai_paid_key_label.grid_remove()
            self.google_ai_paid_key_entry.grid_remove()
            self.log("🔑 Chuyển sang dùng các API keys miễn phí.")
        elif choice == "Paid Key":
            self.google_ai_keys_label.grid_remove()
            self.google_ai_keys_textbox.grid_remove()
            self.google_ai_paid_key_label.grid()
            self.google_ai_paid_key_entry.grid()
            self.log("💳 Chuyển sang dùng API key trả phí.")
    
    def on_context_changed(self, choice):
        """Xử lý khi thay đổi bối cảnh dịch"""
        if choice == "Tùy chỉnh":
            self.custom_prompt_frame.grid(row=4, column=0, sticky="ew", padx=20, pady=10)
            # Load default custom prompt
            default_custom = """Bạn là một chuyên gia dịch thuật, chuyên dịch truyện sang tiếng Việt. Nhiệm vụ của bạn là dịch văn bản sau đây một cách chính xác, tự nhiên và tuân thủ nghiêm ngặt các quy tắc dưới đây.

# QUY TẮC DỊCH THUẬT (BẮT BUỘC TUÂN THỦ)

1. Văn phong và Bối cảnh:
*   Sử dụng văn phong hiện đại, tự nhiên, phù hợp với bối cảnh của câu chuyện và phù hợp với ngữ pháp tiếng Việt.
*   Giữ nguyên tất cả các chi tiết, mô tả và nội dung gốc. Không được lược bỏ hay thay đổi ý nghĩa của văn bản.

2. Danh xưng người kể chuyện (QUAN TRỌNG):
*   NGƯỜI KỂ CHUYỆN (narrator) luôn xưng "tôi" trong bối cảnh hiện đại hoặc "ta" trong bối cảnh cổ đại.
*   KHÔNG BAO GIỜ dịch người kể chuyện thành "ba", "bố", "con", "anh", "chị" hay bất kỳ danh xưng nào khác.
*   Phân biệt rõ giữa lời kể của tác giả và lời thoại của nhân vật.

3. Lời thoại và Xưng hô nhân vật:
*   Xác định rõ mối quan hệ giữa các nhân vật (cha-con, anh-em, chị-em, mẹ-con,...) để sử dụng đại từ nhân xưng phù hợp.
*   Đặt toàn bộ lời thoại của nhân vật trong dấu ngoặc kép "...".
*   Chỉ áp dụng danh xưng quan hệ (ba, mẹ, anh, chị, con...) cho lời thoại TRONG dấu ngoặc kép.

4. Định dạng Output:
*   Chỉ trả về văn bản đã dịch. Không thêm bất kỳ lời bình luận, giải thích hay nội dung nào khác ngoài bản dịch.

---
BẮT ĐẦU DỊCH VĂN BẢN DƯỚI ĐÂY:"""
            self.custom_prompt_textbox.delete("0.0", "end")
            self.custom_prompt_textbox.insert("0.0", default_custom)
        else:
            self.custom_prompt_frame.grid_remove()
    
    def get_system_instruction(self):
        """Tạo system instruction dựa trên bối cảnh đã chọn"""
        context = self.context_var.get()
        
        base_instruction = """Bạn là một chuyên gia dịch thuật, chuyên dịch truyện sang tiếng Việt. Nhiệm vụ của bạn là dịch văn bản sau đây một cách chính xác, tự nhiên và tuân thủ nghiêm ngặt các quy tắc dưới đây.

# QUY TẮC DỊCH THUẬT (BẮT BUỘC TUÂN THỦ)

1. Văn phong và Bối cảnh:
*   Sử dụng văn phong hiện đại, tự nhiên, phù hợp với bối cảnh của câu chuyện và phù hợp với ngữ pháp tiếng Việt.
*   Giữ nguyên tất cả các chi tiết, mô tả và nội dung gốc. Không được lược bỏ hay thay đổi ý nghĩa của văn bản.

2. Danh xưng người kể chuyện (QUAN TRỌNG):
*   NGƯỜI KỂ CHUYỆN (narrator) luôn xưng "tôi" trong bối cảnh hiện đại hoặc "ta" trong bối cảnh cổ đại.
*   KHÔNG BAO GIỜ dịch người kể chuyện thành "ba", "bố", "con", "anh", "chị" hay bất kỳ danh xưng nào khác.
*   Phân biệt rõ giữa lời kể của tác giả và lời thoại của nhân vật.

3. Lời thoại và Xưng hô nhân vật:
*   Xác định rõ mối quan hệ giữa các nhân vật (cha-con, anh-em, chị-em, mẹ-con,...) để sử dụng đại từ nhân xưng phù hợp.
*   Đặt toàn bộ lời thoại của nhân vật trong dấu ngoặc kép "...".
*   Chỉ áp dụng danh xưng quan hệ (ba, mẹ, anh, chị, con...) cho lời thoại TRONG dấu ngoặc kép.

4. Định dạng Output:
*   Chỉ trả về văn bản đã dịch. Không thêm bất kỳ lời bình luận, giải thích hay nội dung nào khác ngoài bản dịch.

---
BẮT ĐẦU DỊCH VĂN BẢN DƯỚI ĐÂY:"""
        
        context_instructions = {
            "Bối cảnh hiện đại": f"""{base_instruction}

# BỐI CẢNH ĐẶC BIỆT - HIỆN ĐẠI:

5. Văn phong hiện đại:
*   Sử dụng ngôn ngữ tự nhiên, gần gũi, phù hợp với cuộc sống hiện đại
*   Người kể chuyện luôn xưng "tôi" (KHÔNG dùng ba, bố, con, anh, chị...)
*   Lời thoại nhân vật: anh/chị, em, bạn, cậu/mày, ông/bà (tùy mối quan hệ)
*   Giữ nguyên các từ ngữ thô tục, tình dục, slang nếu có trong nguyên bản
*   Sử dụng thuật ngữ công nghệ, mạng xã hội, đời sống đô thị hiện đại

6. Đặc điểm riêng:
*   Lời thoại tự nhiên như người Việt nói hàng ngày
*   Không cần quá trang trọng trừ khi ngữ cảnh yêu cầu
*   Giữ nguyên tên riêng, địa danh, thương hiệu nước ngoài""",

            "Bối cảnh cổ đại": f"""{base_instruction}

# BỐI CẢNH ĐẶC BIỆT - CỔ ĐẠI:

5. Văn phong cổ điển:
*   Sử dụng ngôn ngữ trang trọng, lịch thiệp phù hợp thời kỳ cổ đại
*   Người kể chuyện luôn xưng "ta" (KHÔNG dùng thần, hạ thần, tiểu nhân...)
*   Lời thoại nhân vật: ta/ngươi, hạ thần/thần tử, công tử/tiểu thư, sư phụ/đồ đệ
*   Thuật ngữ võ thuật: công pháp, tâm pháp, tu vi, cảnh giới, đan dược
*   Chức vị cổ đại: hoàng thượng, hoàng hậu, thái tử, đại thần, tướng quân

6. Đặc điểm riêng:
*   Lời thoại trang nghiêm, có phép tắc
*   Sử dụng từ Hán Việt khi phù hợp
*   Giữ nguyên tên võ công, tâm pháp, địa danh cổ đại
*   Thể hiện đúng thứ bậc, lễ nghĩa trong xã hội phong kiến""",

            "Tùy chỉnh": self.custom_prompt_textbox.get("0.0", "end").strip() if hasattr(self, 'custom_prompt_textbox') else base_instruction
        }
        
        return context_instructions.get(context, base_instruction)
    
    def browse_input_file(self):
        """Chọn file input"""
        file_path = filedialog.askopenfilename(
            title="Chọn file truyện cần dịch",
            filetypes=[
                ("Text files", "*.txt"),
                ("All files", "*.*")
            ]
        )
        if file_path:
            self.input_file_var.set(file_path)
            
            # Auto-generate output filename
            output_path = generate_output_filename(file_path)
            self.output_file_var.set(output_path)
            self.log(f"📁 Tự động tạo tên file output: {os.path.basename(output_path)}")
            
            # Auto-fill book title from filename
            if not self.book_title_var.get() or self.book_title_var.get() == "Unknown Title":
                filename = os.path.splitext(os.path.basename(file_path))[0]
                self.book_title_var.set(filename)
            
            # Check if there's existing progress
            progress_file = f"{file_path}.progress.json"
            if os.path.exists(progress_file):
                try:
                    with open(progress_file, 'r', encoding='utf-8') as f:
                        progress_data = json.load(f)
                        completed_chunks = progress_data.get('completed_chunks', 0)
                        if completed_chunks > 0:
                            self.log(f"🔄 Phát hiện tiến độ cũ: {completed_chunks} chunks đã hoàn thành")
                            self.translate_btn.configure(
                                text="▶️ Tiếp Tục Dịch",
                                fg_color=("blue", "darkblue"),
                                hover_color=("darkblue", "blue")
                            )
                            self.progress_text.configure(text=f"Sẵn sàng tiếp tục ({completed_chunks} chunks đã xong)")
                except Exception as e:
                    self.log(f"⚠️ Lỗi đọc file tiến độ: {e}")
            else:
                self.translate_btn.configure(
                    text="🚀 Bắt Đầu Dịch",
                    fg_color=("blue", "darkblue"),
                    hover_color=("darkblue", "blue")
                )
                self.progress_text.configure(text="Sẵn sàng để bắt đầu...")
    
    def browse_output_file(self):
        """Chọn file output"""
        initial_dir = ""
        if self.input_file_var.get():
            initial_dir = os.path.dirname(self.input_file_var.get())
            
        file_path = filedialog.asksaveasfilename(
            title="Chọn nơi lưu file đã dịch",
            initialdir=initial_dir,
            defaultextension=".txt",
            filetypes=[
                ("Text files", "*.txt"),
                ("All files", "*.*")
            ]
        )
        if file_path:
            self.output_file_var.set(file_path)
            self.log(f"📁 Đã chọn file output: {os.path.basename(file_path)}")
    
    def reset_output_filename(self):
        """Reset output filename to auto-generated name"""
        if not self.input_file_var.get():
            show_warning("Vui lòng chọn file input trước!", parent=self)
            return
            
        output_path = generate_output_filename(self.input_file_var.get())
        self.output_file_var.set(output_path)
        self.log(f"🔄 Đã reset tên file output: {os.path.basename(output_path)}")
    
    def auto_detect_threads(self, silent=False):
        """Tự động phát hiện số threads tối ưu cho máy"""
        try:
            import multiprocessing
            cpu_cores = multiprocessing.cpu_count()
            
            # Tính toán threads tối ưu:
            # - I/O bound tasks nên dùng nhiều threads hơn số cores
            # - Nhưng không quá nhiều để tránh rate limiting
            optimal_threads = min(max(cpu_cores * 2, 4), 20)
            
            self.threads_var.set(str(optimal_threads))
            
            if not silent:
                self.log(f"🖥️ Phát hiện {cpu_cores} CPU cores")
                self.log(f"🔧 Đã đặt threads tối ưu: {optimal_threads}")
                show_success(f"Đã đặt threads tối ưu: {optimal_threads}\n(Dựa trên {cpu_cores} CPU cores)", parent=self)
            else:
                self.log(f"🔧 Tự động đặt {optimal_threads} threads (CPU: {cpu_cores} cores)")
                
        except Exception as e:
            if not silent:
                self.log(f"⚠️ Lỗi khi phát hiện CPU: {e}")
                show_warning(f"Không thể tự động phát hiện CPU.\nĐặt về mặc định: 10 threads", parent=self)
            self.threads_var.set("10")
    
    def setup_log_capture(self):
        """Thiết lập log capture"""
        if not self.log_capture:
            self.log_capture = LogCapture(self.log_from_translate)
            sys.stdout = self.log_capture
    
    def restore_stdout(self):
        """Khôi phục stdout"""
        if self.log_capture:
            sys.stdout = self.original_stdout
            self.log_capture = None
    
    def log_from_translate(self, message):
        """Nhận log từ translate.py và hiển thị lên GUI"""
        self.after(0, lambda: self._update_log_ui(message))
    
    def _update_log_ui(self, message):
        """Update log UI (thread-safe)"""
        try:
            timestamp = datetime.now().strftime("%H:%M:%S")
            log_message = f"[{timestamp}] {message}"
            
            # Update log textbox
            if hasattr(self, 'log_textbox') and self.log_textbox is not None:
                self.log_textbox.insert("end", log_message + "\n")
            
            # Auto-scroll if enabled
            if hasattr(self, 'auto_scroll_var') and self.auto_scroll_var.get():
                if hasattr(self, 'log_textbox') and self.log_textbox is not None:
                    self.log_textbox.see("end")
            
            # Update progress if it's a progress message
            self._update_progress_from_log(message)
            
            if hasattr(self, 'update_idletasks'):
                self.update_idletasks()
        except Exception as e:
            print(f"⚠️ Lỗi update log UI: {e}")
    
    def _update_progress_from_log(self, message):
        """Cập nhật progress bar từ log messages"""
        try:
            import re
            
            # Pattern: "Hoàn thành chunk X/Y"
            match1 = re.search(r'Hoàn thành chunk (\d+)/(\d+)', message)
            if match1:
                current = int(match1.group(1))
                total = int(match1.group(2))
                progress_percent = (current / total)
                self.progress_bar.set(progress_percent)
                self.progress_text.configure(text=f"Hoàn thành chunk {current}/{total} ({progress_percent*100:.1f}%)")
                return
            
            # Pattern: "Tiến độ: X/Y chunks"
            match2 = re.search(r'Tiến độ: (\d+)/(\d+) chunks \((\d+\.?\d*)%\)', message)
            if match2:
                current = int(match2.group(1))
                total = int(match2.group(2))
                percent = float(match2.group(3))
                self.progress_bar.set(percent / 100)
                self.progress_text.configure(text=f"Tiến độ: {current}/{total} chunks ({percent:.1f}%)")
                return
                
        except Exception:
            pass
    
    def log(self, message):
        """Ghi log vào text area"""
        try:
            timestamp = datetime.now().strftime("%H:%M:%S")
            log_message = f"[{timestamp}] {message}"
            
            if hasattr(self, 'log_textbox') and self.log_textbox is not None:
                self.log_textbox.insert("end", log_message + "\n")
            
            if hasattr(self, 'auto_scroll_var') and self.auto_scroll_var.get():
                if hasattr(self, 'log_textbox') and self.log_textbox is not None:
                    self.log_textbox.see("end")
                
            if hasattr(self, 'update_idletasks'):
                self.update_idletasks()
            
            print(message)  # Also print to console
        except Exception as e:
            print(f"⚠️ Lỗi log GUI: {e} - Message: {message}")
    
    def clear_logs(self):
        """Xóa logs"""
        try:
            if hasattr(self, 'log_textbox') and self.log_textbox is not None:
                self.log_textbox.delete("0.0", "end")
            print("🗑️ Đã xóa logs")
        except Exception as e:
            print(f"⚠️ Lỗi xóa logs: {e}")
    
    def save_logs(self):
        """Lưu logs ra file"""
        file_path = filedialog.asksaveasfilename(
            title="Lưu logs",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if file_path:
            try:
                content = self.log_textbox.get("0.0", "end")
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                self.log(f"💾 Đã lưu logs vào: {file_path}")
            except Exception as e:
                self.log(f"❌ Lỗi lưu logs: {e}")
    
    def toggle_translation(self):
        """Toggle giữa bắt đầu dịch và dừng dịch"""
        if self.is_translating:
            # Đang dịch -> Dừng
            set_stop_translation()
            self.log("🛑 Đã yêu cầu dừng dịch...")
            self.translate_btn.configure(text="⏳ Đang dừng...", state="disabled")
        else:
            # Chưa dịch hoặc đã dừng -> Bắt đầu/Tiếp tục dịch
            self.start_translation()
    
    def continue_translation(self):
        """Tiếp tục dịch từ nơi đã dừng"""
        # Kiểm tra xem có file input không
        if not self.input_file_var.get().strip():
            show_error("Vui lòng chọn file input trước!", parent=self)
            return
        
        # Kiểm tra API key
        if not self.api_key_var.get().strip():
            show_error("Vui lòng nhập API Key!", parent=self)
            return
        
        self.log("▶️ Tiếp tục dịch từ nơi đã dừng...")
        self.start_translation()
    
    def start_translation(self):
        """Bắt đầu quá trình dịch"""
        if not TRANSLATE_AVAILABLE:
            show_error("Không thể import module dịch. Vui lòng kiểm tra lại file translate.py", parent=self)
            return
            
        # Validate inputs - get current API key(s) based on provider
        api_key = self.get_current_api_key()
        provider = self.get_current_provider()
        
        # Validate API key
        if provider == "Google AI":
            # For Google AI, api_key should be a list
            if not api_key or (isinstance(api_key, list) and len(api_key) == 0):
                show_error(f"Vui lòng nhập ít nhất 1 Google AI API Key", parent=self)
                return
        else:
            # For OpenRouter, api_key should be a string
            if not api_key or not api_key.strip():
                show_error(f"Vui lòng nhập {provider} API Key", parent=self)
                return
            
        if not self.input_file_var.get().strip():
            show_error("Vui lòng chọn file input", parent=self)
            return
            
        if not os.path.exists(self.input_file_var.get()):
            show_error("File input không tồn tại", parent=self)
            return
        
        output_file = self.output_file_var.get().strip()
        if not output_file:
            output_file = generate_output_filename(self.input_file_var.get())
            self.output_file_var.set(output_file)
            self.log(f"📝 Tự động tạo tên file output: {os.path.basename(output_file)}")
        
        # Check if input and output are the same
        if os.path.abspath(self.input_file_var.get()) == os.path.abspath(output_file):
            show_error("File input và output không thể giống nhau!", parent=self)
            return
        
        # Warn if output file exists (only for new translation, not continue)
        if not is_translation_stopped() and os.path.exists(output_file):
            progress_file = f"{self.input_file_var.get()}.progress.json"
            if not os.path.exists(progress_file):  # Only warn if not continuing
                result = show_question(
                    f"File output đã tồn tại:\n{os.path.basename(output_file)}\n\nBạn có muốn ghi đè không?",
                    parent=self
                )
                if not result:
                    return
        
        # Start translation
        self.is_translating = True
        self.translate_btn.configure(
            state="normal", 
            text="🛑 Dừng Dịch",
            fg_color=("red", "darkred"),
            hover_color=("darkred", "red")
        )
        self.progress_bar.set(0)
        self.progress_text.configure(text="Đang dịch...")
        
        # Setup log capture
        self.setup_log_capture()
        
        # Validate performance settings
        try:
            num_threads = int(self.threads_var.get())
            if num_threads < 1 or num_threads > 50:
                show_warning("Số threads phải từ 1 đến 50!", parent=self)
                return
        except ValueError:
            show_warning("Số threads phải là số nguyên!", parent=self)
            return
            
        try:
            chunk_size = int(self.chunk_size_var.get())
            if chunk_size < 10 or chunk_size > 500:
                show_warning("Chunk size phải từ 10 đến 500!", parent=self)
                return
        except ValueError:
            show_warning("Chunk size phải là số nguyên!", parent=self)
            return
        
        # Get current model (handle custom model)
        current_model = self.get_current_model()
        provider = self.get_current_provider()
        is_paid_key = (provider == "Google AI" and self.google_key_usage_var.get() == "Paid Key")
        
        self.log("🚀 Bắt đầu quá trình dịch...")
        self.log(f"📁 Input: {os.path.basename(self.input_file_var.get())}")
        self.log(f"📁 Output: {os.path.basename(output_file)}")
        self.log(f"🔑 Provider: {provider}")
        
        # Log số lượng keys cho Google AI
        if provider == "Google AI" and isinstance(api_key, list):
            self.log(f"🔑 Số lượng API keys: {len(api_key)} keys")
            self.log(f"💡 Tổng RPM ước tính: ~{len(api_key) * 10} RPM (mỗi key ~10 RPM)")
        
        self.log(f"🤖 Model: {current_model}")
        self.log(f"⚡ Threads: {num_threads}")
        self.log(f"📦 Chunk size: {chunk_size} dòng")
        
        # Run in thread
        self.translation_thread = threading.Thread(
            target=self.run_translation,
            args=(self.input_file_var.get(), output_file, api_key, current_model, self.get_system_instruction(), num_threads, chunk_size, provider, is_paid_key),
            daemon=True
        )
        self.translation_thread.start()
        
        # Start monitoring translation status
        self.check_translation_status()
    
    def check_translation_status(self):
        """Kiểm tra trạng thái dịch định kỳ"""
        if self.is_translating:
            # Kiểm tra nếu translation thread còn sống không
            if hasattr(self, 'translation_thread') and self.translation_thread:
                if not self.translation_thread.is_alive():
                    # Translation thread đã kết thúc - có thể thành công hoặc thất bại
                    self.log("🔄 Translation thread đã kết thúc")
                    return  # Không schedule check tiếp, để translation_finished() xử lý
            
            if is_translation_stopped():
                # Translation has been stopped
                if is_quota_exceeded():
                    self.log("💳 API đã hết quota!")
                    self.is_translating = False
                    self.translate_btn.configure(
                        state="normal", 
                        text="🔄 Cần API Key Mới",
                        fg_color=("orange", "darkorange"),
                        hover_color=("darkorange", "orange")
                    )
                    self.progress_text.configure(text="API hết quota - cần API key mới")
                    self.restore_stdout()
                    
                    # Show quota exceeded dialog
                    self.show_quota_exceeded_dialog()
                    return
                else:
                    self.log("🛑 Dịch đã bị dừng")
                    self.is_translating = False
                    self.translate_btn.configure(
                        state="normal", 
                        text="▶️ Tiếp Tục Dịch",
                        fg_color=("blue", "darkblue"),
                        hover_color=("darkblue", "blue")
                    )
                    self.progress_text.configure(text="Đã dừng - có thể tiếp tục")
                    self.restore_stdout()
                    return
            else:
                # Check again after 1 second only if still translating
                if self.is_translating:
                    self.after(1000, self.check_translation_status)
    
    def translation_finished(self):
        """Kết thúc quá trình dịch"""
        # Đảm bảo chỉ chạy một lần
        if not self.is_translating:
            return  # Đã được xử lý rồi
            
        self.log("🏁 Kết thúc quá trình dịch...")
        self.is_translating = False
        
        # Restore stdout
        self.restore_stdout()
        
        if is_quota_exceeded():
            # API hết quota
            self.translate_btn.configure(
                state="normal", 
                text="🔄 Cần API Key Mới",
                fg_color=("orange", "darkorange"),
                hover_color=("darkorange", "orange")
            )
            self.progress_text.configure(text="API hết quota - cần API key mới")
        else:
            # Dịch hoàn thành hoặc bị dừng bình thường
            self.translate_btn.configure(
                state="normal", 
                text="🚀 Bắt Đầu Dịch",
                fg_color=("blue", "darkblue"),
                hover_color=("darkblue", "blue")
            )
            
            # Kiểm tra trạng thái progress text hiện tại
            current_progress = self.progress_text.cget("text")
            if not current_progress.startswith("Hoàn thành"):
                # Check if stopped or failed
                if is_translation_stopped():
                    self.progress_text.configure(text="Đã dừng - có thể tiếp tục")
                    self.translate_btn.configure(
                        text="▶️ Tiếp Tục Dịch",
                        fg_color=("blue", "darkblue"),
                        hover_color=("darkblue", "blue")
                    )
                else:
                    self.progress_text.configure(text="Sẵn sàng")
        
        # Clear translation thread reference
        if hasattr(self, 'translation_thread'):
            self.translation_thread = None
    
    def convert_to_epub(self, txt_file):
        """Convert file to EPUB"""
        if not EPUB_AVAILABLE:
            self.log("❌ Không thể convert EPUB - thiếu module ConvertEpub")
            return
        
        try:
            # Generate file paths
            base_name = os.path.splitext(txt_file)[0]
            docx_file = base_name + ".docx"
            epub_file = base_name + ".epub"
            
            # Get book info
            title = self.book_title_var.get() or os.path.splitext(os.path.basename(txt_file))[0]
            author = self.book_author_var.get() or "Unknown Author"
            pattern = self.get_chapter_pattern()
            
            # Convert TXT to DOCX
            self.log("📄 Đang convert TXT → DOCX...")
            if txt_to_docx(txt_file, docx_file, title, pattern):
                self.log("✅ Convert TXT → DOCX hoàn thành!")
                
                # Convert DOCX to EPUB
                self.log("📚 Đang convert DOCX → EPUB...")
                if docx_to_epub(docx_file, epub_file, title, author):
                    self.log(f"✅ Convert EPUB hoàn thành: {epub_file}")
                else:
                    self.log("❌ Convert DOCX → EPUB thất bại")
            else:
                self.log("❌ Convert TXT → DOCX thất bại")
                
        except Exception as e:
            self.log(f"❌ Lỗi convert EPUB: {e}")
    
    def save_settings(self):
        """Lưu cài đặt"""
        custom_prompt = ""
        if hasattr(self, 'custom_prompt_textbox'):
            custom_prompt = self.custom_prompt_textbox.get("0.0", "end").strip()
        
        # Get Google AI keys from textbox
        google_ai_keys = []
        if hasattr(self, 'google_ai_keys_textbox'):
            keys_text = self.google_ai_keys_textbox.get("0.0", "end").strip()
            if keys_text:
                for line in keys_text.split('\n'):
                    key = line.strip()
                    if key and not key.startswith('#'):
                        google_ai_keys.append(key)
            
        settings = {
            # API Settings
            "api_provider": self.api_provider_var.get(),
            "openrouter_key": self.openrouter_key_var.get(),
            "google_ai_keys": google_ai_keys,  # New: list of keys
            "google_ai_paid_key": self.google_ai_paid_key_var.get(),
            "google_key_usage": self.google_key_usage_var.get(),
            "google_ai_key": self.google_ai_key_var.get() if hasattr(self, 'google_ai_key_var') else "",  # Deprecated, giữ lại để tương thích
            "api_key": self.api_key_var.get(),  # Deprecated, giữ lại để tương thích
            "model": self.model_var.get(),
            "custom_model": self.custom_model_entry.get() if hasattr(self, 'custom_model_entry') else "",
            "context": self.context_var.get(),
            "custom_prompt": custom_prompt,
            "auto_reformat": self.auto_reformat_var.get(),
            "auto_convert_epub": self.auto_convert_epub_var.get(),
            "book_author": self.book_author_var.get(),
            "chapter_pattern": self.chapter_pattern_var.get(),
            "custom_chapter_pattern": self.custom_chapter_pattern_var.get(),
            "threads": self.threads_var.get(),
            "chunk_size": self.chunk_size_var.get()
        }
        
        try:
            with open("settings.json", "w", encoding="utf-8") as f:
                json.dump(settings, f, indent=2, ensure_ascii=False)
            self.log("💾 Đã lưu cài đặt")
            show_success("Đã lưu cài đặt!", parent=self)
        except Exception as e:
            self.log(f"❌ Lỗi lưu cài đặt: {e}")
            show_error(f"Lỗi lưu cài đặt: {e}", parent=self)
    
    def load_settings(self):
        """Tải cài đặt"""
        try:
            if os.path.exists("settings.json"):
                with open("settings.json", "r", encoding="utf-8") as f:
                    settings = json.load(f)
                
                # Load API settings
                self.api_provider_var.set(settings.get("api_provider", "OpenRouter"))
                self.openrouter_key_var.set(settings.get("openrouter_key", ""))
                
                # Load Google AI keys (new format: list)
                google_ai_keys = settings.get("google_ai_keys", [])
                if google_ai_keys and isinstance(google_ai_keys, list):
                    # Load multiple keys into textbox
                    if hasattr(self, 'google_ai_keys_textbox'):
                        self.google_ai_keys_textbox.delete("0.0", "end")
                        self.google_ai_keys_textbox.insert("0.0", '\n'.join(google_ai_keys))
                else:
                    # Backward compatibility: load single key if old format
                    old_key = settings.get("google_ai_key", "")
                    if old_key and hasattr(self, 'google_ai_keys_textbox'):
                        self.google_ai_keys_textbox.delete("0.0", "end")
                        self.google_ai_keys_textbox.insert("0.0", old_key)
                
                self.google_ai_paid_key_var.set(settings.get("google_ai_paid_key", ""))
                self.google_key_usage_var.set(settings.get("google_key_usage", "Free Keys"))
                
                # Backward compatibility: nếu có api_key cũ, dùng nó cho OpenRouter
                if not self.openrouter_key_var.get() and settings.get("api_key"):
                    self.openrouter_key_var.set(settings.get("api_key", ""))
                
                self.api_key_var.set(settings.get("api_key", ""))  # Deprecated
                self.model_var.set(settings.get("model", "anthropic/claude-3.5-sonnet"))
                
                # Load custom model if exists
                if hasattr(self, 'custom_model_entry') and settings.get("custom_model"):
                    self.custom_model_entry.insert(0, settings.get("custom_model"))
                
                self.context_var.set(settings.get("context", "Bối cảnh hiện đại"))
                self.auto_reformat_var.set(settings.get("auto_reformat", True))
                self.auto_convert_epub_var.set(settings.get("auto_convert_epub", False))
                self.book_author_var.set(settings.get("book_author", "Unknown Author"))
                self.chapter_pattern_var.set(settings.get("chapter_pattern", "Chương XX:"))
                self.custom_chapter_pattern_var.set(settings.get("custom_chapter_pattern", r"^Chương\s+\d+:\s+.*$"))
                
                # Load threads - nếu không có trong settings thì auto-detect
                threads_setting = settings.get("threads")
                if threads_setting:
                    self.threads_var.set(threads_setting)
                else:
                    self.auto_detect_threads(silent=True)
                    
                self.chunk_size_var.set(settings.get("chunk_size", "100"))
                
                # Load custom prompt if exists
                if hasattr(self, 'custom_prompt_textbox') and settings.get("custom_prompt"):
                    self.custom_prompt_textbox.delete("0.0", "end")
                    self.custom_prompt_textbox.insert("0.0", settings.get("custom_prompt"))
                
                # Trigger context change to show/hide custom prompt
                self.on_context_changed(self.context_var.get())
                
                # Trigger chapter pattern change to show/hide custom pattern
                self.on_chapter_pattern_changed(self.chapter_pattern_var.get())
                
                # Trigger EPUB setting change to show/hide EPUB frame
                self.on_epub_setting_changed()
                
                # Trigger API provider change to show/hide API key fields
                self.on_api_provider_changed(self.api_provider_var.get())
                self.on_google_key_type_changed(self.google_key_usage_var.get())
                
                self.log("📂 Đã tải cài đặt")
        except Exception as e:
            self.log(f"⚠️ Lỗi tải cài đặt: {e}")
    
    def change_appearance_mode_event(self, new_appearance_mode: str):
        """Thay đổi appearance mode"""
        ctk.set_appearance_mode(new_appearance_mode)
    
    def on_closing(self):
        """Xử lý khi đóng cửa sổ"""
        try:
            if self.is_translating:
                result = show_question("Đang dịch. Bạn có chắc muốn thoát?\n\nTiến độ sẽ được lưu để tiếp tục sau.", parent=self)
                if result:
                    # Dừng tiến trình dịch
                    set_stop_translation()
                    self.log("🛑 Dừng tiến trình dịch do đóng app...")
                    
                    # Đợi một chút để translation threads có thể dừng
                    time.sleep(0.5)
                    
                    self.cleanup_and_exit()
                else:
                    return  # Không đóng app
            else:
                self.cleanup_and_exit()
        except Exception as e:
            print(f"Lỗi khi đóng: {e}")
            # Force exit
            self.destroy()
    
    def cleanup_and_exit(self):
        """Cleanup và thoát an toàn"""
        try:
            # Restore stdout
            self.restore_stdout()
            
            # Cancel any running threads
            if hasattr(self, 'translation_thread') and self.translation_thread:
                # Note: Can't force stop threads, just set flag
                self.is_translating = False
            
            # Clear any pending after calls
            self.after_cancel("all")
            
        except Exception as e:
            print(f"Lỗi cleanup: {e}")
        finally:
            # Force destroy
            self.destroy()

    def on_epub_setting_changed(self):
        """Xử lý khi thay đổi cài đặt auto convert EPUB"""
        if self.auto_convert_epub_var.get():
            self.epub_frame.grid(row=2, column=0, sticky="ew", padx=20, pady=10)
        else:
            self.epub_frame.grid_remove()
    
    def on_chapter_pattern_changed(self, choice):
        """Xử lý khi thay đổi chapter pattern"""
        pattern_map = {
            "Chương XX:": r"^Chương\s+\d+:\s+.*$",
            "Chương XX": r"^Chương\s+\d+(?:\s+.*)?$",
            "XXX": r"^\d{3}(?:\s+.*)?$",
            "XXX:": r"^\d{3}:\s+.*$",
            "Phần X:": r"^Phần\s+\d+:\s+.*$",
            "Phần X": r"^Phần\s+\d+(?:\s+.*)?$",
            "Chapter X:": r"^Chapter\s+\d+:\s+.*$",
            "Chapter X": r"^Chapter\s+\d+(?:\s+.*)?$",
            "第X章": r"^第\d+章(?:\s+.*)?$",
            "第X章:": r"^第\d+章:\s+.*$"
        }
        
        if choice == "Tùy chỉnh":
            self.custom_pattern_frame.grid(row=5, column=0, sticky="ew", padx=0, pady=0)
        else:
            self.custom_pattern_frame.grid_remove()
            # Cập nhật pattern tương ứng
            if choice in pattern_map:
                self.custom_chapter_pattern_var.set(pattern_map[choice])
    
    def get_current_api_key(self):
        """
        Lấy API key(s) hiện tại dựa trên provider đã chọn.
        - OpenRouter: trả về string (1 key)
        - Google AI: trả về list (free keys) hoặc string (paid key)
        """
        provider = self.api_provider_var.get()
        if provider == "OpenRouter":
            return self.openrouter_key_var.get().strip()
        elif provider == "Google AI":
            key_type = self.google_key_usage_var.get()
            if key_type == "Paid Key":
                return self.google_ai_paid_key_var.get().strip()
            else: # Free Keys
            # Get all keys from textbox
            keys_text = self.google_ai_keys_textbox.get("0.0", "end").strip()
            if not keys_text:
                return []
            
            # Parse keys (1 key per line)
            keys = []
            for line in keys_text.split('\n'):
                key = line.strip()
                if key and not key.startswith('#'):  # Skip empty lines and comments
                    keys.append(key)
            
            return keys if keys else []
        return ""
    
    def get_current_provider(self):
        """Lấy provider hiện tại"""
        return self.api_provider_var.get()
    
    def get_current_model(self):
        """Lấy model hiện tại (có thể là custom model)"""
        current_model = self.model_var.get()
        if current_model == "🔧 Custom Model...":
            # If custom model is selected but not confirmed yet, return the entry value
            if hasattr(self, 'custom_model_entry'):
                custom_model = self.custom_model_entry.get().strip()
                if custom_model:
                    return custom_model
            # Fallback to default based on provider
            provider = self.get_current_provider()
            if provider == "Google AI":
                return "gemini-2.5-flash"
            else:
                return "anthropic/claude-3.5-sonnet"
        return current_model
    
    def get_chapter_pattern(self):
        """Lấy chapter pattern hiện tại"""
        if self.chapter_pattern_var.get() == "Tùy chỉnh":
            return self.custom_chapter_pattern_var.get()
        else:
            pattern_map = {
                "Chương XX:": r"^Chương\s+\d+:\s+.*$",
                "Chương XX": r"^Chương\s+\d+(?:\s+.*)?$",
                "XXX": r"^\d{3}(?:\s+.*)?$",
                "XXX:": r"^\d{3}:\s+.*$",
                "Phần X:": r"^Phần\s+\d+:\s+.*$",
                "Phần X": r"^Phần\s+\d+(?:\s+.*)?$",
                "Chapter X:": r"^Chapter\s+\d+:\s+.*$",
                "Chapter X": r"^Chapter\s+\d+(?:\s+.*)?$",
                "第X章": r"^第\d+章(?:\s+.*)?$",
                "第X章:": r"^第\d+章:\s+.*$"
            }
            return pattern_map.get(self.chapter_pattern_var.get(), r"^Chương\s+\d+:\s+.*$")

    def run_translation(self, input_file, output_file, api_key, model_name, system_instruction, num_threads, chunk_size, provider="OpenRouter", is_paid_key=False):
        """Chạy quá trình dịch"""
        try:
            self.start_time = time.time()
            
            # Log provider being used
            self.log(f"🔑 Sử dụng {provider} API")
            
            # Xác định context từ GUI settings
            context_setting = self.context_var.get()
            if context_setting == "Bối cảnh cổ đại":
                context = "ancient"
            else:
                context = "modern"  # Default cho "Bối cảnh hiện đại" và "Tùy chỉnh"
            
            self.log(f"🎯 Context: {context_setting} → {'ta' if context == 'ancient' else 'tôi'}")
            
            # Use regular translation
            success = translate_file_optimized(
                input_file=input_file,
                output_file=output_file,
                api_key=api_key,
                model_name=model_name,
                system_instruction=system_instruction,
                num_workers=num_threads,
                chunk_size_lines=chunk_size,
                provider=provider,
                context=context,