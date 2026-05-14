---
name: qzone-album-mcp
description: Use when user asks to batch process Qzone group albums via browser control: open each album from the group album page, extract publish/comment content, trigger UI batch download, build per-album images+csv+xlsx outputs, and clean temporary download cache.
---

# Qzone Album MCP

## Scope

Use this skill for Qzone group album tasks that require real page interaction and local deliverables.

Hard constraints:
- Use browser page actions (MCP Chrome control) as the primary workflow.
- Do not replace page-based batch-download with direct API workflow.
- After each album finishes, always return to the base album page before opening next.
- Do not keep `picKey` in final output tables.
- Keep download directory clean by deleting transient `qzone_*.csv` and `qzone_*.json` after each album.
- Keep each album directory minimal: only `images/`, `相册名_发布内容表.csv`, `相册名_发布内容表.xlsx`.
- Use incremental backup only: do not resave records already indexed by publish time.

Base page:
- `https://h5.qzone.qq.com/groupphoto/index?inqq=3&groupId=377144996&_t_=0.7609239734798603&`

Default album set for this workspace (unless user changes it):
1. 全服务航司经济舱
2. 机场休息室
3. 铁路出行
4. 商务舱
5. 头等舱
6. 超级经济舱
7. 高铁休息室
8. 廉航经济舱
9. 酒店酒廊，早餐
10. 带娃出行
11. 驾驶舱与flight log
12. 酒店房间（展示要饭成果）

## Required per-album workflow

1. Navigate to base page.
2. Click `相册`, then open target album.
3. Scroll until thumbnails stabilize (all loaded).
4. Open photos and collect metadata for each item:
   - `发布人`, `发布时间`, `发布内容`, `评论数`, `评论内容`
   - Prefer right-side detail/comment area (`#_slideView_userinfo`, `#js-description-inner`, `#js-comment-module`).
5. Trigger image download only via UI path:
   - `管理` -> `批量下载` -> `点击下载整个相册` -> `开始下载/本地下载`
6. Save outputs in a dedicated album folder.
7. Return to base page and continue next album.

## Output contract

Per album folder keep only:
- `images/`
- `相册名_发布内容表.csv`
- `相册名_发布内容表.xlsx`

Table columns (no `picKey`):
- `序号`
- `文件名`
- `本地路径`
- `发布人`
- `发布时间`
- `发布内容`
- `评论数`
- `评论内容`

If album has zero images:
- still create `images/`, csv, xlsx (header-only).

## XLSX style minimum

- Header fill/font style
- Freeze top row
- Keep readable column widths
- Include `预览` image column with scaled thumbnails
- Row height adjusted to thumbnail size

## Cleanup rules

After each album run:
- Remove transient cache files in downloads such as `qzone_*.csv` and `qzone_*.json`.
- Remove intermediate zip/temp artifacts in album folder.
- Keep only final artifacts defined above.
- Avoid leaving helper scripts or temporary program files in this workspace.

## Incremental backup policy

State index file:
- `/Users/lazywords/Code/QQ群相册/.backup_publish_time_index.json`

Rules:
1. Before processing each album, load state index.
2. Primary dedupe key: `album + publish_time`.
3. If key already exists, skip saving that row/image as duplicate.
4. If `publish_time` is empty, fallback key: `album + filename`.
5. After processing, write back:
   - newly saved keys,
   - per-album latest publish_time,
   - run timestamp.
6. Output must represent only newly saved content for that run (no duplicate backup).

## Quality checks

For each album, validate:
- Image count in `images/`
- CSV row count
- Row completeness: table rows should match album total image count.
- Non-empty rate for key fields (`发布时间`, `发布内容` where applicable)
- Xlsx exists and opens with preview column

## Failure handling

- If element lookup fails, retry click/refresh/re-enter the same album; do not skip silently.
- Report per-album progress (`done/total`) and explicitly note any mismatch or missing fields before moving on.
