import os
from notion_client import Client

# 读取密钥
api_key = os.getenv('NOTION_TOKEN')
page_id = os.getenv('NOTION_PAGE_ID')

# 初始化客户端
notion = Client(auth=api_key)

# 导出页面内容为Markdown
try:
    # 获取页面子区块
    blocks = notion.blocks.children.list(block_id=page_id).get("results", [])
    
    markdown_content = "# 自动同步的Notion内容\n\n"
    
    # 简单转换为Markdown（可根据需要扩展）
    for block in blocks:
        if block["type"] == "paragraph":
            text = block["paragraph"]["rich_text"][0]["text"]["content"] if block["paragraph"]["rich_text"] else ""
            markdown_content += text + "\n\n"
    
    # 写入文件
    with open("notion-sync.md", "w", encoding="utf-8") as f:
        f.write(markdown_content)
    
    print("✅ 成功生成Markdown文件！")
except Exception as e:
    print(f"❌ 导出失败: {e}")
    exit(1)
