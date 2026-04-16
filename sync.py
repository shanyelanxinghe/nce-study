import os
from notion_client import Client

api_key = os.getenv('NOTION_TOKEN')
page_id = os.getenv('NOTION_PAGE_ID')
notion = Client(auth=api_key)

# 1. 先读取GitHub本地md文件
github_md = ""
if os.path.exists("notion-sync.md"):
    with open("notion-sync.md","r",encoding="utf-8") as f:
        github_md = f.read()

# 2. 读取Notion页面内容
blocks = notion.blocks.children.list(block_id=page_id).get("results", [])
notion_text = ""
for b in blocks:
    if b["type"] == "paragraph":
        t = b["paragraph"]["rich_text"][0]["text"]["content"] if b["paragraph"]["rich_text"] else ""
        notion_text += t + "\n\n"

# 3. 双向判断：哪边新就同步哪边
# GitHub文件有内容、比notion新 → 写入回Notion
if len(github_md) > len(notion_text):
    # 清空notion原有内容
    for b in blocks:
        notion.blocks.delete(block_id=b["id"])
    # 把github内容写回notion
    notion.blocks.children.append(
        block_id=page_id,
        children=[{"type":"paragraph","paragraph":{"rich_text":[{"type":"text","text":{"content":github_md}}]}}]
    )
    print("✅ GitHub修改已同步回Notion")

# Notion内容更新 → 导出保存到GitHub
else:
    with open("notion-sync.md","w",encoding="utf-8") as f:
        f.write("# 双向同步文档\n\n"+notion_text)
    print("✅ Notion内容已同步到GitHub")
