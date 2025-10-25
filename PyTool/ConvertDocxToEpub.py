import os
import subprocess 

# RẤT QUAN TRỌNG:
# HÃY THAY THẾ DÒNG DƯỚI ĐÂY BẰNG ĐƯỜNG DẪN THẬT CỦA pandoc.exe TRÊN MÁY BẠN.
# Bạn có thể tìm thấy nó bằng cách mở Command Prompt/PowerShell và gõ: where pandoc
# Ví dụ: PANDOC_PATH = r"C:\Program Files\Pandoc\pandoc.exe"
# Ví dụ khác: PANDOC_PATH = r"C:\Users\YOUR_USERNAME\AppData\Local\Pandoc\pandoc.exe"
PANDOC_PATH = r"C:\Users\vinhd\AppData\Local\Pandoc\pandoc.exe" # <--- CHỈNH SỬA DÒNG NÀY!


def docx_to_epub(docx_path, epub_path, book_title, book_author, chapter_level=1, include_toc=True, toc_depth=1):
    """
    Chuyển đổi file .docx sang .epub bằng Pandoc.

    Args:
        docx_path (str): Đường dẫn đến file .docx nguồn.
        epub_path (str): Đường dẫn đến file .epub đích.
        book_title (str): Tiêu đề của sách.
        book_author (str): Tác giả của sách.
        chapter_level (int): Mức độ heading được coi là chương (mặc định: 1 = Heading 1).
        include_toc (bool): Có tạo mục lục không (mặc định: True).
        toc_depth (int): Độ sâu của mục lục (mặc định: 1).
    Returns:
        bool: True nếu thành công, False nếu thất bại.
    """
    print(f"\nBắt đầu chuyển đổi DOCX sang EPUB...")
    print(f"  File DOCX nguồn: {docx_path}")
    print(f"  File EPUB đích: {epub_path}")

    if not os.path.exists(docx_path):
        print(f"  ❌ Lỗi: Không tìm thấy file .docx tại đường dẫn '{docx_path}'")
        return False

    # Xây dựng lệnh Pandoc
    command = [
        PANDOC_PATH,
        '-o', epub_path,
        docx_path,
        '--metadata', f'title={book_title}',
        '--metadata', f'author={book_author}',
        f'--epub-chapter-level={chapter_level}',
    ]

    # Thêm tùy chọn mục lục nếu được yêu cầu
    if include_toc:
        command.append('--toc')
        command.append(f'--toc-depth={toc_depth}')

    print(f"\n  Đang chạy Pandoc...")
    print(f"  Lệnh: {' '.join(command)}")

    try:
        # Chạy lệnh Pandoc
        result = subprocess.run(command, check=True, capture_output=True, text=True, encoding='utf-8')
        
        print(f"\n  ✓ Thành công! File EPUB đã được tạo tại: {epub_path}")
        
        if result.stdout:
            print("\n  Pandoc output (stdout):")
            print(result.stdout)
        if result.stderr:
            print("\n  Pandoc warnings (stderr):")
            print(result.stderr)
        
        return True
        
    except FileNotFoundError:
        print("\n  ❌ Lỗi: Pandoc không được tìm thấy TẠI ĐƯỜNG DẪN ĐÃ CHỈ ĐỊNH.")
        print(f"  Đảm bảo đường dẫn '{PANDOC_PATH}' là chính xác.")
        print("  Sử dụng 'where pandoc' trong CMD/PowerShell để tìm đường dẫn của bạn.")
        print("  Tải Pandoc tại: https://pandoc.org/installing.html")
        return False
        
    except subprocess.CalledProcessError as e:
        print(f"\n  ❌ Lỗi khi chạy Pandoc. Mã lỗi: {e.returncode}")
        print(f"  Pandoc stdout: {e.stdout}")
        print(f"  Pandoc stderr: {e.stderr}")
        print(f"  Lệnh đã chạy: {' '.join(command)}")
        return False
        
    except Exception as e:
        print(f"  ❌ Lỗi không xác định khi chuyển đổi DOCX sang EPUB: {e}")
        return False


# --- Phần chạy chính của script ---
if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("CHUYỂN ĐỔI DOCX SANG EPUB")
    print("=" * 70)

    # Nhập đường dẫn file DOCX
    docx_input = input("\nNhập đường dẫn đến file .docx nguồn: ").strip().strip('"')
    docx_file_path = os.path.abspath(docx_input)

    # Kiểm tra file tồn tại
    if not os.path.exists(docx_file_path):
        print(f"❌ Lỗi: Không tìm thấy file tại '{docx_file_path}'")
        exit(1)

    # Kiểm tra extension
    if not docx_file_path.lower().endswith('.docx'):
        print(f"❌ Lỗi: File phải có định dạng .docx")
        exit(1)

    # Tự động đặt tên file EPUB theo tên file DOCX
    docx_base_name = os.path.splitext(os.path.basename(docx_file_path))[0]
    epub_file_path = os.path.join(os.path.dirname(docx_file_path), docx_base_name + ".epub")

    # Nhập thông tin sách
    title = input(f"\nNhập tiêu đề sách (mặc định: '{docx_base_name}'): ").strip()
    if not title:
        title = docx_base_name
        print(f"  → Sử dụng tiêu đề mặc định: {title}")

    author = input("Nhập tên tác giả (mặc định: Unknown Author): ").strip()
    if not author:
        author = "Unknown Author"
        print(f"  → Sử dụng tác giả mặc định: {author}")

    # Tùy chọn nâng cao
    print("\n--- Tùy chọn nâng cao ---")
    
    chapter_level_input = input("Nhập mức heading cho chương (1=Heading 1, 2=Heading 2, mặc định: 1): ").strip()
    chapter_level = 1
    if chapter_level_input and chapter_level_input.isdigit():
        chapter_level = int(chapter_level_input)
        print(f"  → Sử dụng Heading {chapter_level} làm chương")
    else:
        print(f"  → Sử dụng Heading 1 làm chương (mặc định)")

    include_toc_input = input("Tạo mục lục (Table of Contents)? (y/n, mặc định: y): ").strip().lower()
    include_toc = True if include_toc_input != 'n' else False
    
    toc_depth = 1
    if include_toc:
        toc_depth_input = input("Độ sâu mục lục (1-6, mặc định: 1): ").strip()
        if toc_depth_input and toc_depth_input.isdigit():
            toc_depth = int(toc_depth_input)
            if toc_depth < 1:
                toc_depth = 1
            elif toc_depth > 6:
                toc_depth = 6
        print(f"  → Mục lục với độ sâu: {toc_depth}")
    else:
        print("  → Không tạo mục lục")

    # Tùy chọn file output
    custom_output = input(f"\nNhập đường dẫn file EPUB đích (mặc định: '{epub_file_path}'): ").strip().strip('"')
    if custom_output:
        epub_file_path = os.path.abspath(custom_output)
        print(f"  → Sử dụng đường dẫn tùy chỉnh: {epub_file_path}")

    # Hiển thị tóm tắt
    print("\n" + "=" * 70)
    print("THÔNG TIN CHUYỂN ĐỔI")
    print("=" * 70)
    print(f"  File DOCX nguồn: {docx_file_path}")
    print(f"  File EPUB đích: {epub_file_path}")
    print(f"  Tiêu đề sách: {title}")
    print(f"  Tác giả: {author}")
    print(f"  Mức heading chương: Heading {chapter_level}")
    print(f"  Mục lục: {'Có' if include_toc else 'Không'}")
    if include_toc:
        print(f"  Độ sâu mục lục: {toc_depth}")
    print("=" * 70)

    # Xác nhận
    confirm = input("\nBắt đầu chuyển đổi? (y/n): ").strip().lower()
    if confirm != 'y':
        print("Đã hủy.")
        exit(0)

    # Thực hiện chuyển đổi
    try:
        success = docx_to_epub(
            docx_file_path, 
            epub_file_path, 
            title, 
            author, 
            chapter_level=chapter_level,
            include_toc=include_toc,
            toc_depth=toc_depth
        )
        
        if success:
            print("\n" + "=" * 70)
            print("✓ HOÀN THÀNH!")
            print("=" * 70)
            print(f"File EPUB đã được tạo thành công tại:\n{epub_file_path}")
        else:
            print("\n" + "=" * 70)
            print("❌ CHUYỂN ĐỔI THẤT BẠI")
            print("=" * 70)
            
    except Exception as e:
        print(f"\n❌ Lỗi nghiêm trọng trong quá trình chuyển đổi: {e}")
        import traceback
        traceback.print_exc()

    print("\nQuá trình chuyển đổi đã hoàn tất.")
