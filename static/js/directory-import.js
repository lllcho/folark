/**
 * folark - 目录导入组件：directoryImport
 */
document.addEventListener('alpine:init', () => {
    Alpine.data('directoryImport', () => ({
        importPath: '',
        isImporting: false,
        importResult: null,
        importSuccess: false,
        errorMsg: null,
        totalFiles: 0,
        processedFiles: 0,
        _abortController: null,

        async submit() {
            if (!this.importPath.trim()) {
                this.errorMsg = '请输入目录路径';
                return;
            }

            // 重置状态
            this.isImporting = true;
            this.importResult = null;
            this.importSuccess = false;
            this.errorMsg = null;
            this.totalFiles = 0;
            this.processedFiles = 0;

            const url = '/api/import-directory?path=' + encodeURIComponent(this.importPath.trim());
            this._abortController = new AbortController();

            try {
                const resp = await fetch(url, { signal: this._abortController.signal });
                if (!resp.ok) {
                    let detail = '导入失败';
                    try { detail = (await resp.json()).detail || detail; } catch {}
                    this.errorMsg = detail;
                    this.isImporting = false;
                    return;
                }

                const reader = resp.body.getReader();
                const decoder = new TextDecoder();
                let buffer = '';

                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;

                    buffer += decoder.decode(value, { stream: true });

                    // 按双换行拆分 SSE 事件
                    const parts = buffer.split('\n\n');
                    buffer = parts.pop(); // 保留不完整的部分

                    for (const part of parts) {
                        if (!part.trim()) continue;
                        this._handleSSEEvent(part);
                    }
                }

                // 处理剩余 buffer
                if (buffer.trim()) {
                    this._handleSSEEvent(buffer);
                }

                // 流结束但没收到 done 事件
                if (this.isImporting) {
                    this.isImporting = false;
                }
            } catch (e) {
                if (e.name === 'AbortError') return;
                this.errorMsg = '连接中断，导入可能未完成';
                this.isImporting = false;
            }
        },

        _handleSSEEvent(raw) {
            let eventType = 'message';
            let dataStr = '';
            for (const line of raw.split('\n')) {
                if (line.startsWith('event: ')) {
                    eventType = line.slice(7).trim();
                } else if (line.startsWith('data: ')) {
                    dataStr = line.slice(6);
                }
            }
            if (!dataStr) return;

            let data;
            try { data = JSON.parse(dataStr); } catch { return; }

            if (eventType === 'total') {
                this.totalFiles = data.total;
            } else if (eventType === 'progress') {
                this.processedFiles = data.index;
            } else if (eventType === 'done') {
                this.importResult = data.message;
                this.importSuccess = true;
                this.isImporting = false;
                this.importPath = '';
                window.dispatchEvent(new CustomEvent('refresh-list'));
            } else if (eventType === 'error_event') {
                this.errorMsg = data.detail || '导入失败';
                this.isImporting = false;
            }
        },

        destroy() {
            if (this._abortController) {
                this._abortController.abort();
                this._abortController = null;
            }
        }
    }));
});
