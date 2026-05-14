# 群相册静态站点生成器

这个工具会把本地导出的 `*_发布内容表.csv` 解析成两套可发布产物：

1. `dist/site/`：纯静态 HTML/CSS/JS（可直接部署到 Cloudflare Pages）
2. `dist/hugo/`：Hugo 兼容 Markdown + `static/images`

分类规则：
- 默认以 `--source-root` 下的一级文件夹作为相册分类来源
- 即使某个分类当前 CSV 为空，也会在 UI 中显示该分类入口
- 同一分类内会按 `发布内容` 聚合为同一板块（同描述归组）

## 目录结构

```text
album-site-generator/
├── build_album_site.py
├── requirements.txt
├── templates/
│   ├── index.html.j2
│   └── album.html.j2
├── static/
│   ├── style.css
│   └── site.js
└── README.md
```

## 环境要求

- Python 3.10+
- 可写本地磁盘空间（用于复制图片）

安装依赖：

```bash
cd album-site-generator
python3 -m pip install -r requirements.txt
```

## 一键构建

在相册数据根目录执行（你的相册目录和 CSV 所在目录）：

```bash
cd /Users/lazywords/Code/QQ群相册
python3 album-site-generator/build_album_site.py \
  --source-root . \
  --output-root ./dist \
  --site-title "QQ群相册" \
  --sort-order asc \
  --ignore-dirs "dist,album-site-generator,qzone-album-mcp" \
  --clean-output
```

构建后输出：

- `dist/site/index.html`：站点首页（相册目录 + 全局时间轴）
- `dist/site/albums/*.html`：相册瀑布流页面
- `dist/site/assets/images/...`：复制后的静态图片
- `dist/hugo/content/albums/*/index.md`：Hugo 页面内容
- `dist/hugo/static/images/...`：Hugo 静态图片
- `dist/logs/build_report.json`：汇总报告
- `dist/logs/warnings.json`：异常明细

## 异常处理策略

脚本内置以下容错逻辑：

- 图片缺失：记录 `missing_image` 告警，不中断构建
- 路径异常：尝试多种路径候选（绝对路径、相对路径、`images/文件名`、按文件名索引兜底）
- 编码异常：CSV 依次尝试 `utf-8-sig`、`utf-8`、`gb18030`
- 时间格式异常：记录 `bad_publish_time` 告警，保留记录并将时间标记为“未知时间”

## Cloudflare Pages 免费部署

### 方式 A：直接托管纯静态目录（推荐）

1. 新建 Git 仓库，将 `dist/site/` 内容作为仓库根目录提交。
2. 在 Cloudflare Pages 连接该仓库。
3. Build 设置：
   - Framework preset: `None`
   - Build command: 留空
   - Build output directory: `/`
4. 部署完成后即可访问。

### 方式 B：Cloudflare Pages 从生成脚本自动构建

如果你希望每次 push 自动构建：

- 仓库保留 `album-site-generator/` 和原始数据目录
- 在 Pages 配置：
  - Build command:
    ```bash
    python3 album-site-generator/build_album_site.py --source-root . --output-root ./dist --site-title "QQ群相册" --sort-order asc --clean-output
    ```
  - Build output directory:
    ```text
    dist/site
    ```

## Hugo 使用方法（可选）

如果想继续用 Hugo 模板体系：

```bash
cd dist/hugo
hugo server
```

> 首次使用需本地安装 Hugo。

## 常见参数

- `--csv-pattern`: 默认 `*_发布内容表.csv`
- `--sort-order`: `asc`（升序）或 `desc`（降序）
- `--clean-output`: 构建前删除输出目录
- `--ignore-dirs`: 忽略的一级目录名（逗号分隔）

## 说明

- 脚本不会修改你的原始 CSV 和图片文件，只会读取并复制。
- 如果图片总量很大，首次构建时间主要花在图片复制阶段。
