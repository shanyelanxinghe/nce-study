import os
import json
from notion_client import Client

# 1. 初始化 Notion 客户端（从环境变量读 Token）
token = os.getenv("NOTION_TOKEN")
if not token:
    print("❌ 请在 GitHub Secrets 中配置 NOTION_TOKEN！")
    exit(1)
notion = Client(auth=token)

# 2. 读取 GitHub 本地的 notion-sync.md 文件内容
github_md = ""
if os.path.exists("notion-sync.md"):
    with open("notion-sync.md", "r", encoding="utf-8") as f:
        github_md = f.read()

# 3. 读取 Notion 页面内容（假设 page_id 存在环境变量，或你可以写死测试）
page_id = os.getenv("NOTION_PAGE_ID")  # 也可以直接写死，比如 page_id = "你的页面ID"
blocks = notion.blocks.children.list(block_id=page_id).get("results", [])

notion_text = ""
for block in blocks:
    if block["type"] == "paragraph":
        text = block["paragraph"]["rich_text"][0]["text"]["content"]
        notion_text += text + "\n\n"

# 4. 双向同步逻辑：谁新就同步谁
# 情况1：GitHub 本地 md 比 Notion 新 → 把 GitHub 内容推送到 Notion
if len(github_md) > len(notion_text):
    print("🔄 GitHub 内容更新，正在同步到 Notion...")
    # 先清空 Notion 原有内容（可选，也可以增量更新）
    for block in blocks:
        notion.blocks.delete(block_id=block["id"])
    # 再把 GitHub 内容逐段写入 Notion
    for line in github_md.split("\n\n"):
        if line.strip():
            notion.blocks.children.append(
                block_id=page_id,
                children=[
                    {
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [{"type": "text", "text": {"content": line}}]
                        }
                    }
                ]
            )

# 情况2：Notion 比 GitHub 新 → 把 Notion 内容拉取到 GitHub 本地 md
elif len(notion_text) > len(github_md):
    print("🔄 Notion 内容更新，正在同步到 GitHub...")
    with open("notion-sync.md", "w", encoding="utf-8") as f:
        f.write(notion_text)

else:
    print("✅ 两边内容一致，无需同步～")

print("🎉 同步完成！")
