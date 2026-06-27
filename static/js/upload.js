/**
 * folark - 上传组件：uploadZone
 */
document.addEventListener('alpine:init', () => {
    Alpine.data('uploadZone', () => ({
        isDragging: false,
        uploads: [],

        handleDrop(event) {
            this.isDragging = false;
            const files = event.dataTransfer.files;
            this.uploadFiles(files);
        },

        handleFileSelect(event) {
            const files = event.target.files;
            this.uploadFiles(files);
            event.target.value = ''; // Reset input
        },

        async uploadFiles(files) {
            for (const file of files) {
                const uploadId = Date.now() + '-' + Math.random().toString(36).substr(2, 9);
                this.uploads.push({
                    id: uploadId,
                    name: file.name,
                    progress: 0,
                    status: 'uploading',
                    error: null
                });

                // 从响应式数组中获取代理引用，确保后续修改能触发 Alpine 响应式更新
                const uploadItem = this.uploads[this.uploads.length - 1];

                try {
                    await this.uploadFile(file, uploadItem);
                    uploadItem.status = 'done';
                    // 触发刷新列表事件
                    window.dispatchEvent(new CustomEvent('refresh-list'));
                } catch (error) {
                    uploadItem.status = 'failed';
                    uploadItem.error = error.message || '上传失败';
                }
            }
        },

        async uploadFile(file, uploadItem) {
            const formData = new FormData();
            formData.append('data', file);

            return new Promise((resolve, reject) => {
                const xhr = new XMLHttpRequest();

                xhr.upload.addEventListener('progress', (e) => {
                    if (e.lengthComputable) {
                        uploadItem.progress = Math.round((e.loaded / e.total) * 100);
                    }
                });

                xhr.addEventListener('load', () => {
                    if (xhr.status >= 200 && xhr.status < 300) {
                        // 上传成功，服务器已经同步处理完成
                        resolve();
                    } else {
                        try {
                            const error = JSON.parse(xhr.responseText);
                            reject(new Error(error.detail || '上传失败'));
                        } catch {
                            reject(new Error('上传失败'));
                        }
                    }
                });

                xhr.addEventListener('error', () => reject(new Error('网络错误')));

                xhr.open('POST', '/api/upload');
                xhr.send(formData);
            });
        }
    }));
});
