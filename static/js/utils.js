/**
 * folark - 辅助函数
 */

/**
 * 格式化文件大小
 * @param {number} bytes - 字节数
 * @returns {string} 格式化后的字符串
 */
function formatFileSize(bytes) {
    if (bytes === null || bytes === undefined || isNaN(bytes)) {
        return '未知';
    }

    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let size = parseFloat(bytes);
    let unitIndex = 0;

    while (size >= 1024 && unitIndex < units.length - 1) {
        size /= 1024;
        unitIndex++;
    }

    return size.toFixed(2).replace(/\.00$/, '') + ' ' + units[unitIndex];
}

/**
 * 格式化日期
 * @param {string} dateStr - ISO 日期字符串
 * @returns {string} 格式化后的日期字符串
 */
function formatDate(dateStr) {
    if (!dateStr) return '';

    try {
        let date;
        if (dateStr.includes(' ') && !dateStr.includes('T')) {
            // SQLite datetime 格式 "YYYY-MM-DD HH:MM:SS"，存储的是 UTC 时间
            date = new Date(dateStr.replace(' ', 'T') + 'Z');
        } else if (dateStr.includes('T') && !dateStr.endsWith('Z') && !/[+-]\d{2}:?\d{2}$/.test(dateStr)) {
            // ISO 格式但无 Z 后缀（如 file_modified_time），按本地时间解析
            const [d, t] = dateStr.split('T');
            const [year, month, day] = d.split('-').map(Number);
            const [hour, minute, second] = (t || '00:00:00').split(':').map(Number);
            date = new Date(year, month - 1, day, hour, minute, second || 0);
        } else {
            date = new Date(dateStr);
        }
        return date.toLocaleString('zh-CN', {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        });
    } catch (e) {
        return dateStr;
    }
}

/**
 * 获取文件图标 URL
 * @param {string} fileType - 文件类型
 * @returns {string} 图标 URL
 */
function getFileIconUrl(fileType) {
    const iconMap = {
        'pdf': '/static/icons/pdf.svg',
        'docx': '/static/icons/docx.svg',
        'xlsx': '/static/icons/xlsx.svg',
        'pptx': '/static/icons/pptx.svg',
        'epub': '/static/icons/epub.svg',
        'txt': '/static/icons/txt.svg',
        'md': '/static/icons/md.svg',
        'csv': '/static/icons/txt.svg',
        'json': '/static/icons/txt.svg',
        'xml': '/static/icons/txt.svg',
        'yaml': '/static/icons/txt.svg',
        'yml': '/static/icons/txt.svg',
        'toml': '/static/icons/txt.svg',
        'ini': '/static/icons/txt.svg',
        'conf': '/static/icons/txt.svg',
        'cfg': '/static/icons/txt.svg',
        'log': '/static/icons/txt.svg',
        'rst': '/static/icons/txt.svg',
        'py': '/static/icons/txt.svg',
        'js': '/static/icons/txt.svg',
        'ts': '/static/icons/txt.svg',
        'html': '/static/icons/txt.svg',
        'htm': '/static/icons/txt.svg',
        'css': '/static/icons/txt.svg',
        'java': '/static/icons/txt.svg',
        'c': '/static/icons/txt.svg',
        'cpp': '/static/icons/txt.svg',
        'h': '/static/icons/txt.svg',
        'go': '/static/icons/txt.svg',
        'rs': '/static/icons/txt.svg',
        'sh': '/static/icons/txt.svg',
        'sql': '/static/icons/txt.svg',
        'mp4': '/static/icons/video.svg',
        'jpg': '/static/icons/image.svg',
        'jpeg': '/static/icons/image.svg',
        'png': '/static/icons/image.svg',
        'gif': '/static/icons/image.svg',
        'bmp': '/static/icons/image.svg',
        'webp': '/static/icons/image.svg',
        'tiff': '/static/icons/image.svg',
        'tif': '/static/icons/image.svg',
        'ico': '/static/icons/image.svg',
        'svg': '/static/icons/image.svg',
        'mp3': '/static/icons/audio.svg',
        'wav': '/static/icons/audio.svg',
        'flac': '/static/icons/audio.svg',
        'aac': '/static/icons/audio.svg',
        'm4a': '/static/icons/audio.svg',
        'ogg': '/static/icons/audio.svg',
        'zip': '/static/icons/zip.svg',
        'rar': '/static/icons/zip.svg',
        '7z': '/static/icons/zip.svg',
        'tar': '/static/icons/zip.svg',
        'gz': '/static/icons/zip.svg',
        'bz2': '/static/icons/zip.svg',
        'xz': '/static/icons/zip.svg'
    };

    return iconMap[fileType?.toLowerCase()] || '/static/icons/txt.svg';
}

/**
 * 获取缩略图 URL
 * @param {string} uuid - 文档 UUID
 * @param {number} [nocache] - 缓存破坏时间戳
 * @returns {string} 缩略图 URL
 */
function getThumbnailUrl(uuid, nocache) {
    if (!uuid) return '';
    const qs = nocache ? `?t=${nocache}` : '';
    return `/static/thumbnails/${uuid}.jpg${qs}`;
}

/**
 * 显示轻量 toast 提示
 * @param {string} message - 提示文本
 * @param {number} duration - 显示时长（毫秒），默认 3000
 */
function showToast(message, duration = 3000) {
    const el = document.createElement('div');
    el.textContent = message;
    el.style.cssText = 'position:fixed;bottom:2rem;left:50%;transform:translateX(-50%);z-index:9999;'
        + 'padding:0.75rem 1.5rem;border-radius:0.5rem;font-size:0.875rem;font-weight:500;'
        + 'background:rgba(17,24,39,0.9);color:#fff;box-shadow:0 4px 12px rgba(0,0,0,0.15);'
        + 'transition:opacity 0.3s;opacity:0;max-width:90vw;text-align:center;pointer-events:none;';
    document.body.appendChild(el);
    requestAnimationFrame(() => { el.style.opacity = '1'; });
    setTimeout(() => {
        el.style.opacity = '0';
        setTimeout(() => el.remove(), 300);
    }, duration);
}

// 导出辅助函数供全局使用
window.formatFileSize = formatFileSize;
window.formatDate = formatDate;
window.getFileIconUrl = getFileIconUrl;
window.getThumbnailUrl = getThumbnailUrl;
window.showToast = showToast;
