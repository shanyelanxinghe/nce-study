import os
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

# 3. 读取 Notion 页面内容（假设 page_id 存在环境变量，也可以写死测试）
page_id = os.getenv("NOTION_PAGE_ID")  # 例如：page_id = "你的Notion页面ID"
if not page_id:
    print("❌ 请在 GitHub Secrets 中配置 NOTION_PAGE_ID，或直接写死页面ID！")
    exit(1)

blocks = notion.blocks.children.list(block_id=page_id).get("results", [])
notion_text = ""
for b in blocks:
    if b["type"] == "paragraph":
        text = b["paragraph"]["rich_text"][0]["text"]["content"]
        notion_text += text + "\n"

# 4. 双向同步逻辑：GitHub 新 → 写入 Notion；Notion 新 → 写入 GitHub（这里先做 GitHub→Notion）
if len(github_md) > len(notion_text):
    # 清空 Notion 原有内容（可选，也可以增量更新）
    for b in blocks:
        notion.blocks.delete(block_id=b["id"])
    # 将 GitHub 内容写入 Notion（按段落拆分）
    paragraphs = github_md.split("\n\n")  # 按空行拆分段落
    for p in paragraphs:
        if p.strip():  # 跳过空段落
            notion.blocks.children.append(
                block_id=page_id,
                children=[
                    {
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [{"type": "text", "text": {"content": p}}]
                        }
                    }
                ]
            )
    print("✅ GitHub 内容已同步到 Notion！")
else:
    print("ℹ️ Notion 内容比 GitHub 新，或两者一致，无需同步。")
