#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tool gộp tất cả file .txt trong một thư mục thành một file duy nhất
Hỗ trợ chuyển đổi từ UTF-16 sang UTF-8
"""

import os
import glob
from pathlib import Path


def detect_encoding(file_path):
    """
    Phát hiện encoding của file (UTF-16 hoặc UTF-8)
    Chỉ đọc 8KB đầu tiên để tối ưu hiệu suất
    """
    # Kiểm tra BOM trước
    with open(file_path, 'rb') as f:
        raw = f.read(4)
        if raw.startswith(b'\xff\xfe\x00\x00'):
            return 'utf-32-le'
        elif raw.startswith(b'\x00\x00\xfe\xff'):
            return 'utf-32-be'
        elif raw.startswith(b'\xff\xfe') or raw.startswith(b'\xfe\xff'):
            return 'utf-16'
        elif raw.startswith(b'\xef\xbb\xbf'):
            return 'utf-8-sig'
    
    # Thử các encoding phổ biến
    encodings = ['utf-8', 'utf-8-sig', 'utf-16', 'utf-16-le', 'utf-16-be', 
                 'cp1252', 'latin-1', 'ascii']
    
    for encoding in encodings:
        try:
            with open(file_path, 'r', encoding=encoding) as f:
                # Chỉ đọc 8KB đầu tiên để detect
                sample = f.read(8192)
                if sample:  # Kiểm tra có nội dung
                    return encoding
        except (UnicodeDecodeError, UnicodeError, LookupError):
            continue
    
    # Fallback cuối cùng
    return 'utf-8'


def merge_txt_files(input_folder, output_file='merged_output.txt', separator='\n'):
    """
    Gộp tất cả file .txt trong thư mục thành một file duy nhất
    
    Args:
        input_folder (str): Đường dẫn đến thư mục chứa file .txt
        output_file (str): Tên file output (mặc định: merged_output.txt)
        separator (str): Ký tự phân cách giữa các file (mặc định: xuống dòng)
    """
    
    # Kiểm tra thư mục có tồn tại không
    if not os.path.exists(input_folder):
        print(f"❌ Lỗi: Thư mục '{input_folder}' không tồn tại!")
        return
    
    # Tìm tất cả file .txt trong thư mục
    txt_files = sorted(glob.glob(os.path.join(input_folder, '*.txt')))
    
    if not txt_files:
        print(f"❌ Không tìm thấy file .txt nào trong thư mục '{input_folder}'!")
        return
    
    print(f"📁 Tìm thấy {len(txt_files)} file .txt")
    print(f"📝 Đang gộp các file...\n")
    
    # Gộp nội dung các file
    merged_content = []
    success_count = 0
    error_count = 0
    
    for txt_file in txt_files:
        file_name = os.path.basename(txt_file)
        try:
            # Phát hiện encoding
            encoding = detect_encoding(txt_file)
            
            # Đọc nội dung file
            with open(txt_file, 'r', encoding=encoding, errors='replace') as f:
                content = f.read()
            
            # Bỏ qua file rỗng
            if not content or not content.strip():
                print(f"⚠️  {file_name} (rỗng - bỏ qua)")
                continue
            
            # Loại bỏ BOM nếu còn sót lại (đối phó với một số trường hợp đặc biệt)
            if content.startswith('\ufeff'):
                content = content[1:]
            
            # Normalize line endings (chuyển tất cả về \n)
            content = content.replace('\r\n', '\n').replace('\r', '\n')
            
            # Loại bỏ khoảng trắng thừa ở đầu và cuối
            content = content.strip()
            
            # Thêm nội dung vào danh sách
            merged_content.append(content)
            
            print(f"✅ {file_name} ({encoding})")
            success_count += 1
            
        except Exception as e:
            print(f"❌ Lỗi khi đọc {file_name}: {str(e)}")
            error_count += 1
    
    # Ghi file output với encoding UTF-8 (không có BOM)
    if merged_content:
        try:
            output_path = os.path.join(input_folder, output_file)
            # Ghi file với UTF-8 không BOM, newline='\n' để thống nhất
            with open(output_path, 'w', encoding='utf-8', newline='\n') as f:
                f.write(separator.join(merged_content))
            
            # Thống kê
            file_size = os.path.getsize(output_path)
            total_lines = sum(content.count('\n') + 1 for content in merged_content)
            
            print(f"\n{'='*80}")
            print(f"✨ Hoàn thành!")
            print(f"📊 Thống kê:")
            print(f"   - Thành công: {success_count} file")
            print(f"   - Lỗi: {error_count} file")
            print(f"   - Tổng số dòng: {total_lines:,}")
            print(f"📄 File output: {output_path}")
            print(f"📦 Encoding: UTF-8 (không BOM)")
            print(f"💾 Kích thước: {file_size:,} bytes ({file_size/1024:.2f} KB)")
            print(f"{'='*80}")
            
        except Exception as e:
            print(f"\n❌ Lỗi khi ghi file output: {str(e)}")
    else:
        print("\n❌ Không có nội dung nào được gộp!")


def main():
    """
    Hàm chính
    """
    print("="*80)
    print(" "*20 + "CÔNG CỤ GỘP FILE TXT")
    print("="*80)
    print()
    
    # Nhập đường dẫn thư mục
    input_folder = input("📁 Nhập đường dẫn thư mục chứa file .txt: ").strip()
    
    # Xóa dấu ngoặc kép nếu có
    input_folder = input_folder.strip('"').strip("'")
    
    # Nhập tên file output (tuỳ chọn)
    output_file = input("📝 Nhập tên file output (Enter để dùng 'merged_output.txt'): ").strip()
    if not output_file:
        output_file = 'merged_output.txt'
    
    # Đảm bảo file output có đuôi .txt
    if not output_file.endswith('.txt'):
        output_file += '.txt'
    
    print()
    
    # Gộp file
    merge_txt_files(input_folder, output_file)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️ Đã dừng chương trình!")
    except Exception as e:
        print(f"\n❌ Lỗi: {str(e)}")
    
    # Giữ cửa sổ console mở
    input("\nNhấn Enter để thoát...")

