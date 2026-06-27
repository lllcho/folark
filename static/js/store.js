/**
 * folark - 全局 Store：共享文档状态
 */
document.addEventListener('alpine:init', () => {
    Alpine.store('docs', {
        items: [],           // 当前文档列表
        totalCount: 0,       // 总数
        currentPage: 1,      // 当前页
        totalPages: 1,       // 总页数
        limit: 20,           // 每页数量
        filterType: '',      // 当前过滤类型
        searchQuery: '',     // 当前搜索关键词
        isSearchMode: false, // 是否在搜索模式
        sortBy: 'default',   // 排序方式
        currentDoc: null,    // 当前查看的文档详情（JSON 对象）
        pluginSettingsOpen: false, // 插件设置模态框是否打开
        loading: false,      // 列表加载中
    });
});
