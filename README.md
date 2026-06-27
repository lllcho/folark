# folark

> 本地优先的个人文档管理工具

folark 是一个**本地优先**的文档管理 Web 应用，支持多种文件格式的上传、预览、搜索和标签管理。所有数据存储在你自己的机器上，无需依赖任何云服务。

![Python](https://img.shields.io/badge/Python-3.12+-blue)
![License](https://img.shields.io/badge/License-AGPL--3.0-green)

---

## ✨ 功能特性

- **📄 多格式支持** — PDF、DOCX、XLSX、PPTX、EPUB、纯文本、图片、音视频、压缩包等 60+ 种文件格式
- **🔍 全文搜索** — 基于 SQLite FTS5 的全文索引，快速检索文档内容
- **🏷️ 标签管理** — 自定义标签，灵活分类和过滤文档
- **👁️ 在线预览** — 支持文档（PDF/DOCX/EPUB）、图片、音频、视频、压缩包等多种格式在线预览
- **📦 批量导入** — 支持目录批量导入和压缩包导入
- **🔌 插件系统** — 可扩展的插件架构，方便添加新的文件处理器
- **🔒 可选认证** — 可配置的密码认证，保护你的文档库
- **🐳 Docker 部署** — 一键 Docker 部署

## 📋 支持的格式

| 类别 | 格式 |
|------|------|
| **文档** | PDF, DOCX, XLSX, PPTX |
| **电子书** | EPUB, MOBI, AZW3, FB2 |
| **文本** | TXT, Markdown, JSON, YAML, XML, TOML, HTML, CSS, JS, TS, 代码文件等 |
| **图片** | JPG, PNG, GIF, BMP, WebP, SVG, TIFF |
| **音频** | MP3, WAV, FLAC, AAC, M4A |
| **视频** | MP4, WebM, OGG, MOV, M4V |
| **压缩包** | ZIP, RAR, 7z, TAR, GZ, BZ2, XZ |

## 🚀 快速开始

### 前置要求

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)（推荐）或 pip

### 本地运行

```bash
# 1. 克隆仓库
git clone https://github.com/lllcho/folark.git
cd folark

# 2. 创建虚拟环境并安装依赖
uv venv
uv sync

# 3. 启动服务
./run.sh
```

服务启动后，访问 **http://localhost:8890** 即可使用。

### Docker 部署（推荐）

```bash
# 1. 克隆仓库
git clone https://github.com/lllcho/folark.git
cd folark

# 2. （可选）配置环境变量
cp .env.example .env
# 编辑 .env 设置登录密码等

# 3. 一键启动
docker compose up -d
```

服务启动后，访问 **http://localhost:8890** 即可使用。

> **提示**：默认会从 ghcr.io 拉取预构建镜像。如果你想从本地 Dockerfile 构建（例如首次发布前），加上 `--build` 参数：
> ```bash
> docker compose up -d --build
> ```

### 配置认证（可选）

在项目根目录创建 `.env` 文件（可参考 `.env.example`）：

```env
AUTH_PASSWORD=your_password
```

设置后访问需要输入密码登录。也可通过 `docker-compose.yml` 的 `environment` 字段传入。

## ⚙️ 配置项

所有配置项可通过环境变量或 `.env` 文件设置：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PORT` | `8890` | 服务端口 |
| `DATA_ROOT` | `./data` | 数据存储根目录 |
| `AUTH_PASSWORD` | `""` | 登录密码（为空则不启用认证） |
| `LOG_LEVEL` | `DEBUG` | 日志级别 |
| `MAX_UPLOAD_SIZE` | `524288000` | 单次上传最大大小（500MB） |

## 🗂️ 项目结构

```
folark/
├── app/
│   ├── main.py              # 应用入口
│   ├── config.py            # 配置管理
│   ├── database.py          # 数据库管理（SQLite）
│   ├── api/                 # API 路由
│   │   ├── documents.py     # 文档 CRUD
│   │   ├── search.py        # 全文搜索
│   │   ├── tags.py          # 标签管理
│   │   ├── batch_jobs.py    # 批量任务
│   │   ├── plugins.py       # 插件管理
│   │   └── settings.py      # 设置管理
│   ├── plugins/             # 插件系统
│   │   ├── core.py          # 插件核心
│   │   ├── manager.py       # 插件管理器
│   │   └── builtin_plugin/  # 内置插件
│   ├── services/            # 业务逻辑层
│   │   ├── documents.py
│   │   ├── search.py
│   │   ├── ingestion.py
│   │   └── batch_jobs.py
│   └── templates/           # Jinja2 模板
├── static/                  # 静态文件
├── Dockerfile               # Docker 构建
├── docker-compose.yml       # Docker Compose
├── run.sh                   # 启动脚本
└── pyproject.toml           # 项目配置
```

## 🛠️ 技术栈

- **后端框架**: [Litestar](https://litestar.dev/) — 高性能异步 Python Web 框架
- **数据库**: SQLite + aiosqlite + FTS5 全文索引
- **模板引擎**: Jinja2
- **前端**: Alpine.js + HTMX
- **文档处理**: PyMuPDF、python-docx、openpyxl、python-pptx、ebooklib 等
- **部署**: Docker / Docker Compose

## 📜 许可证

本项目基于 [AGPL-3.0](./LICENSE) 许可证开源。
