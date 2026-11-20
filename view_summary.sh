#!/bin/bash
# 查看课程PDF总结

SUMMARY_DIR="/home/colin/Unsw/Summaries"

if [ -z "$1" ]; then
  echo "=== 课程总结目录 ==="
  echo ""
  for course in COMP9414 COMP9417 COMP9511 GSOE9011; do
    if [ -d "$SUMMARY_DIR/$course" ]; then
      for cat in Lectures Tutorials Assignments; do
        count=$(find "$SUMMARY_DIR/$course/$cat" -name "*.json" 2>/dev/null | wc -l)
        if [ "$count" -gt 0 ]; then
          echo "  $course/$cat: $count 个总结"
        fi
      done
    fi
  done
  echo ""
  echo "用法: $0 <课程> [类型]"
  echo "示例: $0 COMP9417 Lectures"
  exit 0
fi

COURSE=$1
CATEGORY=${2:-}

if [ -n "$CATEGORY" ]; then
  DIR="$SUMMARY_DIR/$COURSE/$CATEGORY"
else
  DIR="$SUMMARY_DIR/$COURSE"
fi

if [ ! -d "$DIR" ]; then
  echo "未找到: $DIR"
  exit 1
fi

echo "=== $COURSE ${CATEGORY:-所有} 总结 ==="
echo ""

find "$DIR" -name "*.json" -type f | sort | while read file; do
  cat_name=$(basename $(dirname "$file"))
  name=$(basename "$file" _summary.json)
  
  echo "----------------------------------------"
  echo "[$cat_name] $name"
  echo ""
  
  # 提取关键信息
  echo "标题:"
  jq -r '.title' "$file" 2>/dev/null
  echo ""
  
  echo "关键词:"
  jq -r '.keywords[:8] | map(.word) | join(", ")' "$file" 2>/dev/null
  echo ""
  
  echo "关键点:"
  jq -r '.keyPoints[:5][]' "$file" 2>/dev/null | sed 's/^/  - /'
  echo ""
  
  echo "预览:"
  jq -r '.preview[:200]' "$file" 2>/dev/null | fold -s -w 60
  echo "..."
done
