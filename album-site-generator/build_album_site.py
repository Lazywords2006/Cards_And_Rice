#!/usr/bin/env python3
"""
QQ群相册静态站点生成器

功能：
1. 递归读取导出的 CSV 索引文件（默认匹配 *_发布内容表.csv）
2. 解析并清洗图片元数据，按相册分类，并按发布时间排序
3. 生成两套产物：
   - 可直接托管的纯静态站点（HTML/CSS/JS）
   - Hugo 兼容的 Markdown + static 图片目录
4. 输出构建报告与告警日志（缺图、编码问题、时间解析失败等）
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import unquote

try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
except ImportError as exc:
    raise SystemExit(
        "缺少依赖 Jinja2，请先执行: pip install -r requirements.txt"
    ) from exc


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".heic", ".heif"}

HEADER_ALIASES = {
    "index": ["序号", "id", "index"],
    "file_name": ["文件名", "filename", "file"],
    "local_path": ["本地路径", "路径", "local_path", "path"],
    "preview": ["预览", "preview"],
    "author": ["发布人", "author", "publisher"],
    "publish_time": ["发布时间", "publish_time", "time"],
    "content": ["发布内容", "内容", "caption", "description"],
    "comment_count": ["评论数", "comment_count", "comments"],
    "comment_text": ["评论内容", "comment_text"],
}

TIME_FORMATS = [
    "%Y年%m月%d日 %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
]


@dataclass
class PhotoRecord:
    index: int
    file_name: str
    local_path_raw: str
    source_path: Optional[Path]
    preview: str
    author: str
    publish_time_raw: str
    publish_time: Optional[datetime]
    content: str
    comment_count: int
    comment_text: str
    album_name: str
    album_slug: str
    source_csv: Path
    site_image_rel: Optional[str] = None
    hugo_image_rel: Optional[str] = None
    missing_image: bool = False


@dataclass
class CategoryInfo:
    name: str
    slug: str
    path: Path


@dataclass
class BuildWarning:
    code: str
    message: str
    csv_file: str
    row_number: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="将群相册 CSV 导出数据转换为静态站点（HTML + Hugo Markdown）"
    )
    parser.add_argument(
        "--source-root",
        default=".",
        help="数据根目录（默认当前目录）",
    )
    parser.add_argument(
        "--output-root",
        default="./dist",
        help="输出目录（默认 ./dist）",
    )
    parser.add_argument(
        "--site-title",
        default="QQ群相册",
        help="站点标题",
    )
    parser.add_argument(
        "--csv-pattern",
        default="*_发布内容表.csv",
        help="CSV 文件匹配模式（默认 *_发布内容表.csv）",
    )
    parser.add_argument(
        "--sort-order",
        choices=["asc", "desc"],
        default="asc",
        help="发布时间排序方向（默认 asc）",
    )
    parser.add_argument(
        "--clean-output",
        action="store_true",
        help="构建前清空输出目录",
    )
    parser.add_argument(
        "--ignore-dirs",
        default="dist,album-site-generator,qzone-album-mcp",
        help="忽略的根目录一级文件夹（逗号分隔）",
    )
    return parser.parse_args()


def create_env(template_root: Path) -> Environment:
    return Environment(
        loader=FileSystemLoader(str(template_root)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def slugify(text: str) -> str:
    """将任意相册名转为 URL 友好的稳定 slug（支持中文）。"""
    text = (text or "").strip()
    if not text:
        return "untitled"

    pieces: List[str] = []
    for ch in text:
        if ch.isascii() and (ch.isalnum() or ch in {"-", "_"}):
            pieces.append(ch.lower())
        elif ch.isspace():
            pieces.append("-")
        else:
            pieces.append(f"u{ord(ch):x}")

    slug = "".join(pieces)
    slug = re.sub(r"-+", "-", slug)
    slug = re.sub(r"[^a-z0-9_\-u]", "", slug)
    return slug.strip("-") or "untitled"


def normalize_text(value: str) -> str:
    value = (value or "").strip().strip('"').strip("'")
    return value


def normalize_path_text(path_value: str) -> str:
    """尽量修复路径中的编码或转义问题。"""
    text = normalize_text(path_value)
    if not text:
        return ""

    text = text.replace("\\\\", "/")
    text = unquote(text)

    # 尝试修复常见的 UTF-8/Latin-1 乱码。
    try:
        repaired = text.encode("latin1").decode("utf-8")
        if repaired and repaired != text:
            text = repaired
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass

    return text


def parse_time(raw: str) -> Optional[datetime]:
    raw = normalize_text(raw)
    if not raw:
        return None

    for fmt in TIME_FORMATS:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def parse_int(raw: str, default: int = 0) -> int:
    raw = normalize_text(raw)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def find_matching_key(row: Dict[str, str], aliases: Iterable[str]) -> Optional[str]:
    row_keys = {k.strip().lower(): k for k in row.keys() if k is not None}
    for alias in aliases:
        key = row_keys.get(alias.strip().lower())
        if key is not None:
            return key
    return None


def pick(row: Dict[str, str], aliases: Iterable[str]) -> str:
    key = find_matching_key(row, aliases)
    return row.get(key, "") if key is not None else ""


def read_csv_rows(csv_path: Path) -> List[Tuple[int, Dict[str, str]]]:
    """读取 CSV 并兼容常见编码。返回 (行号, 行数据) 列表。"""
    encodings = ["utf-8-sig", "utf-8", "gb18030"]
    last_error: Optional[Exception] = None

    for encoding in encodings:
        try:
            with csv_path.open("r", encoding=encoding, newline="") as fp:
                reader = csv.DictReader(fp)
                rows: List[Tuple[int, Dict[str, str]]] = []
                for row_number, row in enumerate(reader, start=2):
                    rows.append((row_number, row))
                return rows
        except UnicodeDecodeError as exc:
            last_error = exc
            continue

    if last_error is not None:
        raise last_error

    return []


def build_filename_index(source_root: Path) -> Dict[str, List[Path]]:
    """建立文件名到本地路径的索引，用于路径缺失时兜底定位图片。"""
    index: Dict[str, List[Path]] = defaultdict(list)
    for file_path in source_root.rglob("*"):
        if file_path.is_file() and file_path.suffix.lower() in IMAGE_EXTENSIONS:
            index[file_path.name].append(file_path)
    return index


def discover_categories(source_root: Path, ignore_dirs: Iterable[str]) -> List[CategoryInfo]:
    ignored = {name.strip() for name in ignore_dirs if name.strip()}
    categories: List[CategoryInfo] = []
    for child in sorted(source_root.iterdir(), key=lambda x: x.name):
        if not child.is_dir():
            continue
        if child.name.startswith("."):
            continue
        if child.name in ignored:
            continue
        categories.append(
            CategoryInfo(
                name=child.name,
                slug=slugify(child.name),
                path=child,
            )
        )
    return categories


def infer_album_name(path_candidate: Optional[Path], csv_path: Path, content: str) -> str:
    """优先从路径推断相册名，失败时回退到 CSV 目录名或内容摘要。"""
    if path_candidate is not None:
        parts = path_candidate.parts
        if "images" in parts:
            idx = parts.index("images")
            if idx > 0:
                return parts[idx - 1]
        if len(parts) >= 2:
            return parts[-2]

    folder_name = csv_path.parent.name
    if folder_name:
        return folder_name

    content = normalize_text(content)
    return (content[:20] + "...") if len(content) > 20 else (content or "未分类")


def resolve_image_path(
    local_path_raw: str,
    file_name: str,
    csv_path: Path,
    source_root: Path,
    filename_index: Dict[str, List[Path]],
) -> Optional[Path]:
    normalized = normalize_path_text(local_path_raw)
    candidates: List[Path] = []

    if normalized:
        base = Path(normalized)
        candidates.append(base)
        if not base.is_absolute():
            candidates.append(csv_path.parent / base)
            candidates.append(source_root / base)

    if file_name:
        candidates.append(csv_path.parent / "images" / file_name)

    seen = set()
    for candidate in candidates:
        if candidate is None:
            continue
        try:
            resolved = candidate.expanduser().resolve(strict=False)
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.exists() and resolved.is_file():
            return resolved

    # 路径完全不可用时，用文件名索引兜底。
    # 若同名文件存在多份，优先选择与当前 CSV 目录最接近的文件，避免跨相册串图。
    if file_name and file_name in filename_index:
        same_folder_first = []
        csv_parent = csv_path.parent.resolve()
        for matched in filename_index[file_name]:
            try:
                matched.resolve().relative_to(csv_parent)
                same_folder_first.append(matched)
            except ValueError:
                continue

        if same_folder_first:
            return same_folder_first[0]
        return filename_index[file_name][0]

    return None


def sort_key(record: PhotoRecord) -> Tuple[datetime, int, str]:
    sentinel = datetime.max if record.publish_time is None else record.publish_time
    return sentinel, record.index, record.file_name


def format_dt(dt: Optional[datetime]) -> str:
    if dt is None:
        return "未知时间"
    return dt.strftime("%Y-%m-%d %H:%M")


def group_photos_by_description(photos: List[PhotoRecord]) -> List[Dict[str, object]]:
    """
    将同一分类下“发布内容”一致的照片归并为同一板块。
    输入 photos 默认已按发布时间排好序，分组保持首次出现顺序。
    """
    groups: Dict[str, Dict[str, object]] = {}

    for photo in photos:
        description = normalize_text(photo.content) or "（无描述）"
        group = groups.get(description)
        if group is None:
            group = {
                "description": description,
                "photos": [],
                "authors": [],
                "first_time": photo.publish_time,
                "last_time": photo.publish_time,
                "photo_count": 0,
            }
            groups[description] = group

        group["photos"].append(photo)
        group["photo_count"] += 1

        if photo.author and photo.author not in group["authors"]:
            group["authors"].append(photo.author)

        if photo.publish_time is not None:
            first_time = group["first_time"]
            last_time = group["last_time"]
            if first_time is None or photo.publish_time < first_time:
                group["first_time"] = photo.publish_time
            if last_time is None or photo.publish_time > last_time:
                group["last_time"] = photo.publish_time

    payload: List[Dict[str, object]] = []
    for group in groups.values():
        first_time = group["first_time"]
        last_time = group["last_time"]
        if first_time is None and last_time is None:
            time_text = "未知时间"
        elif first_time == last_time:
            time_text = format_dt(first_time)
        else:
            time_text = f"{format_dt(first_time)} ~ {format_dt(last_time)}"

        authors = group["authors"]
        author_text = "、".join(authors) if authors else "未知发布人"
        group["time_text"] = time_text
        group["author_text"] = author_text
        payload.append(group)

    return payload


def group_recent_posts(records: List[PhotoRecord]) -> List[Dict[str, object]]:
    """
    将首页“最近更新”按同一分类、发布人、发布时间、发布内容聚合成单条帖子。
    这样同一条内容下的多张图会合并展示，而不是重复渲染多张卡片。
    """
    groups: Dict[Tuple[str, str, str, str], Dict[str, object]] = {}

    for record in records:
        key = (
            record.album_name,
            normalize_text(record.author),
            normalize_text(record.publish_time_raw),
            normalize_text(record.content),
        )

        group = groups.get(key)
        if group is None:
            group = {
                "album_name": record.album_name,
                "author": record.author or "未知发布人",
                "content": record.content or "（无描述）",
                "publish_time": record.publish_time,
                "publish_time_text": format_dt(record.publish_time),
                "photos": [],
                "gallery_images": [],
            }
            groups[key] = group

        group["photos"].append(record)
        if record.site_image_rel:
            group["gallery_images"].append(
                {
                    "src": record.site_image_rel,
                    "alt": record.content or record.album_name or record.file_name,
                }
            )

        latest_time = group["publish_time"]
        if latest_time is None or (record.publish_time is not None and record.publish_time > latest_time):
            group["publish_time"] = record.publish_time
            group["publish_time_text"] = format_dt(record.publish_time)

    payload: List[Dict[str, object]] = []
    for group in groups.values():
        gallery_images = group["gallery_images"]
        group["photo_count"] = len(group["photos"])
        group["preview_images"] = gallery_images[:9]
        group["hidden_photo_count"] = max(0, len(gallery_images) - 9)
        group["gallery_json"] = json.dumps(gallery_images, ensure_ascii=False)
        payload.append(group)

    payload.sort(
        key=lambda item: (
            item["publish_time"] or datetime.min,
            item["photo_count"],
            item["album_name"],
        ),
        reverse=True,
    )
    return payload


def copy_asset(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)


def unique_filename(target_dir: Path, name: str) -> str:
    """避免同目录重名覆盖。"""
    candidate = name
    stem = Path(name).stem
    suffix = Path(name).suffix
    seq = 1
    while (target_dir / candidate).exists():
        candidate = f"{stem}_{seq}{suffix}"
        seq += 1
    return candidate


def build_records(
    source_root: Path,
    csv_files: List[Path],
    category_names: Iterable[str],
) -> Tuple[List[PhotoRecord], List[BuildWarning]]:
    filename_index = build_filename_index(source_root)
    category_name_set = set(category_names)
    records: List[PhotoRecord] = []
    warnings: List[BuildWarning] = []

    for csv_file in csv_files:
        try:
            rows = read_csv_rows(csv_file)
        except Exception as exc:  # noqa: BLE001
            warnings.append(
                BuildWarning(
                    code="csv_read_error",
                    message=f"读取 CSV 失败: {exc}",
                    csv_file=str(csv_file),
                    row_number=0,
                )
            )
            continue

        for row_number, row in rows:
            file_name = normalize_text(pick(row, HEADER_ALIASES["file_name"]))
            local_path_raw = pick(row, HEADER_ALIASES["local_path"])
            author = normalize_text(pick(row, HEADER_ALIASES["author"]))
            publish_time_raw = pick(row, HEADER_ALIASES["publish_time"])
            content = normalize_text(pick(row, HEADER_ALIASES["content"]))
            preview = normalize_text(pick(row, HEADER_ALIASES["preview"]))
            comment_text = normalize_text(pick(row, HEADER_ALIASES["comment_text"]))
            index = parse_int(pick(row, HEADER_ALIASES["index"]), default=row_number - 1)
            comment_count = parse_int(pick(row, HEADER_ALIASES["comment_count"]), default=0)

            publish_time = parse_time(publish_time_raw)
            if publish_time is None and normalize_text(publish_time_raw):
                warnings.append(
                    BuildWarning(
                        code="bad_publish_time",
                        message=f"无法解析时间: {publish_time_raw}",
                        csv_file=str(csv_file),
                        row_number=row_number,
                    )
                )

            source_path = resolve_image_path(
                local_path_raw=local_path_raw,
                file_name=file_name,
                csv_path=csv_file,
                source_root=source_root,
                filename_index=filename_index,
            )

            csv_category = csv_file.parent.name
            if csv_category in category_name_set:
                album_name = csv_category
            else:
                album_name = infer_album_name(source_path, csv_file, content)
            album_slug = slugify(album_name)

            record = PhotoRecord(
                index=index,
                file_name=file_name,
                local_path_raw=normalize_text(local_path_raw),
                source_path=source_path,
                preview=preview,
                author=author,
                publish_time_raw=normalize_text(publish_time_raw),
                publish_time=publish_time,
                content=content,
                comment_count=comment_count,
                comment_text=comment_text,
                album_name=album_name,
                album_slug=album_slug,
                source_csv=csv_file,
            )

            if source_path is None:
                record.missing_image = True
                warnings.append(
                    BuildWarning(
                        code="missing_image",
                        message=f"图片不存在，文件名={file_name}，原路径={record.local_path_raw}",
                        csv_file=str(csv_file),
                        row_number=row_number,
                    )
                )

            records.append(record)

    return records, warnings


def write_static_files(site_root: Path, static_root: Path) -> None:
    css_target = site_root / "assets" / "css" / "style.css"
    js_target = site_root / "assets" / "js" / "site.js"
    copy_asset(static_root / "style.css", css_target)
    copy_asset(static_root / "site.js", js_target)


def render_html_site(
    env: Environment,
    site_root: Path,
    categories: List[CategoryInfo],
    records_by_album: Dict[str, List[PhotoRecord]],
    all_records_sorted: List[PhotoRecord],
    site_title: str,
) -> None:
    site_root.mkdir(parents=True, exist_ok=True)
    (site_root / "albums").mkdir(parents=True, exist_ok=True)

    index_tmpl = env.get_template("index.html.j2")
    album_tmpl = env.get_template("album.html.j2")

    albums_payload = []
    for category in categories:
        photos = records_by_album.get(category.name, [])
        first_cover = next((p.site_image_rel for p in photos if p.site_image_rel), None)
        latest = max((p.publish_time for p in photos if p.publish_time is not None), default=None)
        albums_payload.append(
            {
                "name": category.name,
                "slug": category.slug,
                "count": len(photos),
                "latest": latest,
                "latest_text": format_dt(latest),
                "cover": first_cover,
            }
        )

    featured_albums = sorted(
        albums_payload,
        key=lambda item: (
            item["count"],
            item["latest"] or datetime.min,
        ),
        reverse=True,
    )[:4]

    recent_posts = group_recent_posts(all_records_sorted)[:18]

    index_html = index_tmpl.render(
        site_title=site_title,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        albums=albums_payload,
        timeline=all_records_sorted,
        featured_albums=featured_albums,
        recent_posts=recent_posts,
        format_dt=format_dt,
    )
    (site_root / "index.html").write_text(index_html, encoding="utf-8")

    for category in categories:
        photos = records_by_album.get(category.name, [])
        photo_groups = group_photos_by_description(photos)
        album_cover = next((p.site_image_rel for p in photos if p.site_image_rel), None)
        latest = max((p.publish_time for p in photos if p.publish_time is not None), default=None)
        album_html = album_tmpl.render(
            site_title=site_title,
            album_name=category.name,
            album_slug=category.slug,
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            photos=photos,
            photo_groups=photo_groups,
            album_cover=album_cover,
            latest_text=format_dt(latest),
            format_dt=format_dt,
        )
        (site_root / "albums" / f"{category.slug}.html").write_text(
            album_html,
            encoding="utf-8",
        )


def render_hugo_markdown(
    hugo_root: Path,
    categories: List[CategoryInfo],
    records_by_album: Dict[str, List[PhotoRecord]],
    site_title: str,
) -> None:
    content_root = hugo_root / "content" / "albums"
    content_root.mkdir(parents=True, exist_ok=True)

    index_md = "\n".join(
        [
            "---",
            f'title: "{site_title}"',
            "---",
            "",
            "# 相册目录",
            "",
        ]
    )

    index_lines = [index_md]
    for category in categories:
        index_lines.append(f"- [{category.name}](/albums/{category.slug}/)")

    (hugo_root / "content" / "_index.md").write_text(
        "\n".join(index_lines) + "\n", encoding="utf-8"
    )

    for category in categories:
        photos = records_by_album.get(category.name, [])
        photo_groups = group_photos_by_description(photos)
        album_dir = content_root / category.slug
        album_dir.mkdir(parents=True, exist_ok=True)

        lines: List[str] = [
            "---",
            f'title: "{category.name}"',
            "---",
            "",
            f"# {category.name}",
            "",
        ]

        if not photos:
            lines.extend(["（该分类暂时没有可展示图片）", ""])

        for group in photo_groups:
            lines.append(f"## {group['description']}")
            lines.append("")
            lines.append(
                f"时间范围：{group['time_text']}  \n发布人：{group['author_text']}  \n图片数：{group['photo_count']}"
            )
            lines.append("")

            for photo in group["photos"]:
                if photo.hugo_image_rel:
                    lines.append(f"![{photo.file_name or 'photo'}]({photo.hugo_image_rel})")
                    lines.append("")
                if photo.comment_count:
                    lines.append(f"评论数：{photo.comment_count}")
                if photo.comment_text:
                    lines.append(f"评论内容：{photo.comment_text}")
                if photo.comment_count or photo.comment_text:
                    lines.append("")

        (album_dir / "index.md").write_text("\n".join(lines), encoding="utf-8")

    hugo_toml = "\n".join(
        [
            f'baseURL = "https://example.com/"',
            f'languageCode = "zh-cn"',
            f'title = "{site_title}"',
            "",
            "[markup]",
            "  [markup.goldmark]",
            "    [markup.goldmark.renderer]",
            "      unsafe = true",
            "",
        ]
    )
    (hugo_root / "hugo.toml").write_text(hugo_toml, encoding="utf-8")


def export_report(
    output_root: Path,
    categories: List[CategoryInfo],
    records: List[PhotoRecord],
    warnings: List[BuildWarning],
    csv_files: List[Path],
) -> None:
    report_dir = output_root / "logs"
    report_dir.mkdir(parents=True, exist_ok=True)

    by_album: Dict[str, int] = {category.name: 0 for category in categories}
    missing_count = 0
    for record in records:
        by_album[record.album_name] = by_album.get(record.album_name, 0) + 1
        if record.missing_image:
            missing_count += 1

    report = {
        "generated_at": datetime.now().isoformat(),
        "csv_files": [str(p) for p in csv_files],
        "total_records": len(records),
        "missing_images": missing_count,
        "warning_count": len(warnings),
        "albums": dict(sorted(by_album.items(), key=lambda item: item[0])),
    }

    (report_dir / "build_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    warning_payload = [warning.__dict__ for warning in warnings]
    (report_dir / "warnings.json").write_text(
        json.dumps(warning_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    source_root = Path(args.source_root).expanduser().resolve()
    output_root = Path(args.output_root).expanduser().resolve()
    script_root = Path(__file__).resolve().parent

    if not source_root.exists() or not source_root.is_dir():
        print(f"[ERROR] source-root 不存在或不是目录: {source_root}")
        return 1

    ignore_dirs = [name.strip() for name in args.ignore_dirs.split(",")]
    categories = discover_categories(source_root=source_root, ignore_dirs=ignore_dirs)
    if not categories:
        print("[ERROR] 未发现任何分类目录，请检查 source-root 与 ignore-dirs")
        return 1

    csv_files: List[Path] = []
    for category in categories:
        csv_files.extend(sorted(category.path.glob(args.csv_pattern)))

    if not csv_files:
        print(f"[ERROR] 未找到 CSV 文件，匹配模式: {args.csv_pattern}")
        return 1

    if args.clean_output and output_root.exists():
        shutil.rmtree(output_root)

    output_root.mkdir(parents=True, exist_ok=True)
    site_root = output_root / "site"
    hugo_root = output_root / "hugo"

    records, warnings = build_records(
        source_root=source_root,
        csv_files=csv_files,
        category_names=[category.name for category in categories],
    )
    if not records:
        print("[ERROR] 未解析到任何记录")
        return 1

    records.sort(key=sort_key, reverse=(args.sort_order == "desc"))

    # 先按相册分组，方便后续生成页面与 Markdown。
    records_by_album: Dict[str, List[PhotoRecord]] = {category.name: [] for category in categories}
    for record in records:
        records_by_album.setdefault(record.album_name, []).append(record)

    # 拷贝图片到静态目录，并更新每条记录的站内路径。
    for category in categories:
        photos = records_by_album.get(category.name, [])
        album_slug = category.slug
        site_image_album_dir = site_root / "assets" / "images" / album_slug
        hugo_image_album_dir = hugo_root / "static" / "images" / album_slug

        for photo in photos:
            if photo.source_path is None or not photo.source_path.exists():
                continue

            safe_name = unique_filename(site_image_album_dir, photo.source_path.name)
            site_target = site_image_album_dir / safe_name
            hugo_target = hugo_image_album_dir / safe_name

            copy_asset(photo.source_path, site_target)
            copy_asset(photo.source_path, hugo_target)

            photo.site_image_rel = f"assets/images/{album_slug}/{safe_name}"
            photo.hugo_image_rel = f"/images/{album_slug}/{safe_name}"

    env = create_env(script_root / "templates")
    write_static_files(site_root, script_root / "static")
    render_html_site(
        env=env,
        site_root=site_root,
        categories=categories,
        records_by_album=records_by_album,
        all_records_sorted=records,
        site_title=args.site_title,
    )
    render_hugo_markdown(
        hugo_root=hugo_root,
        categories=categories,
        records_by_album=records_by_album,
        site_title=args.site_title,
    )

    export_report(
        output_root=output_root,
        categories=categories,
        records=records,
        warnings=warnings,
        csv_files=csv_files,
    )

    print("[OK] 构建完成")
    print(f"source_root: {source_root}")
    print(f"output_root: {output_root}")
    print(f"categories: {len(categories)}")
    print(f"csv_files: {len(csv_files)}")
    print(f"records: {len(records)}")
    print(f"warnings: {len(warnings)}")
    print(f"site: {site_root}")
    print(f"hugo: {hugo_root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
