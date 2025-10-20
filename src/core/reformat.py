import re
import os

def fix_text_format(filepath):
    """
    Sửa lỗi định dạng file text:
    1. Thay thế 3 hoặc nhiều hơn ký tự xuống dòng liên tiếp (ví dụ: \n\n\n)
       bằng 2 ký tự xuống dòng liên tiếp (\n\n) để phân cách đoạn đúng chuẩn.
    2. Xóa các ký tự ** (markdown bold markers)
    3. Xử lý path có dấu ngoặc kép
    """
    # Xử lý path có dấu ngoặc kép
    if filepath.startswith('"') and filepath.endswith('"'):
        filepath = filepath[1:-1]
    elif filepath.startswith("'") and filepath.endswith("'"):
        filepath = filepath[1:-1]
    
    # Normalize path
    filepath = os.path.normpath(filepath)
    
    if not os.path.exists(filepath):
        print(f"Lỗi: Không tìm thấy file tại đường dẫn '{filepath}'")
        return False

    print(f"Đang xử lý file: '{filepath}'...")

    try:
        # Bước 1: Đọc toàn bộ nội dung file
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        print(f"📊 Kích thước file gốc: {len(content)} ký tự")
        
        # Đếm số lượng trước khi xử lý
        bold_markers_count = content.count('**')
        newlines_count = len(re.findall(r'\n{3,}', content))
        
        # Bước 2: Xóa các ký tự ** (markdown bold markers)
        # Thay thế ** bằng chuỗi rỗng
        fixed_content = content.replace('**', '')
        
        if bold_markers_count > 0:
            print(f"🔧 Đã xóa {bold_markers_count} ký tự ** (markdown bold)")

        # Bước 3: Chuẩn hóa xuống dòng
        # Sử dụng biểu thức chính quy (regex) để tìm kiếm và thay thế:
        # r'\n{3,}' tìm 3 hoặc nhiều hơn ký tự xuống dòng liên tiếp
        # '\n\n' sẽ thay thế chúng bằng 2 ký tự xuống dòng liên tiếp
        fixed_content = re.sub(r'\n{3,}', '\n\n', fixed_content)
        
        if newlines_count > 0:
            print(f"🔧 Đã chuẩn hóa {newlines_count} vị trí có 3+ dòng trống")

        # Bước 4: Loại bỏ các dòng trống thừa ở đầu và cuối file (nếu có)
        # và đảm bảo kết thúc bằng một dòng trống đúng chuẩn (nếu cần)
        fixed_content = fixed_content.strip() # Xóa dòng trống đầu/cuối
        if fixed_content: # Nếu nội dung không rỗng, đảm bảo có một dòng trống cuối cùng (để phân cách đoạn cuối)
            fixed_content += '\n' # re.sub có thể đã để lại một \n hoặc không, strip() sẽ xóa tất cả.
                                  # Thêm lại một \n để đảm bảo định dạng file text đúng chuẩn
                                  # (thường các file text kết thúc bằng một ký tự xuống dòng).

        # Bước 5: Ghi nội dung đã sửa vào file gốc
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(fixed_content)

        # Thống kê
        size_diff = len(content) - len(fixed_content)
        print(f"📊 Kích thước file sau reformat: {len(fixed_content)} ký tự")
        if size_diff > 0:
            print(f"✂️ Đã giảm {size_diff} ký tự ({size_diff / len(content) * 100:.1f}%)")
        
        print(f"✅ Hoàn tất sửa lỗi định dạng cho file '{os.path.basename(filepath)}'.")
        return True

    except Exception as e:
        print(f"❌ Đã xảy ra lỗi trong quá trình xử lý: {e}")
        return False

# --- Cách sử dụng script ---
if __name__ == "__main__":
    # Yêu cầu người dùng nhập đường dẫn file
    file_path = input("Vui lòng nhập đường dẫn đến file .txt cần chỉnh sửa: ")

    # Xác nhận trước khi thực hiện để tránh mất dữ liệu
    confirm = input(f"Bạn có chắc chắn muốn sửa file '{file_path}'? "
                    "Hành động này sẽ ghi đè lên file gốc. (y/n): ").lower()

    if confirm == 'y':
        fix_text_format(file_path)
    else:
        print("Hủy bỏ thao tác. File không bị thay đổi.")