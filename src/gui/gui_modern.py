# -*- coding: utf-8 -*-
import os
import sys

# Set console encoding to UTF-8 for Windows
if sys.platform.startswith('win'):
    try:
        # Try to set console to UTF-8
        os.system('chcp 65001 > nul')
    except:
        pass

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
    from ..core.translate import translate_file_optimized, generate_output_filename, set_stop_translation, clear_stop_translation, is_translation_stopped, is_quota_exceeded, validate_api_key_before_translation
    from ..core.reformat import fix_text_format
    from ..core.ConvertEpub import txt_to_docx, docx_to_epub
    TRANSLATE_AVAILABLE = True
    EPUB_AVAILABLE = True
except ImportError:
    # Try absolute imports (when run directly)
    try:
        # Import OpenRouter translate functions instead of original translate
        from core.translate import translate_file_optimized, generate_output_filename, set_stop_translation, clear_stop_translation, is_translation_stopped, is_quota_exceeded, validate_api_key_before_translation
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
            
        def validate_api_key_before_translation(*args, **kwargs):
            print("❌ Chức năng test API không khả dụng")
            return False, "Module dịch không khả dụng"
            
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
        
        # Saved custom models list
        self.saved_custom_models = []
        
        # Model settings storage
        self.model_settings = {}
        
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
        
        # --- Model Selection ---
        self.model_frame = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent")
        self.model_frame.grid(row=10, column=0, padx=20, pady=5, sticky="ew")
        self.model_frame.grid_columnconfigure(0, weight=1)
        
        self.model_combo = ctk.CTkComboBox(
            self.model_frame,
            values=[], # Will be populated by _update_model_list
            variable=self.model_var
        )
        self.model_combo.grid(row=0, column=0, sticky="ew")

        # Button frame for + and settings buttons
        self.model_buttons_frame = ctk.CTkFrame(self.model_frame, fg_color="transparent")
        self.model_buttons_frame.grid(row=0, column=1, padx=(5, 0))
        
        self.add_model_btn = ctk.CTkButton(
            self.model_buttons_frame,
            text="➕",
            command=self.open_add_model_dialog,
            width=30,
            height=28
        )
        self.add_model_btn.grid(row=0, column=0, padx=(0, 2))

        self.model_settings_btn = ctk.CTkButton(
            self.model_buttons_frame,
            text="⚙️",
            command=self.open_model_settings,
            width=30,
            height=28
        )
        self.model_settings_btn.grid(row=0, column=1)
        
        
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
        
        # Auto-detect button
        self.auto_threads_btn = ctk.CTkButton(
            self.threads_frame,
            text="🔧",
            command=self.auto_detect_threads,
            width=25,
            height=28,
            font=ctk.CTkFont(size=10)
        )
        self.auto_threads_btn.grid(row=0, column=2, padx=(2, 0))
        
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
            placeholder_text="10-2000",
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
            
            self.log("🔄 Chuyển sang OpenRouter API")
            
        elif choice == "Google AI":
            # Hide OpenRouter key, show Google AI keys
            self.openrouter_key_entry.grid_remove()
            self.google_key_type_segmented_btn.grid()
            self.on_google_key_type_changed() # Show correct entry based on selector's current value
            
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
    
        # Update model list for the new provider
        self._update_model_list()

    def _update_model_list(self):
        """Cập nhật danh sách model trong combobox dựa trên provider và các model đã lưu."""
        provider = self.api_provider_var.get()
        
        if provider == "OpenRouter":
            base_models = [
                "anthropic/claude-3.5-sonnet",
                "openai/gpt-4o-mini",
                "google/gemini-2.0-flash-001",
                "google/gemini-1.5-pro"
            ]
        elif provider == "Google AI":
            base_models = [
                "gemini-2.5-pro",
                "gemini-2.5-flash",
                "gemini-2.5-flash-lite",
                "gemini-2.0-flash",
                "gemini-2.0-flash-lite",
                "gemini-1.5-pro",
                "gemini-1.5-flash"
            ]
        else:
            base_models = []

        # Combine base models with saved custom models
        combined_models = base_models + sorted(self.saved_custom_models)
        
        self.model_combo.configure(values=combined_models)
        
        # Check if the current model is still valid, if not, set a default
        current_model = self.model_var.get()
        if current_model not in combined_models:
            self.model_var.set(base_models[0] if base_models else "anthropic/claude-3.5-sonnet")
    
    
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
            default_custom = """NHIỆM VỤ: Dịch văn bản sang tiếng Việt hiện đại, tự nhiên.

QUY TẮC QUAN TRỌNG:
1. VĂN PHONG: Dịch như người Việt nói chuyện hàng ngày, tránh từ Hán Việt cứng nhắc
2. NGƯỜI KỂ CHUYỆN: Luôn xưng "tôi" (hiện đại) hoặc "ta" (cổ đại). TUYỆT ĐỐI KHÔNG dùng "ba/bố/anh/chị/em/con"
3. LỜI THOẠI: Đặt trong dấu ngoặc kép "...", xưng hô tự nhiên theo quan hệ nhân vật
4. TỪNG NGỮ HIỆN ĐẠI: "Cảm thấy" thay vì "cảm nhận", "Anh ấy/Cô ấy" thay vì "Hắn/Nàng"

⚠️ QUAN TRỌNG: CHỈ TRẢ VỀ BẢN DỊCH, KHÔNG GIẢI THÍCH GÌ THÊM!

Văn bản cần dịch:"""
            self.custom_prompt_textbox.delete("0.0", "end")
            self.custom_prompt_textbox.insert("0.0", default_custom)
        else:
            self.custom_prompt_frame.grid_remove()
    
    def get_system_instruction(self):
        """Tạo system instruction dựa trên bối cảnh đã chọn"""
        context = self.context_var.get()
        
        base_instruction = """NHIỆM VỤ: Dịch văn bản sang tiếng Việt hiện đại, tự nhiên.

QUY TẮC QUAN TRỌNG:
1. VĂN PHONG: Dịch như người Việt nói chuyện hàng ngày, tránh từ Hán Việt cứng nhắc
2. NGƯỜI KỂ CHUYỆN: Luôn xưng "tôi" (hiện đại) hoặc "ta" (cổ đại). TUYỆT ĐỐI KHÔNG dùng "ba/bố/anh/chị/em/con"
3. LỜI THOẠI: Đặt trong dấu ngoặc kép "...", xưng hô tự nhiên theo quan hệ nhân vật
4. TỪNG NGỮ HIỆN ĐẠI: "Cảm thấy" thay vì "cảm nhận", "Anh ấy/Cô ấy" thay vì "Hắn/Nàng"

⚠️ QUAN TRỌNG: CHỈ TRẢ VỀ BẢN DỊCH, KHÔNG GIẢI THÍCH GÌ THÊM!

Văn bản cần dịch:"""
        
        context_instructions = {
            "Bối cảnh hiện đại": f"""{base_instruction}

BỔ SUNG CHO HIỆN ĐẠI:
- Xưng hô lời thoại: "mình/bạn", "tao/mày", "anh/chị/em" tùy quan hệ
- Tránh từ cũ: "Hắn"→"Anh ấy", "Nàng"→"Cô ấy", "Thân thể"→"Cơ thể"  
- Giữ từ lóng, slang nếu có trong gốc

CHỈ TRẢ VỀ BẢN DỊCH!""",

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
                self.progress_bar.set(0)  # Reset progress bar
    
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
        """Tự động phát hiện số threads tối ưu cho máy và provider"""
        try:
            # Import hàm get_optimal_threads từ translate module
            try:
                from ..core.translate import get_optimal_threads
            except ImportError:
                from core.translate import get_optimal_threads
            
            # Lấy thông tin provider và API keys
            provider = self.get_current_provider()
            model_name = self.model_var.get()
            api_key = self.get_current_api_key()
            
            # Tính số lượng API keys
            if provider == "Google AI" and isinstance(api_key, list):
                num_api_keys = len(api_key)
            else:
                num_api_keys = 1
            
            # Tính toán threads tối ưu dựa trên provider và số keys
            optimal_threads = get_optimal_threads(num_api_keys=num_api_keys, provider=provider)
            
            self.threads_var.set(str(optimal_threads))
            
            if not silent:
                if num_api_keys > 1:
                    message = f"Đã đặt threads tối ưu: {optimal_threads}\n(Provider: {provider}, {num_api_keys} API keys)"
                    message += f"\n\n💡 TIP: Với {num_api_keys} keys, hệ thống có thể chạy {optimal_threads} threads đồng thời để tối ưu tốc độ!"
                else:
                    message = f"Đã đặt threads tối ưu: {optimal_threads}\n(Provider: {provider}, Model: {model_name})"
                
                show_success(message, parent=self)
                
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
            
            # Detect adaptive scaling messages và thêm formatting đặc biệt
            if "SCALE DOWN" in message or "SCALE UP" in message:
                log_message = f"[{timestamp}] 🎯 {message}"
            elif "Thread Manager Stats" in message:
                log_message = f"[{timestamp}] 📊 {message}"
            elif "Khởi động thread pool" in message:
                log_message = f"[{timestamp}] 🔧 {message}"
            elif "Adaptive scaling" in message:
                log_message = f"[{timestamp}] 🔄 {message}"
            else:
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
            
            # Safe console printing - remove emojis for console
            try:
                console_message = message.encode('ascii', 'ignore').decode('ascii')
                print(console_message)
            except:
                pass  # Skip console printing if encoding fails
        except Exception as e:
            try:
                error_msg = f"Loi log GUI: {str(e)}"
                print(error_msg.encode('ascii', 'ignore').decode('ascii'))
            except:
                pass
    
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
        
        # Kiểm tra API key dựa trên provider hiện tại
        api_key = self.get_current_api_key()
        provider = self.get_current_provider()
        
        if provider == "Google AI":
            if not api_key or (isinstance(api_key, list) and len(api_key) == 0):
                show_error(f"Vui lòng nhập ít nhất 1 Google AI API Key", parent=self)
                return
        else:
            if not api_key or not api_key.strip():
                show_error(f"Vui lòng nhập {provider} API Key", parent=self)
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
            if chunk_size < 10 or chunk_size > 2000:
                show_warning("Chunk size phải từ 10 đến 2000!", parent=self)
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
        
        # Log số lượng keys cho Google AI với recommendations
        if provider == "Google AI" and isinstance(api_key, list):
            num_keys = len(api_key)
            self.log(f"🔑 Số lượng API keys: {num_keys} keys")
            
            base_rpm = 10  # Default RPM per key
            if "pro" in current_model.lower():
                base_rpm = 2
            
            total_rpm = num_keys * base_rpm
            self.log(f"💡 Tổng RPM ước tính: ~{total_rpm} RPM (mỗi key ~{base_rpm} RPM)")
            
            # NEW: Recommendation cho > 5 keys
            if num_keys > 5:
                recommended_threads_min = num_keys * 2
                recommended_threads_max = num_keys * 3
                
                self.log(f"✨ Với {num_keys} keys, khuyến nghị:")
                self.log(f"   📌 Threads: {recommended_threads_min}-{recommended_threads_max} (hiện tại: {num_threads})")
                
                if num_threads < recommended_threads_min:
                    self.log(f"   ⚠️ Threads hiện tại thấp, có thể tăng lên để tăng tốc độ!")
                elif num_threads > recommended_threads_max:
                    self.log(f"   ⚠️ Threads hiện tại cao, có thể gặp rate limit!")
                else:
                    self.log(f"   ✅ Threads trong khoảng tối ưu!")
        
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
            # Kiểm tra xem có file progress không để xác định trạng thái
            progress_file_path = f"{self.input_file_var.get()}.progress.json"
            
            if is_translation_stopped():
                # Dịch bị dừng
                self.translate_btn.configure(
                    state="normal", 
                    text="▶️ Tiếp Tục Dịch",
                    fg_color=("blue", "darkblue"),
                    hover_color=("darkblue", "blue")
                )
                self.progress_text.configure(text="Đã dừng - có thể tiếp tục")
            elif not os.path.exists(progress_file_path):
                # Không có file progress = dịch hoàn thành
                self.translate_btn.configure(
                    state="normal", 
                    text="🚀 Bắt Đầu Dịch",
                    fg_color=("blue", "darkblue"),
                    hover_color=("darkblue", "blue")
                )
                self.progress_text.configure(text="✅ Dịch hoàn thành!")
                self.progress_bar.set(1.0)  # Set progress bar to 100%
                self.log("🎉 Dịch hoàn thành thành công!")
                
                # Tự động convert EPUB nếu user chọn
                if self.auto_convert_epub_var.get():
                    self.log("\n📚 Bắt đầu convert sang EPUB...")
                    output_file = self.output_file_var.get()
                    if output_file and os.path.exists(output_file):
                        try:
                            self.convert_to_epub(output_file)
                        except Exception as e:
                            self.log(f"❌ Lỗi khi convert EPUB: {e}")
                    else:
                        self.log("⚠️ Không tìm thấy file output để convert EPUB")
            else:
                # Có file progress = dịch chưa hoàn thành
                self.translate_btn.configure(
                    state="normal", 
                    text="▶️ Tiếp Tục Dịch",
                    fg_color=("blue", "darkblue"),
                    hover_color=("darkblue", "blue")
                )
                self.progress_text.configure(text="Đã dừng - có thể tiếp tục")
        
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
            "saved_custom_models": self.saved_custom_models, # Save the list of custom models
            "model_settings": self.model_settings, # Save model settings
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
                
                # Load saved custom models
                self.saved_custom_models = settings.get("saved_custom_models", [])
                
                # Load model settings
                self.model_settings = settings.get("model_settings", {})
                
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
        """Lấy model hiện tại"""
        current_model = self.model_var.get()
        if not current_model:
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
                is_paid_key=is_paid_key
            )
            
            # Re-enable UI elements after completion
            self.after(0, self.translation_finished)
            
            # Post-translation actions
            if success and not is_translation_stopped():
                # Xóa file progress khi hoàn thành
                progress_file_path = f"{input_file}.progress.json"
                if os.path.exists(progress_file_path):
                    try:
                        os.remove(progress_file_path)
                        self.log(f"🗑️ Đã xóa file tiến độ khi hoàn thành.")
                    except Exception as e:
                        self.log(f"⚠️ Không thể xóa file tiến độ: {e}")

                # Auto reformat
                if self.auto_reformat_var.get():
                    self.log("🔧 Bắt đầu reformat file đã dịch...")
                    try:
                        fix_text_format(output_file)
                        self.log("✅ Reformat hoàn thành!")
                    except Exception as e:
                        self.log(f"⚠️ Lỗi khi reformat: {e}")
                
                # Auto convert to EPUB
                if self.auto_convert_epub_var.get():
                    self.log("📚 Bắt đầu convert EPUB...")
                    self.convert_to_epub(output_file)
            
        except Exception as e:
            self.log(f"❌ Lỗi nghiêm trọng trong thread dịch: {e}")
            # Ensure UI is re-enabled even on critical error
            self.after(0, self.translation_finished)

    def show_quota_exceeded_dialog(self):
        """Hiển thị dialog khi hết quota"""
        from tkinter import Toplevel, Text, END, Label
        
        dialog = Toplevel(self)
        dialog.title("💳 API Hết Quota")
        dialog.geometry("500x350")
        dialog.transient(self)
        dialog.grab_set()
        dialog.configure(bg=self.cget("bg"))
        
        Label(dialog, text="API Key của bạn đã hết quota.", font=ctk.CTkFont(size=14, weight="bold"), bg=self.cget("bg"), fg="white").pack(pady=(20, 10))
        
        text_content = """Để tiếp tục dịch, vui lòng:
1. Tạo tài khoản Google Cloud mới (nếu chưa có).
2. Nhận 300$ credit miễn phí.
3. Tạo API key mới từ ai.google.dev.
4. Cập nhật API key trong app và tiếp tục dịch.

File tiến độ đã được lưu, bạn có thể tiếp tục dịch ngay sau khi cập nhật key mới.
"""
        
        text_widget = Text(dialog, wrap="word", height=10, width=60, font=("Segoe UI", 10), bg="#2b2b2b", fg="white", relief="flat", padx=10, pady=10)
        text_widget.insert(END, text_content)
        text_widget.config(state="disabled")
        text_widget.pack(pady=10, padx=20)
        
        ok_button = ctk.CTkButton(dialog, text="OK", command=dialog.destroy, width=100)
        ok_button.pack(pady=(10, 20))

    def test_api_connection(self):
        """Test API connection in a separate thread."""
        self.log("🧪 Đang kiểm tra kết nối API...")
        self.test_api_btn.configure(state="disabled", text="🧪 Đang kiểm tra...")

        provider = self.get_current_provider()
        api_key = self.get_current_api_key()
        model = self.get_current_model()
        
        # For Google AI, test all keys if multiple keys are provided
        if provider == "Google AI" and isinstance(api_key, list):
            if not api_key:
                self.log("❌ Vui lòng nhập ít nhất một Google AI API key.")
                show_error("Vui lòng nhập ít nhất một Google AI API key.", parent=self)
                self.test_api_btn.configure(state="normal", text="🧪 Test API")
                return
            
            # Test all keys
            self.log(f"🔍 Sẽ kiểm tra tất cả {len(api_key)} API keys...")
            threading.Thread(target=self._run_multiple_api_test, args=(api_key, model, provider), daemon=True).start()
        else:
            # Single key test
            api_key_to_test = api_key
            if not api_key_to_test:
                provider_name = "OpenRouter" if provider == "OpenRouter" else "Google AI"
                self.log(f"❌ Vui lòng nhập API key cho {provider_name}.")
                show_error(f"Vui lòng nhập API key cho {provider_name}.", parent=self)
                self.test_api_btn.configure(state="normal", text="🧪 Test API")
                return

            threading.Thread(target=self._run_api_test, args=(api_key_to_test, model, provider), daemon=True).start()

    def _run_api_test(self, api_key, model, provider):
        """Worker function to test API."""
        is_valid, message = validate_api_key_before_translation(api_key, model, provider)
        
        def update_ui():
            if is_valid:
                self.log(f"✅ Kết nối API thành công: {message}")
                show_success("Kết nối API thành công!", details=message, parent=self)
            else:
                self.log(f"❌ Lỗi kết nối API: {message}")
                show_error("Kết nối API thất bại!", details=message, parent=self)
            self.test_api_btn.configure(state="normal", text="🧪 Test API")

        self.after(0, update_ui)
    
    def _run_multiple_api_test(self, api_keys, model, provider):
        """Worker function to test multiple API keys."""
        valid_keys = 0
        invalid_keys = 0
        results = []
        
        for i, api_key in enumerate(api_keys, 1):
            self.after(0, lambda idx=i: self.log(f"🧪 Đang test key #{idx}..."))
            
            is_valid, message = validate_api_key_before_translation(api_key, model, provider)
            
            # Mask the key for display
            masked_key = api_key[:8] + "***" + api_key[-4:] if len(api_key) > 12 else "***"
            
            if is_valid:
                valid_keys += 1
                result_msg = f"✅ Key #{i} ({masked_key}): {message}"
                results.append(result_msg)
                self.after(0, lambda msg=result_msg: self.log(msg))
            else:
                invalid_keys += 1
                result_msg = f"❌ Key #{i} ({masked_key}): {message}"
                results.append(result_msg)
                self.after(0, lambda msg=result_msg: self.log(msg))
        
        # Final summary
        def update_final_ui():
            summary = f"📊 Kết quả test: {valid_keys} keys hợp lệ, {invalid_keys} keys lỗi"
            self.log(summary)
            
            if valid_keys > 0:
                details = f"Keys hợp lệ: {valid_keys}/{len(api_keys)}\n\n" + "\n".join(results)
                show_success(f"Test hoàn thành!\n{summary}", details=details, parent=self)
            else:
                details = "Tất cả keys đều lỗi:\n\n" + "\n".join(results)
                show_error(f"Test thất bại!\n{summary}", details=details, parent=self)
            
            self.test_api_btn.configure(state="normal", text="🧪 Test API")
        
        self.after(0, update_final_ui)
    
    def set_light_mode(self):
        """Chuyển sang chế độ sáng"""
        ctk.set_appearance_mode("light")
        self.log("☀️ Đã chuyển sang Light Mode")
        self.update_appearance_buttons()
    
    def set_dark_mode(self):
        """Chuyển sang chế độ tối"""
        ctk.set_appearance_mode("dark")
        self.log("🌙 Đã chuyển sang Dark Mode")
        self.update_appearance_buttons()
    
    def update_appearance_buttons(self):
        """Cập nhật màu sắc của nút appearance mode"""
        try:
            current_mode = ctk.get_appearance_mode()
            
            if current_mode == "Light":
                # Light mode active
                self.light_mode_btn.configure(
                    fg_color=("gray75", "gray25"),
                    text_color=("gray10", "gray90")
                )
                self.dark_mode_btn.configure(
                    fg_color=("gray90", "gray13"),
                    text_color=("gray10", "gray90")
                )
            else:
                # Dark mode active
                self.light_mode_btn.configure(
                    fg_color=("gray90", "gray13"),
                    text_color=("gray10", "gray90")
                )
                self.dark_mode_btn.configure(
                    fg_color=("gray75", "gray25"),
                    text_color=("gray10", "gray90")
                )
        except Exception as e:
            print(f"⚠️ Lỗi cập nhật appearance buttons: {e}")

    def open_add_model_dialog(self):
        """Mở dialog để thêm model mới."""
        
        # Tạo cửa sổ Toplevel
        if hasattr(self, 'add_model_window') and self.add_model_window.winfo_exists():
            self.add_model_window.focus()
            return
        
        self.add_model_window = ctk.CTkToplevel(self)
        self.add_model_window.title("Thêm Model Mới")
        self.add_model_window.geometry("450x300")
        self.add_model_window.transient(self)
        self.add_model_window.grab_set()
        
        self.add_model_window.grid_columnconfigure(0, weight=1)

        # --- Title ---
        title_label = ctk.CTkLabel(self.add_model_window, text="Thêm Model Mới", font=ctk.CTkFont(size=18, weight="bold"))
        title_label.grid(row=0, column=0, padx=20, pady=(20, 10))

        # --- Model Name Entry ---
        model_name_label = ctk.CTkLabel(self.add_model_window, text="Tên Model:", font=ctk.CTkFont(size=12, weight="bold"))
        model_name_label.grid(row=1, column=0, padx=20, pady=(10, 5), sticky="w")
        
        self.add_model_entry = ctk.CTkEntry(
            self.add_model_window,
            placeholder_text="Ví dụ: anthropic/claude-3.5-sonnet",
            width=400
        )
        self.add_model_entry.grid(row=2, column=0, padx=20, pady=5, sticky="ew")
        self.add_model_entry.focus()

        # --- Examples ---
        examples_label = ctk.CTkLabel(
            self.add_model_window, 
            text="Ví dụ các model phổ biến:",
            font=ctk.CTkFont(size=11, weight="bold")
        )
        examples_label.grid(row=3, column=0, padx=20, pady=(15, 5), sticky="w")
        
        examples_text = """• OpenRouter: anthropic/claude-3.5-sonnet, openai/gpt-4o
• Google AI: gemini-2.0-flash-exp, gemini-1.5-pro-002
• Anthropic: claude-3-opus-20240229
• OpenAI: gpt-4-turbo-preview"""
        
        examples_display = ctk.CTkLabel(
            self.add_model_window,
            text=examples_text,
            font=ctk.CTkFont(size=10),
            justify="left"
        )
        examples_display.grid(row=4, column=0, padx=20, pady=5, sticky="w")

        # --- Buttons ---
        button_frame = ctk.CTkFrame(self.add_model_window, fg_color="transparent")
        button_frame.grid(row=5, column=0, padx=20, pady=(20, 20), sticky="ew")
        button_frame.grid_columnconfigure(0, weight=1)
        button_frame.grid_columnconfigure(1, weight=1)

        cancel_btn = ctk.CTkButton(
            button_frame,
            text="Hủy",
            command=self.add_model_window.destroy,
            fg_color="gray",
            hover_color="darkgray"
        )
        cancel_btn.grid(row=0, column=0, padx=(0, 10), sticky="ew")

        add_btn = ctk.CTkButton(
            button_frame,
            text="Thêm Model",
            command=self._confirm_add_model
        )
        add_btn.grid(row=0, column=1, padx=(10, 0), sticky="ew")
        
        # Bind Enter key to add model
        self.add_model_entry.bind("<Return>", lambda e: self._confirm_add_model())

    def _confirm_add_model(self):
        """Xác nhận thêm model mới."""
        model_name = self.add_model_entry.get().strip()
        
        if not model_name:
            show_error("Vui lòng nhập tên model!", parent=self.add_model_window)
            return
        
        # Validate model format for OpenRouter
        provider = self.get_current_provider()
        if provider == "OpenRouter" and '/' not in model_name:
            result = show_question(
                f"Model '{model_name}' không có format chuẩn 'provider/model-name'.\n\n"
                f"Ví dụ format đúng: anthropic/claude-3.5-sonnet\n\n"
                f"Bạn có muốn tiếp tục với model này không?",
                parent=self.add_model_window
            )
            if not result:
                return
        
        # Check if model already exists
        if model_name in self.saved_custom_models:
            show_warning(f"Model '{model_name}' đã tồn tại!", parent=self.add_model_window)
            return
        
        # Add to saved models list
        self.saved_custom_models.append(model_name)
        self.saved_custom_models.sort()
        
        # Initialize default settings for the model
        self.model_settings[model_name] = self._get_default_model_settings()
        
        # Update model list and select the new model
        self._update_model_list()
        self.model_var.set(model_name)
        
        # Close dialog
        self.add_model_window.destroy()
        
        # Log and show success
        self.log(f"➕ Đã thêm model mới: {model_name}")
        show_success(f"Đã thêm model mới:\n{model_name}", parent=self)

    def _get_default_model_settings(self):
        """Lấy cài đặt mặc định cho model mới."""
        return {
            "thinking_mode": False,
            "top_p": 1.0,
            "temperature": 1.0,
            "max_tokens": 4096,
            "frequency_penalty": 0.0,
            "presence_penalty": 0.0,
            "repetition_penalty": 1.0,
            "top_k": 0,
            "min_p": 0.0
        }

    def open_model_settings(self):
        """Mở dialog cài đặt model."""
        current_model = self.get_current_model()
        
        if not current_model:
            show_error("Vui lòng chọn model trước!", parent=self)
            return
        
        # Tạo cửa sổ Toplevel
        if hasattr(self, 'model_settings_window') and self.model_settings_window.winfo_exists():
            self.model_settings_window.focus()
            return
        
        self.model_settings_window = ctk.CTkToplevel(self)
        self.model_settings_window.title(f"Cài Đặt Model: {current_model}")
        self.model_settings_window.geometry("500x600")
        self.model_settings_window.transient(self)
        self.model_settings_window.grab_set()
        
        self.model_settings_window.grid_columnconfigure(0, weight=1)
        self.model_settings_window.grid_rowconfigure(1, weight=1)

        # --- Title ---
        title_label = ctk.CTkLabel(
            self.model_settings_window, 
            text=f"Cài Đặt Model: {current_model}", 
            font=ctk.CTkFont(size=16, weight="bold")
        )
        title_label.grid(row=0, column=0, padx=20, pady=(20, 10))

        # --- Scrollable Frame ---
        settings_frame = ctk.CTkScrollableFrame(self.model_settings_window)
        settings_frame.grid(row=1, column=0, padx=20, pady=10, sticky="nsew")
        settings_frame.grid_columnconfigure(1, weight=1)

        # Get current settings or defaults
        current_settings = self.model_settings.get(current_model, self._get_default_model_settings())
        
        # Store references to entry widgets
        self.settings_widgets = {}
        
        row = 0
        
        # Thinking Mode (checkbox)
        thinking_label = ctk.CTkLabel(settings_frame, text="Thinking Mode:", font=ctk.CTkFont(weight="bold"))
        thinking_label.grid(row=row, column=0, padx=10, pady=5, sticky="w")
        
        self.settings_widgets["thinking_mode"] = ctk.CTkCheckBox(
            settings_frame,
            text="Bật chế độ suy nghĩ (o1 models)",
            variable=ctk.BooleanVar(value=current_settings.get("thinking_mode", False))
        )
        self.settings_widgets["thinking_mode"].grid(row=row, column=1, padx=10, pady=5, sticky="w")
        row += 1

        # Temperature
        temp_label = ctk.CTkLabel(settings_frame, text="Temperature:", font=ctk.CTkFont(weight="bold"))
        temp_label.grid(row=row, column=0, padx=10, pady=5, sticky="w")
        
        self.settings_widgets["temperature"] = ctk.CTkEntry(
            settings_frame,
            placeholder_text="0.0 - 2.0",
            width=200
        )
        self.settings_widgets["temperature"].insert(0, str(current_settings.get("temperature", 1.0)))
        self.settings_widgets["temperature"].grid(row=row, column=1, padx=10, pady=5, sticky="w")
        row += 1

        # Top P
        top_p_label = ctk.CTkLabel(settings_frame, text="Top P:", font=ctk.CTkFont(weight="bold"))
        top_p_label.grid(row=row, column=0, padx=10, pady=5, sticky="w")
        
        self.settings_widgets["top_p"] = ctk.CTkEntry(
            settings_frame,
            placeholder_text="0.0 - 1.0",
            width=200
        )
        self.settings_widgets["top_p"].insert(0, str(current_settings.get("top_p", 1.0)))
        self.settings_widgets["top_p"].grid(row=row, column=1, padx=10, pady=5, sticky="w")
        row += 1

        # Max Tokens
        max_tokens_label = ctk.CTkLabel(settings_frame, text="Max Tokens:", font=ctk.CTkFont(weight="bold"))
        max_tokens_label.grid(row=row, column=0, padx=10, pady=5, sticky="w")
        
        self.settings_widgets["max_tokens"] = ctk.CTkEntry(
            settings_frame,
            placeholder_text="1 - 32768",
            width=200
        )
        self.settings_widgets["max_tokens"].insert(0, str(current_settings.get("max_tokens", 4096)))
        self.settings_widgets["max_tokens"].grid(row=row, column=1, padx=10, pady=5, sticky="w")
        row += 1

        # Frequency Penalty
        freq_penalty_label = ctk.CTkLabel(settings_frame, text="Frequency Penalty:", font=ctk.CTkFont(weight="bold"))
        freq_penalty_label.grid(row=row, column=0, padx=10, pady=5, sticky="w")
        
        self.settings_widgets["frequency_penalty"] = ctk.CTkEntry(
            settings_frame,
            placeholder_text="-2.0 - 2.0",
            width=200
        )
        self.settings_widgets["frequency_penalty"].insert(0, str(current_settings.get("frequency_penalty", 0.0)))
        self.settings_widgets["frequency_penalty"].grid(row=row, column=1, padx=10, pady=5, sticky="w")
        row += 1

        # Presence Penalty
        pres_penalty_label = ctk.CTkLabel(settings_frame, text="Presence Penalty:", font=ctk.CTkFont(weight="bold"))
        pres_penalty_label.grid(row=row, column=0, padx=10, pady=5, sticky="w")
        
        self.settings_widgets["presence_penalty"] = ctk.CTkEntry(
            settings_frame,
            placeholder_text="-2.0 - 2.0",
            width=200
        )
        self.settings_widgets["presence_penalty"].insert(0, str(current_settings.get("presence_penalty", 0.0)))
        self.settings_widgets["presence_penalty"].grid(row=row, column=1, padx=10, pady=5, sticky="w")
        row += 1

        # Repetition Penalty
        rep_penalty_label = ctk.CTkLabel(settings_frame, text="Repetition Penalty:", font=ctk.CTkFont(weight="bold"))
        rep_penalty_label.grid(row=row, column=0, padx=10, pady=5, sticky="w")
        
        self.settings_widgets["repetition_penalty"] = ctk.CTkEntry(
            settings_frame,
            placeholder_text="0.0 - 2.0",
            width=200
        )
        self.settings_widgets["repetition_penalty"].insert(0, str(current_settings.get("repetition_penalty", 1.0)))
        self.settings_widgets["repetition_penalty"].grid(row=row, column=1, padx=10, pady=5, sticky="w")
        row += 1

        # Top K
        top_k_label = ctk.CTkLabel(settings_frame, text="Top K:", font=ctk.CTkFont(weight="bold"))
        top_k_label.grid(row=row, column=0, padx=10, pady=5, sticky="w")
        
        self.settings_widgets["top_k"] = ctk.CTkEntry(
            settings_frame,
            placeholder_text="0 - 100",
            width=200
        )
        self.settings_widgets["top_k"].insert(0, str(current_settings.get("top_k", 0)))
        self.settings_widgets["top_k"].grid(row=row, column=1, padx=10, pady=5, sticky="w")
        row += 1

        # Min P
        min_p_label = ctk.CTkLabel(settings_frame, text="Min P:", font=ctk.CTkFont(weight="bold"))
        min_p_label.grid(row=row, column=0, padx=10, pady=5, sticky="w")
        
        self.settings_widgets["min_p"] = ctk.CTkEntry(
            settings_frame,
            placeholder_text="0.0 - 1.0",
            width=200
        )
        self.settings_widgets["min_p"].insert(0, str(current_settings.get("min_p", 0.0)))
        self.settings_widgets["min_p"].grid(row=row, column=1, padx=10, pady=5, sticky="w")
        row += 1

        # --- Buttons ---
        button_frame = ctk.CTkFrame(self.model_settings_window, fg_color="transparent")
        button_frame.grid(row=2, column=0, padx=20, pady=(10, 20), sticky="ew")
        button_frame.grid_columnconfigure(0, weight=1)
        button_frame.grid_columnconfigure(1, weight=1)
        button_frame.grid_columnconfigure(2, weight=1)

        reset_btn = ctk.CTkButton(
            button_frame,
            text="Reset",
            command=lambda: self._reset_model_settings(current_model),
            fg_color="orange",
            hover_color="darkorange"
        )
        reset_btn.grid(row=0, column=0, padx=(0, 5), sticky="ew")

        cancel_btn = ctk.CTkButton(
            button_frame,
            text="Hủy",
            command=self.model_settings_window.destroy,
            fg_color="gray",
            hover_color="darkgray"
        )
        cancel_btn.grid(row=0, column=1, padx=5, sticky="ew")

        save_btn = ctk.CTkButton(
            button_frame,
            text="Lưu",
            command=lambda: self._save_model_settings(current_model)
        )
        save_btn.grid(row=0, column=2, padx=(5, 0), sticky="ew")

    def _reset_model_settings(self, model_name):
        """Reset cài đặt model về mặc định."""
        default_settings = self._get_default_model_settings()
        
        # Update widgets
        self.settings_widgets["thinking_mode"].deselect() if not default_settings["thinking_mode"] else self.settings_widgets["thinking_mode"].select()
        
        for key, widget in self.settings_widgets.items():
            if key != "thinking_mode":  # Skip checkbox
                widget.delete(0, "end")
                widget.insert(0, str(default_settings[key]))
        
        self.log(f"🔄 Đã reset cài đặt model {model_name} về mặc định")

    def _save_model_settings(self, model_name):
        """Lưu cài đặt model."""
        try:
            settings = {}
            
            # Get thinking mode
            settings["thinking_mode"] = self.settings_widgets["thinking_mode"].get()
            
            # Get numeric values
            numeric_fields = ["temperature", "top_p", "frequency_penalty", "presence_penalty", "repetition_penalty", "min_p"]
            integer_fields = ["max_tokens", "top_k"]
            
            for field in numeric_fields:
                try:
                    value = float(self.settings_widgets[field].get())
                    settings[field] = value
                except ValueError:
                    show_error(f"Giá trị '{field}' không hợp lệ!", parent=self.model_settings_window)
                    return
            
            for field in integer_fields:
                try:
                    value = int(self.settings_widgets[field].get())
                    settings[field] = value
                except ValueError:
                    show_error(f"Giá trị '{field}' phải là số nguyên!", parent=self.model_settings_window)
                    return
            
            # Validate ranges
            if not (0.0 <= settings["temperature"] <= 2.0):
                show_error("Temperature phải từ 0.0 đến 2.0!", parent=self.model_settings_window)
                return
            
            if not (0.0 <= settings["top_p"] <= 1.0):
                show_error("Top P phải từ 0.0 đến 1.0!", parent=self.model_settings_window)
                return
            
            if not (1 <= settings["max_tokens"] <= 32768):
                show_error("Max Tokens phải từ 1 đến 32768!", parent=self.model_settings_window)
                return
            
            # Save settings
            self.model_settings[model_name] = settings
            
            # Close dialog
            self.model_settings_window.destroy()
            
            # Log and show success
            self.log(f"💾 Đã lưu cài đặt cho model: {model_name}")
            show_success(f"Đã lưu cài đặt cho model:\n{model_name}", parent=self)
            
        except Exception as e:
            show_error(f"Lỗi lưu cài đặt: {e}", parent=self.model_settings_window)

    def open_model_manager(self):
        """Mở dialog quản lý custom model."""
        
        # Tạo cửa sổ Toplevel
        if hasattr(self, 'model_manager_window') and self.model_manager_window.winfo_exists():
            self.model_manager_window.focus()
            return
        
        self.model_manager_window = ctk.CTkToplevel(self)
        self.model_manager_window.title("Quản lý Model Tùy Chỉnh")
        self.model_manager_window.geometry("600x500")
        self.model_manager_window.transient(self)
        self.model_manager_window.grab_set()
        
        self.model_manager_window.grid_columnconfigure(0, weight=1)
        self.model_manager_window.grid_rowconfigure(1, weight=1)

        # --- Label ---
        label = ctk.CTkLabel(self.model_manager_window, text="Danh sách Model Đã Lưu", font=ctk.CTkFont(size=16, weight="bold"))
        label.grid(row=0, column=0, padx=20, pady=(20, 10))

        # --- Scrollable Frame for models ---
        self.model_list_frame = ctk.CTkScrollableFrame(self.model_manager_window)
        self.model_list_frame.grid(row=1, column=0, padx=20, pady=10, sticky="nsew")
        self.model_list_frame.grid_columnconfigure(0, weight=1)

        # --- Populate models ---
        self._populate_model_manager()

        # --- Close button ---
        close_button = ctk.CTkButton(self.model_manager_window, text="Đóng", command=self.model_manager_window.destroy)
        close_button.grid(row=2, column=0, padx=20, pady=(10, 20))

    def _populate_model_manager(self):
        """Xóa và điền lại danh sách model trong cửa sổ quản lý."""
        # Clear existing widgets
        for widget in self.model_list_frame.winfo_children():
            widget.destroy()

        if not self.saved_custom_models:
            no_models_label = ctk.CTkLabel(self.model_list_frame, text="Chưa có model tùy chỉnh nào được lưu.")
            no_models_label.pack(pady=20)
            return

        # Add models to the list
        for i, model_name in enumerate(sorted(self.saved_custom_models)):
            row_frame = ctk.CTkFrame(self.model_list_frame, fg_color="transparent")
            row_frame.grid(row=i, column=0, pady=(5, 0), sticky="ew")
            row_frame.grid_columnconfigure(0, weight=1)

            model_label = ctk.CTkLabel(row_frame, text=model_name, anchor="w", font=ctk.CTkFont(weight="bold"))
            model_label.grid(row=0, column=0, padx=10, sticky="w")
            
            # Show settings info
            settings = self.model_settings.get(model_name, {})
            settings_info = f"T:{settings.get('temperature', 1.0)} | P:{settings.get('top_p', 1.0)} | Max:{settings.get('max_tokens', 4096)}"
            if settings.get('thinking_mode', False):
                settings_info = "🧠 " + settings_info
            
            settings_label = ctk.CTkLabel(row_frame, text=settings_info, anchor="w", font=ctk.CTkFont(size=10), text_color="gray")
            settings_label.grid(row=1, column=0, padx=10, sticky="w")
            
            # Button frame
            btn_frame = ctk.CTkFrame(row_frame, fg_color="transparent")
            btn_frame.grid(row=0, column=1, rowspan=2, padx=10)
            
            settings_btn = ctk.CTkButton(
                btn_frame,
                text="⚙️",
                command=lambda m=model_name: self._edit_model_settings(m),
                width=30,
                height=25,
                fg_color="transparent",
                border_color=("gray70", "gray30"),
                border_width=1,
                hover_color=("blue", "#0066cc")
            )
            settings_btn.grid(row=0, column=0, padx=(0, 5))
            
            delete_btn = ctk.CTkButton(
                btn_frame,
                text="🗑️",
                command=lambda m=model_name: self._delete_custom_model(m),
                width=30,
                height=25,
                fg_color="transparent",
                border_color=("gray70", "gray30"),
                border_width=1,
                hover_color=("red", "#990000")
            )
            delete_btn.grid(row=0, column=1)

    def _edit_model_settings(self, model_name):
        """Mở dialog chỉnh sửa settings cho model cụ thể."""
        # Temporarily set the model to edit its settings
        original_model = self.model_var.get()
        self.model_var.set(model_name)
        
        # Close model manager window
        if hasattr(self, 'model_manager_window'):
            self.model_manager_window.destroy()
        
        # Open model settings
        self.open_model_settings()
        
        # Restore original model selection after settings dialog closes
        def restore_model():
            if hasattr(self, 'model_settings_window') and self.model_settings_window.winfo_exists():
                self.after(100, restore_model)
            else:
                self.model_var.set(original_model)
                # Reopen model manager
                self.after(100, self.open_model_manager)
        
        restore_model()

    def _delete_custom_model(self, model_to_delete):
        """Xóa một model tùy chỉnh khỏi danh sách đã lưu."""
        result = show_question(
            f"Bạn có chắc muốn xóa model '{model_to_delete}' không?\n\nCài đặt của model này cũng sẽ bị xóa.",
            parent=self.model_manager_window
        )
        
        if not result:
            return
            
        if model_to_delete in self.saved_custom_models:
            self.saved_custom_models.remove(model_to_delete)
            
            # Remove model settings
            if model_to_delete in self.model_settings:
                del self.model_settings[model_to_delete]
            
            # Nếu model đang được chọn bị xóa, reset về model mặc định
            if self.model_var.get() == model_to_delete:
                self.model_var.set(self._get_default_model())
                
            self._update_model_list() # Cập nhật combobox chính
            self._populate_model_manager() # Cập nhật cửa sổ quản lý
            
            self.log(f"🗑️ Đã xóa model tùy chỉnh: {model_to_delete}")
            show_toast_success(f"Đã xóa model: {model_to_delete}")
        else:
            show_toast_error(f"Không tìm thấy model: {model_to_delete}")

    def _get_default_model(self):
        """Lấy model mặc định dựa trên provider hiện tại."""
        provider = self.api_provider_var.get()
        if provider == "Google AI":
            return "gemini-2.5-flash"
        else: # OpenRouter
            return "anthropic/claude-3.5-sonnet"

if __name__ == "__main__":
    app = ModernTranslateNovelAI()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()