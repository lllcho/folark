/**
 * folark - 设置中心组件：settingsApp
 */
document.addEventListener('alpine:init', () => {
    Alpine.data('settingsApp', () => ({
        activeTab: 'general',
        mobileView: 'menu',  // 'menu' | 'content'

        // 通用设置
        settings: {},
        settingsLoading: false,
        settingsSaving: false,
        settingsMsg: null,

        // 可编辑表单字段
        form: {
            log_level: 'DEBUG',
            max_upload_size_mb: 500,
            import_dir_whitelist: [],
            document_extensions: [],
            ebook_extensions: [],
            text_extensions: [],
            image_extensions: [],
            audio_extensions: [],
            video_extensions: [],
            archive_extensions: [],
        },
        newWhitelistDir: '',
        newExt: { document: '', ebook: '', text: '', image: '', audio: '', video: '', archive: '' },

        // 插件管理
        plugins: [],
        pluginsLoading: false,
        pluginsError: null,
        expandedPlugin: null,
        expandedHandlerTypes: {},    // key: "pluginName:type" → boolean
        editingConfig: {},           // key: pluginName → {key: value} 编辑中的配置
        configSaving: {},            // key: pluginName → boolean
        pluginSettingsModal: null,   // 当前打开设置弹窗的 plugin name，null=关闭

        // 标签管理
        tags: [],
        tagsLoading: false,
        editingTagUuid: null,
        editingTagName: '',
        colorPickerTagUuid: null,
        presetColors: [
            '#409EFF', '#67C23A', '#E6A23C', '#F56C6C', '#909399',
            '#8B5CF6', '#EC4899', '#14B8A6', '#F97316', '#6366F1',
            '#0EA5E9', '#84CC16', '#EF4444', '#A855F7', '#F59E0B',
            '#10B981', '#3B82F6', '#E11D48', '#8B5E3C', '#6B7280',
        ],

        // 后台任务
        batchJobs: [],
        expandedJobUuid: null,
        batchJobDetail: null,
        batchJobsLoading: false,
        batchJobPollingTimer: null,
        batchJobControlling: {},  // key: uuid → boolean 防重复点击
        failedItemsExpanded: false,

        // 关于
        about: {},
        aboutLoading: false,

        _validTabs: ['general', 'tags', 'plugins', 'batch-jobs', 'about'],

        init() {
            // 从 URL hash 恢复状态
            const hash = window.location.hash.slice(1);
            if (this._validTabs.includes(hash)) {
                this.activeTab = hash;
                this.mobileView = 'content';
            }

            this.loadSettings();

            // 直接访问 about 页面时手动加载
            if (this.activeTab === 'about') this.loadAbout();

            this.$watch('activeTab', (tab) => {
                if (tab === 'tags' && this.tags.length === 0) this.loadTags();
                if (tab === 'plugins' && this.plugins.length === 0) this.loadPlugins();
                if (tab === 'batch-jobs') this.loadBatchJobs();
                if (tab !== 'batch-jobs') this.stopBatchJobPolling();
                if (tab === 'about' && !this.about.app_version) this.loadAbout();
            });

            // 浏览器后退/前进按钮（含移动端返回手势）
            window.addEventListener('popstate', (e) => {
                const state = e.state;
                if (state && state.tab) {
                    this.activeTab = state.tab;
                    this.mobileView = 'content';
                } else {
                    // 回到菜单页
                    this.mobileView = 'menu';
                    this.activeTab = 'general';
                }
            });

            // 页面卸载时清理 timer
            window.addEventListener('beforeunload', () => this.stopBatchJobPolling());

            // 页面不可见时暂停轮询，可见时恢复
            document.addEventListener('visibilitychange', () => {
                if (document.hidden) {
                    this.stopBatchJobPolling();
                } else if (this.activeTab === 'batch-jobs') {
                    this.maybeStartPolling();
                }
            });

            // 替换当前 history 记录，标记为菜单态（无 hash 时）或子页态
            if (this.mobileView === 'content') {
                history.replaceState({ tab: this.activeTab }, '', '#' + this.activeTab);
            } else {
                history.replaceState(null, '', window.location.pathname);
            }
        },

        // ---- 移动端导航 ----
        openMobileTab(tab) {
            this.activeTab = tab;
            this.mobileView = 'content';
            history.pushState({ tab }, '', '#' + tab);
        },
        backToMobileMenu() {
            this.mobileView = 'menu';
            history.pushState(null, '', window.location.pathname);
        },
        // PC 端切换 tab 时同步 hash（replaceState 不产生历史记录）
        switchTab(tab) {
            this.activeTab = tab;
            history.replaceState({ tab }, '', '#' + tab);
        },
        get mobileTabTitle() {
            const titles = {
                general: '通用设置', tags: '标签管理', plugins: '插件管理',
                'batch-jobs': '后台任务', about: '关于'
            };
            return titles[this.activeTab] || '';
        },

        // ---- 通用设置 ----
        async loadSettings() {
            this.settingsLoading = true;
            try {
                const resp = await fetch('/api/settings');
                if (!resp.ok) throw new Error('加载设置失败');
                this.settings = await resp.json();
                // 填充表单
                this.form.log_level = this.settings.log_level || 'DEBUG';
                this.form.max_upload_size_mb = Math.round((this.settings.max_upload_size || 0) / 1024 / 1024);
                this.form.import_dir_whitelist = [...(this.settings.import_dir_whitelist || [])];
                this.form.document_extensions = [...(this.settings.document_extensions || [])];
                this.form.ebook_extensions = [...(this.settings.ebook_extensions || [])];
                this.form.text_extensions = [...(this.settings.text_extensions || [])];
                this.form.image_extensions = [...(this.settings.image_extensions || [])];
                this.form.audio_extensions = [...(this.settings.audio_extensions || [])];
                this.form.video_extensions = [...(this.settings.video_extensions || [])];
                this.form.archive_extensions = [...(this.settings.archive_extensions || [])];
            } catch (e) {
                console.error('加载设置失败:', e);
            } finally {
                this.settingsLoading = false;
            }
        },

        async saveSettings() {
            this.settingsSaving = true;
            this.settingsMsg = null;
            try {
                const payload = {
                    LOG_LEVEL: this.form.log_level,
                    MAX_UPLOAD_SIZE: this.form.max_upload_size_mb * 1024 * 1024,
                    IMPORT_DIR_WHITELIST: this.form.import_dir_whitelist,
                    DOCUMENT_EXTENSIONS: this.form.document_extensions,
                    EBOOK_EXTENSIONS: this.form.ebook_extensions,
                    TEXT_EXTENSIONS: this.form.text_extensions,
                    IMAGE_EXTENSIONS: this.form.image_extensions,
                    AUDIO_EXTENSIONS: this.form.audio_extensions,
                    VIDEO_EXTENSIONS: this.form.video_extensions,
                    ARCHIVE_EXTENSIONS: this.form.archive_extensions,
                };
                const resp = await fetch('/api/settings', {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                if (!resp.ok) {
                    const err = await resp.json().catch(() => null);
                    throw new Error(err?.detail || '保存失败');
                }
                this.settingsMsg = { type: 'success', text: '配置已保存，重启服务后生效' };
                setTimeout(() => this.settingsMsg = null, 3000);
            } catch (e) {
                this.settingsMsg = { type: 'error', text: e.message || '保存失败' };
            } finally {
                this.settingsSaving = false;
            }
        },

        async resetSetting(key) {
            try {
                const resp = await fetch(`/api/settings/reset/${key}`, { method: 'POST' });
                if (!resp.ok) throw new Error('重置失败');
                await this.loadSettings();
                this.settingsMsg = { type: 'success', text: `${key} 已恢复默认值，重启服务后生效` };
                setTimeout(() => this.settingsMsg = null, 3000);
            } catch (e) {
                this.settingsMsg = { type: 'error', text: e.message || '重置失败' };
            }
        },

        // 白名单操作
        addWhitelistDir() {
            const dir = this.newWhitelistDir.trim();
            if (dir && !this.form.import_dir_whitelist.includes(dir)) {
                this.form.import_dir_whitelist.push(dir);
            }
            this.newWhitelistDir = '';
        },
        removeWhitelistDir(index) {
            this.form.import_dir_whitelist.splice(index, 1);
        },

        // 扩展名操作
        addExt(category) {
            let ext = this.newExt[category].trim().toLowerCase();
            if (!ext) return;
            if (!ext.startsWith('.')) ext = '.' + ext;
            const field = category + '_extensions';
            if (!this.form[field].includes(ext)) {
                this.form[field].push(ext);
                this.form[field].sort();
            }
            this.newExt[category] = '';
        },
        removeExt(category, index) {
            const field = category + '_extensions';
            this.form[field].splice(index, 1);
        },

        // ---- 标签管理 ----
        async loadTags() {
            this.tagsLoading = true;
            try {
                const resp = await fetch('/api/tags/stats');
                if (!resp.ok) throw new Error('加载标签列表失败');
                this.tags = await resp.json();
            } catch (e) {
                console.error('加载标签列表失败:', e);
            } finally {
                this.tagsLoading = false;
            }
        },

        async deleteTag(uuid, name) {
            if (!confirm(`确定要删除标签「${name}」吗？该标签将从所有文档中移除。`)) return;
            try {
                const resp = await fetch(`/api/tags/${uuid}`, { method: 'DELETE' });
                if (!resp.ok) throw new Error('删除标签失败');
                this.tags = this.tags.filter(t => t.uuid !== uuid);
            } catch (e) {
                console.error('删除标签失败:', e);
                alert('删除标签失败，请重试');
            }
        },

        async updateTag(uuid, data) {
            try {
                const resp = await fetch(`/api/tags/${uuid}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });
                if (!resp.ok) {
                    const err = await resp.json().catch(() => null);
                    throw new Error(err?.detail || '更新标签失败');
                }
                const updated = await resp.json();
                const tag = this.tags.find(t => t.uuid === uuid);
                if (tag) {
                    tag.name = updated.name;
                    tag.color = updated.color;
                }
                return true;
            } catch (e) {
                console.error('更新标签失败:', e);
                alert(e.message || '更新标签失败');
                return false;
            }
        },

        startEditName(tag) {
            this.editingTagUuid = tag.uuid;
            this.editingTagName = tag.name;
        },

        async saveEditName(tag) {
            const newName = this.editingTagName.trim();
            const wasEditing = this.editingTagUuid === tag.uuid;
            this.editingTagUuid = null;
            if (!wasEditing || !newName || newName === tag.name) return;
            const ok = await this.updateTag(tag.uuid, { name: newName });
            if (!ok) {
                // 回滚本地显示
                const t = this.tags.find(t => t.uuid === tag.uuid);
                if (t) t.name = tag.name;
            }
        },

        async pickColor(uuid, color) {
            this.colorPickerTagUuid = null;
            await this.updateTag(uuid, { color });
        },

        // ---- 插件管理 ----
        async loadPlugins() {
            this.pluginsLoading = true;
            this.pluginsError = null;
            try {
                const resp = await fetch('/api/plugins');
                if (!resp.ok) throw new Error('加载插件列表失败');
                this.plugins = await resp.json();
            } catch (e) {
                console.error('加载插件列表失败:', e);
                this.pluginsError = e.message || '加载插件列表失败';
            } finally {
                this.pluginsLoading = false;
            }
        },

        toggleExpand(name) {
            if (this.expandedPlugin === name) {
                this.expandedPlugin = null;
            } else {
                this.expandedPlugin = name;
            }
        },

        toggleHandlerType(pluginName, type) {
            const key = `${pluginName}:${type}`;
            this.expandedHandlerTypes = {...this.expandedHandlerTypes, [key]: !this.expandedHandlerTypes[key]};
        },

        isHandlerTypeExpanded(pluginName, type) {
            return this.expandedHandlerTypes[`${pluginName}:${type}`] === true;
        },

        groupedTasks(plugin) {
            const tasks = plugin.tasks || [];
            const groups = {};
            for (const task of tasks) {
                const type = task.handler_type || 'extract';
                if (!groups[type]) groups[type] = [];
                groups[type].push(task);
            }
            // 按 source_types 首元素排序
            for (const type of Object.keys(groups)) {
                groups[type].sort((a, b) => {
                    const sa = (a.source_types && a.source_types[0]) || '';
                    const sb = (b.source_types && b.source_types[0]) || '';
                    return sa.localeCompare(sb);
                });
            }
            // 固定顺序：extract → thumbnail → summarize → convert → preview
            const order = [
                { type: 'extract', label: '文本提取' },
                { type: 'thumbnail', label: '缩略图' },
                { type: 'summarize', label: '摘要' },
                { type: 'convert', label: '格式转换' },
                { type: 'preview', label: '预览' },
            ];
            const result = [];
            for (const { type, label } of order) {
                if (groups[type]) result.push({ type, label, tasks: groups[type] });
            }
            // 其他未知 type
            for (const type of Object.keys(groups)) {
                if (!order.some(o => o.type === type)) {
                    result.push({ type, label: type, tasks: groups[type] });
                }
            }
            return result;
        },

        openPluginSettings(pluginName) {
            this.pluginSettingsModal = pluginName;
            this.configSaving = {...this.configSaving, [pluginName]: false};
            this.initEditingConfig(this.plugins.find(p => p.name === pluginName));
            this.$store.docs.pluginSettingsOpen = true;
        },

        closePluginSettings() {
            this.pluginSettingsModal = null;
            this.$store.docs.pluginSettingsOpen = false;
        },

        get settingsModalPlugin() {
            return this.plugins.find(p => p.name === this.pluginSettingsModal) || null;
        },

        async togglePlugin(name, enabled) {
            try {
                const resp = await fetch(`/api/plugins/${encodeURIComponent(name)}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ enabled })
                });
                if (!resp.ok) throw new Error('更新插件状态失败');

                const plugin = this.plugins.find(p => p.name === name);
                if (plugin) plugin.enabled = enabled;
            } catch (e) {
                console.error('更新插件状态失败:', e);
                this.pluginsError = e.message || '更新插件状态失败';
            }
        },

        async toggleTask(pluginName, handlerName, enabled) {
            try {
                const resp = await fetch(`/api/plugins/${encodeURIComponent(pluginName)}/handlers/${encodeURIComponent(handlerName)}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ enabled })
                });
                if (!resp.ok) throw new Error('更新处理器状态失败');

                const plugin = this.plugins.find(p => p.name === pluginName);
                if (plugin) {
                    const task = plugin.tasks.find(t => t.handler_name === handlerName);
                    if (task) task.enabled = enabled ? 1 : 0;
                }
            } catch (e) {
                console.error('更新处理器状态失败:', e);
                this.pluginsError = e.message || '更新处理器状态失败';
            }
        },

        // ---- 插件配置 ----
        hasConfig(plugin) {
            return plugin.default_config && Object.keys(plugin.default_config).length > 0;
        },

        initEditingConfig(plugin) {
            this.editingConfig = {...this.editingConfig, [plugin.name]: {...(plugin.config || {})}};
        },

        getConfigValue(pluginName, key) {
            if (this.editingConfig[pluginName] && key in this.editingConfig[pluginName]) {
                return this.editingConfig[pluginName][key];
            }
            const plugin = this.plugins.find(p => p.name === pluginName);
            return plugin ? (plugin.config || {})[key] : undefined;
        },

        setConfigValue(pluginName, key, value) {
            if (!this.editingConfig[pluginName]) {
                const plugin = this.plugins.find(p => p.name === pluginName);
                this.editingConfig = {...this.editingConfig, [pluginName]: {...(plugin?.config || {})}};
            }
            this.editingConfig[pluginName][key] = value;
            this.editingConfig = {...this.editingConfig};
        },

        configValueType(value) {
            if (typeof value === 'boolean') return 'bool';
            if (typeof value === 'number') return 'number';
            return 'string';
        },

        async savePluginConfig(pluginName) {
            this.configSaving = {...this.configSaving, [pluginName]: true};
            try {
                const configData = this.editingConfig[pluginName];
                if (!configData) return;

                // 转换类型：确保 number 字段是 number
                const plugin = this.plugins.find(p => p.name === pluginName);
                const cleaned = {};
                for (const [key, val] of Object.entries(configData)) {
                    const defaultVal = plugin?.default_config?.[key];
                    if (typeof defaultVal === 'number') {
                        cleaned[key] = Number(val);
                    } else if (typeof defaultVal === 'boolean') {
                        cleaned[key] = Boolean(val);
                    } else {
                        cleaned[key] = val;
                    }
                }

                const resp = await fetch(`/api/plugins/${encodeURIComponent(pluginName)}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ config: cleaned })
                });
                if (!resp.ok) {
                    const err = await resp.json().catch(() => null);
                    throw new Error(err?.detail || '保存配置失败');
                }

                // 更新本地状态
                if (plugin) plugin.config = cleaned;
                this.pluginsError = null;
            } catch (e) {
                console.error('保存插件配置失败:', e);
                this.pluginsError = e.message || '保存插件配置失败';
            } finally {
                this.configSaving = {...this.configSaving, [pluginName]: false};
            }
        },

        resetPluginConfig(pluginName) {
            const plugin = this.plugins.find(p => p.name === pluginName);
            if (plugin) {
                this.editingConfig = {...this.editingConfig, [pluginName]: {...(plugin.default_config || {})}};
            }
        },

        // ---- 后台任务 ----
        async loadBatchJobs() {
            this.batchJobsLoading = true;
            try {
                const resp = await fetch('/api/batch-jobs');
                if (!resp.ok) throw new Error('加载任务列表失败');
                const data = await resp.json();
                this.batchJobs = data.items || [];
                this.maybeStartPolling();
            } catch (e) {
                console.error('加载任务列表失败:', e);
            } finally {
                this.batchJobsLoading = false;
            }
        },

        async loadBatchJobDetail(uuid) {
            try {
                const resp = await fetch(`/api/batch-jobs/${uuid}`);
                if (!resp.ok) throw new Error('加载任务详情失败');
                this.batchJobDetail = await resp.json();
            } catch (e) {
                console.error('加载任务详情失败:', e);
            }
        },

        async controlBatchJob(uuid, action) {
            if (this.batchJobControlling[uuid]) return;
            this.batchJobControlling = {...this.batchJobControlling, [uuid]: true};
            // 暂停轮询，避免竞态导致 DOM 重建丢失事件
            this.stopBatchJobPolling();
            try {
                const resp = await fetch(`/api/batch-jobs/${uuid}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ action })
                });
                if (!resp.ok) {
                    const err = await resp.json().catch(() => null);
                    throw new Error(err?.detail || '操作失败');
                }
                await this.loadBatchJobs();
                if (this.expandedJobUuid === uuid) {
                    await this.loadBatchJobDetail(uuid);
                }
            } catch (e) {
                console.error('操作批量任务失败:', e);
                alert(e.message || '操作失败，请重试');
                // 失败时重新加载以同步状态
                await this.loadBatchJobs();
            } finally {
                this.batchJobControlling = {...this.batchJobControlling, [uuid]: false};
                this.maybeStartPolling();
            }
        },

        async toggleJobDetail(uuid) {
            if (this.expandedJobUuid === uuid) {
                this.expandedJobUuid = null;
                this.batchJobDetail = null;
                this.failedItemsExpanded = false;
            } else {
                this.expandedJobUuid = uuid;
                this.batchJobDetail = null;
                this.failedItemsExpanded = false;
                await this.loadBatchJobDetail(uuid);
            }
        },

        maybeStartPolling() {
            const hasRunning = this.batchJobs.some(j => j.status === 'running');
            if (hasRunning) {
                this.startBatchJobPolling();
            } else {
                this.stopBatchJobPolling();
            }
        },

        startBatchJobPolling() {
            if (this.batchJobPollingTimer) return; // 已在轮询
            this.batchJobPollingTimer = setInterval(async () => {
                try {
                    const resp = await fetch('/api/batch-jobs');
                    if (!resp.ok) return;
                    const data = await resp.json();
                    this.batchJobs = data.items || [];

                    // 如果展开了详情，也刷新
                    if (this.expandedJobUuid) {
                        await this.loadBatchJobDetail(this.expandedJobUuid);
                    }

                    // 检查是否还有运行中的任务
                    const hasRunning = this.batchJobs.some(j => j.status === 'running');
                    if (!hasRunning) {
                        this.stopBatchJobPolling();
                    }
                } catch (e) {
                    console.error('轮询任务失败:', e);
                }
            }, 2000);
        },

        stopBatchJobPolling() {
            if (this.batchJobPollingTimer) {
                clearInterval(this.batchJobPollingTimer);
                this.batchJobPollingTimer = null;
            }
        },

        formatDuration(startStr, endStr) {
            if (!startStr || !endStr) return '';
            const start = new Date(startStr);
            const end = new Date(endStr);
            const sec = Math.round((end - start) / 1000);
            if (sec < 60) return sec + ' 秒';
            const min = Math.floor(sec / 60);
            const s = sec % 60;
            if (min < 60) return min + ' 分 ' + s + ' 秒';
            const hr = Math.floor(min / 60);
            const m = min % 60;
            return hr + ' 时 ' + m + ' 分';
        },

        // ---- 关于 ----
        async loadAbout() {
            this.aboutLoading = true;
            try {
                const resp = await fetch('/api/settings/about');
                if (!resp.ok) throw new Error('加载系统信息失败');
                this.about = await resp.json();
            } catch (e) {
                console.error('加载系统信息失败:', e);
            } finally {
                this.aboutLoading = false;
            }
        }
    }));
});
