/**
 * folark - 详情模态框组件：documentDetail
 */
document.addEventListener('alpine:init', () => {
    Alpine.data('documentDetail', () => ({
        showHash: false,
        downloadOpen: false,
        previewOpen: false,
        showTagInput: false,
        newTagName: '',
        availableTags: [],
        // 格式选择相关状态
        previewFormats: [],
        downloadFormats: [],
        selectedPreviewFormat: '',
        selectedDownloadFormat: '',
        showPreviewDropdown: false,
        showDownloadDropdown: false,
        // 行内编辑状态
        editingField: null,
        editValue: '',
        editSaving: false,
        // 缩略图上传状态
        thumbnailUploading: false,
        // 缩略图缓存破坏时间戳（按 uuid）
        thumbnailTimestamps: {},

        init() {
            // 加载可用标签列表
            this.loadTags();
            // 监听 documentApp 发出的详情打开事件，同步格式数据
            this.$watch('$store.docs.currentDoc', (doc) => {
                if (doc) {
                    this.showTagInput = false;
                    this.newTagName = '';
                    this.previewFormats = doc.preview_formats || [];
                    this.downloadFormats = doc.download_formats || [];
                    this.selectedPreviewFormat = this.previewFormats[0] || '';
                    this.selectedDownloadFormat = this.downloadFormats[0] || '';
                    this.showPreviewDropdown = false;
                    this.showDownloadDropdown = false;
                }
            });
        },

        async loadTags() {
            try {
                const resp = await fetch('/api/tags/');
                if (resp.ok) {
                    this.availableTags = await resp.json();
                }
            } catch (e) {
                console.error('加载标签列表失败:', e);
            }
        },

        // 打开详情
        async open(uuid) {
            const store = this.$store.docs;
            store.loading = true;

            try {
                const resp = await fetch(`/api/documents/${uuid}`);
                if (!resp.ok) throw new Error('获取文档详情失败');

                const doc = await resp.json();
                store.currentDoc = doc;
                this.showTagInput = false;
                this.newTagName = '';

                // 初始化格式选择状态
                this.previewFormats = doc.preview_formats || [];
                this.downloadFormats = doc.download_formats || [];
                this.selectedPreviewFormat = this.previewFormats[0] || '';
                this.selectedDownloadFormat = this.downloadFormats[0] || '';
                this.showPreviewDropdown = false;
                this.showDownloadDropdown = false;
            } catch (e) {
                console.error('获取文档详情失败:', e);
            } finally {
                store.loading = false;
            }
        },

        // 关闭模态框
        close() {
            this.$store.docs.currentDoc = null;
            this.showTagInput = false;
        },

        // 移除标签
        async removeTag(tagUuid) {
            const doc = this.$store.docs.currentDoc;
            if (!doc) return;

            try {
                const resp = await fetch(`/api/documents/${doc.uuid}/tags/${tagUuid}`, {
                    method: 'DELETE'
                });

                if (!resp.ok) throw new Error('移除标签失败');

                // 重新获取文档详情
                await this.open(doc.uuid);

                // 刷新列表中的标签
                window.dispatchEvent(new CustomEvent('refresh-list'));
            } catch (e) {
                console.error('移除标签失败:', e);
            }
        },

        // 添加标签
        async addTag(tagName) {
            const doc = this.$store.docs.currentDoc;
            if (!doc || !tagName.trim()) return;

            try {
                const resp = await fetch(`/api/documents/${doc.uuid}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ add_tags: [tagName.trim()] })
                });

                if (!resp.ok) throw new Error('添加标签失败');

                const updatedDoc = await resp.json();
                this.$store.docs.currentDoc = updatedDoc;
                this.newTagName = '';
                this.showTagInput = false;

                // 刷新列表
                window.dispatchEvent(new CustomEvent('refresh-list'));
            } catch (e) {
                console.error('添加标签失败:', e);
            }
        },

        // 删除文档
        async deleteDocument() {
            const doc = this.$store.docs.currentDoc;
            if (!doc) return;

            if (!confirm('确定要删除这个文档吗？仅删除数据库记录，不删除源文件。此操作不可恢复。')) {
                return;
            }

            try {
                const resp = await fetch('/api/documents/batch-delete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ uuids: [doc.uuid] })
                });

                if (!resp.ok) throw new Error('删除文档失败');

                // 关闭模态框并刷新列表
                this.close();
                window.dispatchEvent(new CustomEvent('refresh-list'));
            } catch (e) {
                console.error('删除文档失败:', e);
            }
        },

        // 生成预览 URL
        previewUrl(format = null) {
            const doc = this.$store.docs.currentDoc;
            if (!doc) return '';

            let url = `/api/documents/${doc.uuid}/preview`;
            if (format && format !== doc.file_type) {
                url += `?target_type=${encodeURIComponent(format)}`;
            }
            return url;
        },

        // 生成下载 URL
        downloadUrl(format = null) {
            const doc = this.$store.docs.currentDoc;
            if (!doc) return '';

            let url = `/api/documents/${doc.uuid}/download`;
            if (format && format !== doc.file_type) {
                url += `?target_type=${encodeURIComponent(format)}`;
            }
            return url;
        },

        // 获取文件图标 URL
        getFileIconUrl(fileType) {
            return getFileIconUrl(fileType);
        },

        // 获取缩略图 URL
        getThumbnailUrl(uuid) {
            const ts = this.thumbnailTimestamps[uuid];
            return getThumbnailUrl(uuid, ts);
        },

        // --- 缩略图上传 ---

        // 触发文件选择
        triggerThumbnailUpload() {
            const input = document.createElement('input');
            input.type = 'file';
            input.accept = 'image/*';
            input.onchange = (e) => {
                const file = e.target.files[0];
                if (file) {
                    this.uploadThumbnail(file);
                }
            };
            input.click();
        },

        // 上传缩略图
        async uploadThumbnail(file) {
            const doc = this.$store.docs.currentDoc;
            if (!doc) return;

            // 校验文件类型
            if (!file.type.startsWith('image/')) {
                alert('请选择图片文件');
                return;
            }

            this.thumbnailUploading = true;
            try {
                const formData = new FormData();
                formData.append('data', file);

                const resp = await fetch(`/api/documents/${doc.uuid}/thumbnail`, {
                    method: 'POST',
                    body: formData,
                });

                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({ detail: '上传失败' }));
                    throw new Error(err.detail || '上传失败');
                }

                const updatedDoc = await resp.json();
                this.thumbnailTimestamps[updatedDoc.uuid] = Date.now();
                this.$store.docs.currentDoc = updatedDoc;
                showToast('缩略图更新成功');

                // 刷新列表以显示新缩略图
                window.dispatchEvent(new CustomEvent('refresh-list'));
            } catch (e) {
                console.error('缩略图上传失败:', e);
                alert('缩略图上传失败: ' + e.message);
            } finally {
                this.thumbnailUploading = false;
            }
        },

        // --- 行内编辑 ---

        // 获取字段当前值（用于初始化编辑值）
        _getFieldValue(field) {
            const doc = this.$store.docs.currentDoc;
            if (!doc) return '';
            if (field === 'authors') {
                // authors 为 JSON 字符串或数组，转为逗号分隔字符串
                let val = doc.authors;
                if (!val) return '';
                if (typeof val === 'string') {
                    try { val = JSON.parse(val); } catch { return val; }
                }
                return Array.isArray(val) ? val.join(', ') : String(val);
            }
            if (field === 'meta_data') {
                let val = doc.meta_data;
                if (!val) return '';
                if (typeof val === 'string') {
                    try { return JSON.stringify(JSON.parse(val), null, 2); } catch { return val; }
                }
                return JSON.stringify(val, null, 2);
            }            if (field === 'title') {
                return getDisplayTitle(doc.title, doc.file_name);
            }            return doc[field] || '';
        },

        // 获取字段显示值（用于展示态）
        getDisplayValue(field) {
            const doc = this.$store.docs.currentDoc;
            if (!doc) return '';
            if (field === 'authors') {
                let val = doc.authors;
                if (!val) return '';
                if (typeof val === 'string') {
                    try { val = JSON.parse(val); } catch { return val; }
                }
                return Array.isArray(val) ? val.join(', ') : String(val);
            }
            if (field === 'meta_data') {
                let val = doc.meta_data;
                if (!val) return '';
                if (typeof val === 'string') {
                    try { val = JSON.parse(val); return JSON.stringify(val, null, 2); } catch { return val; }
                }
                return JSON.stringify(val, null, 2);
            }
            return doc[field] || '';
        },

        startEdit(field) {
            this.editingField = field;
            this.editValue = this._getFieldValue(field);
            this.$nextTick(() => {
                const el = document.querySelector('[x-ref="editInput"]') || document.querySelector('[x-ref="editTextarea"]');
                if (el) el.focus();
            });
        },

        cancelEdit() {
            this.editingField = null;
            this.editValue = '';
        },

        async saveEdit(field) {
            const doc = this.$store.docs.currentDoc;
            if (!doc || this.editSaving) return;

            let payload = {};
            if (field === 'authors') {
                // 将逗号分隔字符串转为 JSON 数组
                const arr = this.editValue.split(/[,，]/).map(s => s.trim()).filter(Boolean);
                payload.authors = arr;
            } else if (field === 'meta_data') {
                try {
                    payload.meta_data = this.editValue.trim() ? JSON.parse(this.editValue) : null;
                } catch {
                    alert('meta_data 必须是合法的 JSON 格式');
                    return;
                }
            } else {
                payload[field] = this.editValue;
            }

            this.editSaving = true;
            try {
                const resp = await fetch(`/api/documents/${doc.uuid}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                if (!resp.ok) throw new Error('保存失败');
                const updatedDoc = await resp.json();
                this.$store.docs.currentDoc = updatedDoc;
                this.editingField = null;
                this.editValue = '';
                // 刷新列表（标题可能在列表中显示）
                window.dispatchEvent(new CustomEvent('refresh-list'));
            } catch (e) {
                console.error('保存字段失败:', e);
                alert('保存失败，请重试');
            } finally {
                this.editSaving = false;
            }
        }
    }));
});
