/**
 * folark - 主应用组件：documentApp
 */
document.addEventListener('alpine:init', () => {
    Alpine.data('documentApp', () => ({
        showSearchResults: false,
        searching: false,
        showFilters: false,
        activeFilter: 'all',
        activeExtension: '',
        activeTagUuid: '',
        availableTags: [],
        showModal: false,
        viewMode: localStorage.getItem('viewMode') || 'list',
        selectMode: false,
        selectedUuids: [],
        showBatchTagInput: false,
        batchTagName: '',
        showBatchExecuteModal: false,
        availableHandlers: [],
        selectedHandlers: [],
        batchExecuteLoading: false,
        _searchController: null,

        // 大类 -> 扩展名映射（由后端 config.py 通过模板注入）
        extensionMap: window.__extensionMap || {},

        // 当前大类下的扩展名列表
        get currentExtensions() {
            if (this.activeFilter === 'all' || !this.extensionMap[this.activeFilter]) return [];
            return this.extensionMap[this.activeFilter];
        },

        // 获取实际传给后端的 type 参数
        _getFilterType() {
            if (this.activeExtension) return this.activeExtension;
            if (this.activeFilter && this.activeFilter !== 'all') return this.activeFilter;
            return '';
        },

        // 构建包含所有筛选参数的 URL 后缀
        _buildFilterParams() {
            let params = '';
            const filterType = this._getFilterType();
            if (filterType) {
                params += `&type=${encodeURIComponent(filterType)}`;
            }
            if (this.activeTagUuid) {
                params += `&tag=${encodeURIComponent(this.activeTagUuid)}`;
            }
            const sortBy = this.$store.docs.sortBy;
            if (sortBy && sortBy !== 'default') {
                params += `&sort=${encodeURIComponent(sortBy)}`;
            }
            return params;
        },

        // 排序选项列表
        sortOptions: [
            { key: 'default', label: '默认' },
            { key: 'name_asc', label: '名称 ↑' },
            { key: 'name_desc', label: '名称 ↓' },
            { key: 'size_asc', label: '大小 ↑' },
            { key: 'size_desc', label: '大小 ↓' },
            { key: 'date_asc', label: '日期 ↑' },
            { key: 'date_desc', label: '日期 ↓' },
        ],

        // 切换排序
        async changeSort(sortKey) {
            this.$store.docs.sortBy = sortKey;
            if (this.$store.docs.isSearchMode) return; // 搜索模式不支持自定义排序
            await this.loadDocuments(1);
        },

        // 计算要显示的页码数组
        get visiblePages() {
            const pages = [];
            const current = this.$store.docs.currentPage;
            const total = this.$store.docs.totalPages;
            for (let i = 1; i <= total; i++) {
                if (i === 1 || i === total || (i >= current - 2 && i <= current + 2)) {
                    pages.push(i);
                }
            }
            return pages;
        },

        // 检查页码前是否需要省略号
        showEllipsisBefore(p) {
            const pages = this.visiblePages;
            const idx = pages.indexOf(p);
            return idx > 0 && pages[idx] - pages[idx - 1] > 1;
        },

        init() {
            // 监听 viewMode 变化，持久化到 localStorage
            this.$watch('viewMode', val => localStorage.setItem('viewMode', val));

            // 监听刷新列表事件
            window.addEventListener('refresh-list', () => {
                this.refreshList();
            });

            // 加载标签列表
            this.loadAvailableTags();

            // 初始加载文档列表
            this.loadDocuments(1);
        },

        // 加载可用标签列表
        async loadAvailableTags() {
            try {
                const resp = await fetch('/api/tags/');
                if (resp.ok) {
                    this.availableTags = await resp.json();
                }
            } catch (e) {
                console.error('加载标签列表失败:', e);
            }
        },

        // 加载文档列表
        async loadDocuments(page = 1) {
            const store = this.$store.docs;
            store.loading = true;

            try {
                let url = `/api/documents?page=${page}&limit=${store.limit}`;
                url += this._buildFilterParams();

                const resp = await fetch(url);
                if (!resp.ok) throw new Error('加载文档列表失败');

                const data = await resp.json();
                store.items = data.documents || [];
                store.currentPage = data.page || 1;
                store.totalPages = data.total_pages || 1;
                store.totalCount = data.total_count || 0;
                store.isSearchMode = false;
            } catch (e) {
                console.error('加载文档列表失败:', e);
            } finally {
                store.loading = false;
            }
        },

        // 内部搜索执行（resetFilters=true 时重置筛选条件）
        async _executeSearch(resetFilters) {
            const q = this.$store.docs.searchQuery.trim();
            if (!q) {
                if (resetFilters) this.clearSearch();
                return;
            }

            // 取消上一次未完成的请求
            if (this._searchController) {
                this._searchController.abort();
            }
            this._searchController = new AbortController();

            this.searching = true;

            if (resetFilters) {
                this.showSearchResults = true;
                this.activeFilter = 'all';
                this.activeExtension = '';
                this.activeTagUuid = '';
                this.$store.docs.isSearchMode = true;
            }

            const store = this.$store.docs;
            store.loading = true;

            try {
                let url = `/api/search?q=${encodeURIComponent(q)}&page=1&limit=${store.limit}`;
                url += this._buildFilterParams();

                const resp = await fetch(url, {
                    signal: this._searchController.signal
                });

                if (!resp.ok) throw new Error('搜索失败');

                const data = await resp.json();
                store.items = data.results || [];
                store.currentPage = data.page || 1;
                store.totalPages = data.total_pages || 1;
                store.totalCount = data.total_count || 0;
            } catch (e) {
                if (e.name !== 'AbortError') {
                    console.error('搜索失败:', e);
                }
            } finally {
                this._searchController = null;
                this.searching = false;
                store.loading = false;
            }
        },

        // 搜索文档
        async search() {
            await this._executeSearch(true);
        },

        // 清除搜索
        clearSearch() {
            this.$store.docs.searchQuery = '';
            this.showSearchResults = false;
            this.activeFilter = 'all';
            this.activeExtension = '';
            this.activeTagUuid = '';
            this.$store.docs.isSearchMode = false;
            this.loadDocuments(1);
        },

        // 按类型过滤
        async filterByType(type) {
            this.activeFilter = type || 'all';
            this.activeExtension = '';
            this.activeTagUuid = '';

            if (this.showSearchResults) {
                // 搜索模式下过滤
                await this.searchWithFilter();
            } else {
                // 普通列表模式过滤
                await this.loadDocuments(1);
            }
        },

        // 按具体扩展名过滤
        async filterByExtension(ext) {
            this.activeExtension = ext;

            if (this.showSearchResults) {
                await this.searchWithFilter();
            } else {
                await this.loadDocuments(1);
            }
        },

        // 按标签筛选
        async filterByTag(tagUuid) {
            this.activeTagUuid = tagUuid;

            if (this.showSearchResults) {
                await this.searchWithFilter();
            } else {
                await this.loadDocuments(1);
            }
        },

        // 搜索时带过滤
        async searchWithFilter() {
            await this._executeSearch(false);
        },

        // 翻页
        async goToPage(page) {
            const store = this.$store.docs;
            if (page < 1 || page > store.totalPages) return;

            store.loading = true;

            try {
                let url;
                const filterParams = this._buildFilterParams();
                if (store.isSearchMode) {
                    url = `/api/search?q=${encodeURIComponent(store.searchQuery)}&page=${page}&limit=${store.limit}`;
                    url += filterParams;
                } else {
                    url = `/api/documents?page=${page}&limit=${store.limit}`;
                    url += filterParams;
                }

                const resp = await fetch(url);
                if (!resp.ok) throw new Error('加载失败');

                const data = await resp.json();
                if (store.isSearchMode) {
                    store.items = data.results || [];
                } else {
                    store.items = data.documents || [];
                }
                store.currentPage = data.page || 1;
                store.totalPages = data.total_pages || 1;
                store.totalCount = data.total_count || 0;
            } catch (e) {
                console.error('翻页失败:', e);
            } finally {
                store.loading = false;
            }
        },

        // 刷新当前列表
        async refreshList() {
            const store = this.$store.docs;
            await this.loadAvailableTags();
            await this.goToPage(store.currentPage);
        },

        // 打开文档详情
        async openDetail(uuid) {
            const store = this.$store.docs;
            store.loading = true;

            try {
                const resp = await fetch(`/api/documents/${uuid}`);
                if (!resp.ok) throw new Error('获取文档详情失败');

                const doc = await resp.json();
                store.currentDoc = doc;
                this.showModal = true;
                // 通知 documentDetail 组件更新格式数据
                this.$nextTick(() => {
                    window.dispatchEvent(new CustomEvent('doc-detail-opened', { detail: doc }));
                });
            } catch (e) {
                console.error('获取文档详情失败:', e);
            } finally {
                store.loading = false;
            }
        },

        // 关闭模态框
        closeModal() {
            this.showModal = false;
            this.$store.docs.currentDoc = null;
        },

        // 切换选择模式
        toggleSelectMode() {
            this.selectMode = !this.selectMode;
            if (!this.selectMode) {
                this.selectedUuids = [];
            }
        },

        // 退出选择模式
        exitSelectMode() {
            this.selectMode = false;
            this.selectedUuids = [];
        },

        // 切换单个文档选中状态
        toggleSelect(uuid) {
            const idx = this.selectedUuids.indexOf(uuid);
            if (idx === -1) {
                this.selectedUuids.push(uuid);
            } else {
                this.selectedUuids.splice(idx, 1);
            }
        },

        // 是否已选中
        isSelected(uuid) {
            return this.selectedUuids.includes(uuid);
        },

        // 全选当前页
        selectAll() {
            const allUuids = this.$store.docs.items.map(d => d.uuid);
            this.selectedUuids = [...allUuids];
        },

        // 取消全选
        deselectAll() {
            this.selectedUuids = [];
        },

        // 是否全选
        get isAllSelected() {
            const items = this.$store.docs.items;
            return items.length > 0 && this.selectedUuids.length === items.length;
        },

        // 批量删除
        async batchDelete() {
            if (this.selectedUuids.length === 0) return;

            if (!confirm(`确定要删除选中的 ${this.selectedUuids.length} 个文档吗？仅删除数据库记录，不删除源文件。此操作不可恢复。`)) {
                return;
            }

            try {
                const resp = await fetch('/api/documents/batch-delete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ uuids: this.selectedUuids })
                });

                if (!resp.ok) throw new Error('批量删除失败');

                const result = await resp.json();
                this.selectedUuids = [];
                this.selectMode = false;

                // 刷新列表
                window.dispatchEvent(new CustomEvent('refresh-list'));
            } catch (e) {
                console.error('批量删除失败:', e);
                alert('批量删除失败，请重试');
            }
        },

        // ── 批量执行任务 ────────────────────────────────────

        async openBatchExecuteModal() {
            try {
                const resp = await fetch('/api/plugins/handlers');
                if (!resp.ok) throw new Error('获取处理器列表失败');
                this.availableHandlers = await resp.json();
            } catch (e) {
                console.error('获取处理器列表失败:', e);
                alert('获取处理器列表失败，请重试');
                return;
            }
            this.selectedHandlers = [];
            this.showBatchExecuteModal = true;
            this.$store.docs.pluginSettingsOpen = true;
        },

        get groupedHandlers() {
            const typeOrder = ['extract', 'thumbnail', 'summarize'];
            const typeLabels = { extract: '文本提取', thumbnail: '缩略图生成', summarize: '摘要生成' };
            const groups = {};
            for (const h of this.availableHandlers) {
                const t = h.handler_type;
                if (!groups[t]) groups[t] = { type: t, label: typeLabels[t] || t, handlers: [] };
                groups[t].handlers.push(h);
            }
            return typeOrder.filter(t => groups[t]).map(t => groups[t]);
        },

        toggleHandler(plugin_name, handler_name) {
            const idx = this.selectedHandlers.findIndex(
                h => h.plugin_name === plugin_name && h.handler_name === handler_name
            );
            if (idx === -1) {
                this.selectedHandlers.push({ plugin_name, handler_name });
            } else {
                this.selectedHandlers.splice(idx, 1);
            }
        },

        isHandlerSelected(plugin_name, handler_name) {
            return this.selectedHandlers.some(
                h => h.plugin_name === plugin_name && h.handler_name === handler_name
            );
        },

        async submitBatchExecute() {
            if (this.selectedHandlers.length === 0 || this.selectedUuids.length === 0) return;
            this.batchExecuteLoading = true;
            try {
                const resp = await fetch('/api/batch-jobs/', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        document_uuids: this.selectedUuids,
                        handlers: this.selectedHandlers,
                    }),
                });
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    throw new Error(err.detail || '创建任务失败');
                }
                this.closeBatchExecuteModal();
                showToast('任务已创建，可在设置/后台任务中查看');
            } catch (e) {
                console.error('批量执行失败:', e);
                alert(e.message || '批量执行失败，请重试');
            } finally {
                this.batchExecuteLoading = false;
            }
        },

        closeBatchExecuteModal() {
            this.showBatchExecuteModal = false;
            this.selectedHandlers = [];
            this.$store.docs.pluginSettingsOpen = false;
        },

        // 批量添加标签
        async batchAddTag() {
            const tagName = this.batchTagName.trim();
            if (!tagName || this.selectedUuids.length === 0) return;

            try {
                const resp = await fetch('/api/documents/batch-add-tags', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ uuids: this.selectedUuids, tag_names: [tagName] })
                });

                if (!resp.ok) throw new Error('批量添加标签失败');

                this.batchTagName = '';
                this.showBatchTagInput = false;

                // 刷新列表和标签
                window.dispatchEvent(new CustomEvent('refresh-list'));
            } catch (e) {
                console.error('批量添加标签失败:', e);
                alert('批量添加标签失败，请重试');
            }
        }
    }));

    // 文档卡片组件：documentCard
    Alpine.data('documentCard', () => ({
        // 卡片级别的交互逻辑可以在这里添加
    }));

    // 分页组件：pagination
    Alpine.data('pagination', () => ({
        // 分页逻辑在主应用组件中处理
    }));
});
