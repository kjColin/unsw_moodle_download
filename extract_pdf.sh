#!/bin/bash
# 提取PDF文本供AI总结

PDF_FILE="$1"

if [ -z "$PDF_FILE" ]; then
  echo "用法: $0 <pdf文件路径>"
  echo ""
  echo "示例: $0 ~/Unsw/COMP9417/Lectures/Week1_Regression.pdf"
  exit 1
fi

if [ ! -f "$PDF_FILE" ]; then
  echo "文件不存在: $PDF_FILE"
  exit 1
fi

echo "=== PDF内容 (前5000字符) ==="
echo ""
pdftotext "$PDF_FILE" - 2>/dev/null | head -c 5000
echo ""
echo ""
echo "=== 请把这个内容发给我，我来帮你总结 ==="
